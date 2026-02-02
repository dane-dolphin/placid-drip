import frappe
from frappe.rate_limiter import rate_limit
from frappe.utils import now_datetime, get_datetime
from placid_drip.access import resolve_user_batch_for_course, can_access_lesson
from lms.lms import utils as lms_utils
from placid_drip.constants import RATE_LIMIT, RATE_LIMIT_WINDOW

LESSON_DTYPE = "Course Lesson"
CHAPTER_DTYPE = "Course Chapter"
_FRAPPE_RPC_KEYS = {
    "cmd", "data", "_",
    "ignore_permissions", "freeze", "freeze_message",
    "run_method", "docs", "doc",
}

# def _log(msg, **kv):
#     # consistent, readable logs
#     extra = " ".join([f"{k}={repr(v)}" for k, v in kv.items()])
#     frappe.logger("placid_drip").warning(f"[drip-outline] {msg} {extra}".strip())


@frappe.whitelist()
@rate_limit(limit=RATE_LIMIT, seconds=RATE_LIMIT_WINDOW)
def get_lesson(*args, **kwargs):
    clean_kwargs = {k: v for k, v in kwargs.items() if k not in _FRAPPE_RPC_KEYS}

    course = clean_kwargs.get("course") or clean_kwargs.get("course_name")
    chapter = clean_kwargs.get("chapter")
    lesson = clean_kwargs.get("lesson")

    result = lms_utils.get_lesson(*args, **clean_kwargs)

    # LMS may return dict/no_preview OR full lesson dict
    if (
        isinstance(result, dict)
        and result.get("no_preview")
        and course
        and chapter
        and lesson
        and _is_evaluator_for_course(frappe.session.user, course)
    ):
        # ✅ Resolve the SAME way LMS does
        chapter_name = frappe.db.get_value("Chapter Reference", {"parent": course, "idx": int(chapter)}, "chapter")
        lesson_name = frappe.db.get_value("Lesson Reference", {"parent": chapter_name, "idx": int(lesson)}, "lesson")
        if not lesson_name:
            return {}

        # ✅ Return the SAME shape LMS returns (copy from lms get_lesson)
        lesson_details = frappe.db.get_value(
            "Course Lesson",
            lesson_name,
            [
                "name","title","include_in_preview","body","creation","youtube","quiz_id","question",
                "file_type","instructor_notes","course","content","instructor_content",
            ],
            as_dict=True,
        ) or {}

        if not lesson_details:
            return {}

        # Fill the same extra fields LMS adds
        lesson_details.chapter_title = frappe.db.get_value("Course Chapter", chapter_name, "title")
        neighbours = lms_utils.get_neighbour_lesson(course, int(chapter), int(lesson))
        lesson_details.next = neighbours["next"]
        lesson_details.prev = neighbours["prev"]
        lesson_details.progress = 0  # evaluator progress typically irrelevant; or call get_progress if you want
        lesson_details.membership = True  # effectively bypass
        lesson_details.icon = lms_utils.get_lesson_icon(lesson_details.body, lesson_details.content)
        lesson_details.instructors = lms_utils.get_instructors("LMS Course", course)
        course_info = frappe.db.get_value("LMS Course", course, ["title","paid_certificate","disable_self_learning"], as_dict=1)
        lesson_details.course_title = course_info.title
        lesson_details.paid_certificate = course_info.paid_certificate
        lesson_details.disable_self_learning = course_info.disable_self_learning
        lesson_details.videos = lms_utils.get_video_details(lesson_name)

        return lesson_details

    return result

@frappe.whitelist(allow_guest=True)
@rate_limit(limit=RATE_LIMIT, seconds=RATE_LIMIT_WINDOW)
def get_course_outline(*args, **kwargs):
    # _log("OVERRIDE HIT", user=frappe.session.user, args_len=len(args), kwargs_keys=list(kwargs.keys()))

    # 1) clean kwargs
    clean_kwargs = {k: v for k, v in kwargs.items() if k not in _FRAPPE_RPC_KEYS}
    # _log("clean_kwargs prepared", clean_kwargs=clean_kwargs) 
    # 2) call original
    # _log("calling original lms.lms.utils.get_course_outline")
    result = lms_utils.get_course_outline(*args, **clean_kwargs)
    # _log("original returned", result_type=type(result).__name__, has_message=isinstance(result, dict) and "message" in result)

    # 3) extract outline
    outline = result.get("message") if isinstance(result, dict) else result
    # _log("outline extracted", outline_type=type(outline).__name__, outline_len=(len(outline) if isinstance(outline, list) else None))

    # 4) sanity checks
    if not outline:
        # _log("outline empty -> returning outline as-is (empty)")
        return outline  # return list/None, not dict
    
    if frappe.session.user == "Guest":
        for ch in outline:
            for lesson in ch.get("lessons", []):
                lesson["is_locked"] = 1
                lesson["opens_at"] = None
                lesson["lock_reason"] = "Please log in to view lessons."
        return outline

    enforce = _should_enforce_drip()
    # _log("should_enforce_drip evaluated", enforce=enforce)
    if not enforce:
        # _log("not enforcing drip -> returning outline unchanged")
        return outline

    # 5) resolve course
    course = clean_kwargs.get("course") or clean_kwargs.get("course_name")

    if not course:
        # fallback: sometimes lessons contain `course`
        try:
            course = outline[0].get("lessons", [{}])[0].get("course")
        except Exception:
            course = None
    # _log("course resolved", course=course)

    if not course:
        # _log("course missing -> returning outline unchanged")
        return outline
    
    if _is_evaluator_for_course(frappe.session.user, course):
        return outline
    

    # 6) resolve batch for this user+course
    batch = resolve_user_batch_for_course(frappe.session.user, course)
    # _log("batch resolved", batch=batch)

    # 7) if no batch, apply policy (lock all or unlock all)
    if not batch:
        # _log("no batch found -> applying cohort-only lock-all policy")
        for ch in outline:
            for lesson in ch.get("lessons", []):
                lesson["is_locked"] = 1
                lesson["opens_at"] = None
                lesson["lock_reason"] = "Not enrolled in a batch for this course."
        # _log("lock-all policy applied", chapters=len(outline))
        return outline

    # 8) collect lesson names
    lesson_names = [
        l["name"]
        for ch in outline
        for l in ch.get("lessons", [])
        if l.get("name")
    ]
    # _log("lesson_names collected", count=len(lesson_names))

    if not lesson_names:
        # _log("no lessons found -> returning outline unchanged")
        return outline

    # 9) fetch schedule rows
    rows = frappe.db.get_all(
        "Batch Lesson Access",
        filters={"batch": batch, "lesson": ["in", lesson_names]},
        fields=["lesson", "available_from", "force_lock"],
    )
    # _log("schedule rows fetched", rows_count=len(rows))

    by_lesson = {r["lesson"]: r for r in rows}
    now = now_datetime()
    # _log("now", now=str(now))
    # 10) annotate outline
    locked_count = 0
    for ch in outline:
        for lesson in ch.get("lessons", []):
            lname = lesson.get("name")
            r = by_lesson.get(lname)

            # defaults
            lesson["is_locked"] = 0
            lesson["opens_at"] = None
            lesson["lock_reason"] = None

            if not r:
                continue

            if r.get("force_lock"):
                lesson["is_locked"] = 1
                lesson["lock_reason"] = "Locked by cohort schedule"
                locked_count += 1
                continue

            opens = get_datetime(r.get("available_from"))
            if opens and now < opens:
                lesson["is_locked"] = 1
                lesson["opens_at"] = str(opens)  # stringify so JSON is clean
                lesson["lock_reason"] = f"Opens on {opens}"
                locked_count += 1

    # _log("annotation complete", locked_count=locked_count)

    # IMPORTANT: return outline (list) so API response becomes {"message": [ ... ]}
    return outline

def _should_enforce_drip() -> bool:
    if frappe.session.user == "Guest":
        return True

    roles = set(frappe.get_roles(frappe.session.user))

    # staff can always see everything
    if roles & {"System Manager", "LMS Instructor"}:
        return False

    return "LMS Student" in roles

def _is_evaluator_for_course(user: str, course: str) -> bool:
    return bool(
        frappe.db.exists(
            "Batch Course",
            {
                "course": course,
                "evaluator": user,
                "parenttype": "LMS Batch",
            },
        )
    )


# -------------------------
# COURSES
# -------------------------

@frappe.whitelist(allow_guest=True)
@rate_limit(limit=RATE_LIMIT, seconds=RATE_LIMIT_WINDOW)
def get_courses(filters=None, start=0):
    return lms_utils.get_courses(filters=filters, start=start)


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=RATE_LIMIT, seconds=RATE_LIMIT_WINDOW)
def get_course_details(course):
    return lms_utils.get_course_details(course)


# -------------------------
# BATCHES
# -------------------------

@frappe.whitelist(allow_guest=True)
@rate_limit(limit=RATE_LIMIT, seconds=RATE_LIMIT_WINDOW)
def get_batches(filters=None, start=0, order_by="start_date"):
    return lms_utils.get_batches(
        filters=filters,
        start=start,
        order_by=order_by,
    )


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=RATE_LIMIT, seconds=RATE_LIMIT_WINDOW)
def get_batch_details(batch):
    return lms_utils.get_batch_details(batch)


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=RATE_LIMIT, seconds=RATE_LIMIT_WINDOW)
def get_batch_courses(batch):
    return lms_utils.get_batch_courses(batch)
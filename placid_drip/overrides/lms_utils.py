import frappe
from frappe.utils import now_datetime, get_datetime
from placid_drip.access import resolve_user_batch_for_course, can_access_lesson

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
def get_lesson(*args, **kwargs):
    clean_kwargs = {k: v for k, v in kwargs.items() if k not in _FRAPPE_RPC_KEYS}

    # IMPORTANT: call original via direct import (avoid recursion)
    from lms.lms import utils as lms_utils
    result = lms_utils.get_lesson(*args, **clean_kwargs)

    lesson_doc = (result or {}).get("message") if isinstance(result, dict) and "message" in result else result
    lesson_doc = lesson_doc or {}

    course = lesson_doc.get("course") or clean_kwargs.get("course")
    lesson_name = lesson_doc.get("name") or clean_kwargs.get("lesson")

    # ✅ allow batch evaluator to view lesson content
    if course and _is_evaluator_for_course(frappe.session.user, course):
        return result

    if _should_enforce_drip() and course and lesson_name:
        allowed, reason, _next_at = can_access_lesson(frappe.session.user, course, lesson_name)
        if not allowed:
            frappe.throw(reason or "Lesson is locked.", frappe.PermissionError)

    return result

@frappe.whitelist()
def get_course_outline(*args, **kwargs):
    # _log("OVERRIDE HIT", user=frappe.session.user, args_len=len(args), kwargs_keys=list(kwargs.keys()))

    # 1) clean kwargs
    clean_kwargs = {k: v for k, v in kwargs.items() if k not in _FRAPPE_RPC_KEYS}
    # _log("clean_kwargs prepared", clean_kwargs=clean_kwargs) 
    # 2) call original
    from lms.lms import utils as lms_utils
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
        return False

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
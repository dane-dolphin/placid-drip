import json
import frappe
from frappe import _

def _require_staff(batch: str):
    # Keep this simple for now; tighten later if you want “only batch instructors/evaluators”
    user = frappe.session.user
    if user == "Guest":
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    if frappe.db.exists("Has Role", {"parent": user, "role": "Moderator"}):
        return
    # allow instructors
    if frappe.db.exists("Has Role", {"parent": user, "role": "Course Creator"}):
        return
    # optionally allow evaluators
    if frappe.db.exists("Has Role", {"parent": user, "role": "Batch Evaluator"}):
        return
    frappe.throw(_("Not permitted"), frappe.PermissionError)


@frappe.whitelist()
def get_batch_courses(batch: str):
    _require_staff(batch)
    rows = frappe.get_all(
        "Batch Course",
        filters={"parent": batch},
        fields=["course", "title"],
        order_by="idx asc",
    )
    # normalize fields for frontend
    return [{"course": r.course, "title": r.title or r.course} for r in rows]


@frappe.whitelist()
def get_course_quizzes(course: str):
    # If you want: lock this down similarly (moderator/instructor only)
    if frappe.session.user == "Guest":
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    lessons = frappe.get_all(
        "Course Lesson",
        filters={"course": course},
        fields=["name", "title", "quiz_id", "content"],
        order_by="creation asc",
    )

    found = []
    seen = set()

    def add_quiz(qid: str, lesson_name: str, lesson_title: str, source: str):
        if not qid:
            return
        key = (qid, lesson_name)
        if key in seen:
            return
        seen.add(key)
        found.append({
            "quiz": qid,
            "lesson": lesson_name,
            "lesson_title": lesson_title,
            "source": source,  # "quiz_id" or "content"
        })

    for l in lessons:
        # A) Course Lesson.quiz_id
        if l.quiz_id:
            add_quiz(l.quiz_id, l.name, l.title, "quiz_id")

        # B) EditorJS blocks
        if l.content:
            try:
                doc = json.loads(l.content)
                for b in (doc.get("blocks") or []):
                    if b.get("type") == "quiz":
                        qid = (b.get("data") or {}).get("quiz")
                        add_quiz(qid, l.name, l.title, "content")
            except Exception:
                # ignore bad JSON
                pass

    # Optionally enrich with Quiz title
    quiz_names = list({x["quiz"] for x in found})
    quiz_titles = {}
    if quiz_names:
        for q in frappe.get_all("LMS Quiz", filters={"name": ["in", quiz_names]}, fields=["name", "title"]):
            quiz_titles[q.name] = q.title

    for x in found:
        x["quiz_title"] = quiz_titles.get(x["quiz"]) or x["quiz"]

    return found


@frappe.whitelist()
def get_batch_quiz_submissions(batch: str, quiz: str = None, quizzes=None, quizzes_json: str = None):
    """
    Returns quiz submissions for members in a batch.

    Accepts any of:
      - quiz: single quiz id (string)
      - quizzes: list of quiz ids (list or json-string)
      - quizzes_json: legacy json string list
    """
    _require_staff(batch)

    quiz_ids = []

    # 1) single quiz
    if quiz:
        quiz_ids = [quiz]

    # 2) quizzes (could be list, or json string)
    elif quizzes:
        if isinstance(quizzes, str):
            try:
                quizzes = json.loads(quizzes)
            except Exception:
                # allow comma-separated string as a fallback
                quizzes = [q.strip() for q in quizzes.split(",") if q.strip()]
        if isinstance(quizzes, (list, tuple)):
            quiz_ids = list(quizzes)

    # 3) legacy quizzes_json
    elif quizzes_json:
        try:
            parsed = json.loads(quizzes_json)
            if isinstance(parsed, (list, tuple)):
                quiz_ids = list(parsed)
        except Exception:
            quiz_ids = []

    # normalize / clean
    quiz_ids = [q for q in (quiz_ids or []) if q]
    if not quiz_ids:
        return []

    # Members in this batch
    members = frappe.get_all(
        "LMS Batch Enrollment",
        filters={"batch": batch},
        pluck="member",
    )
    if not members:
        return []

    # Pull submissions
    subs = frappe.get_all(
        "LMS Quiz Submission",
        filters={
            "quiz": ["in", quiz_ids],
            "member": ["in", members],
        },
        fields=[
            "name",
            "quiz",
            "member",
            "score",
            "percentage",
            "creation",
            "modified",
            # include pass/status if these fields exist in your doctype:
            # "pass",
            # "status",
        ],
        order_by="creation desc",
        limit_page_length=5000,
    )

    # Optional: map member -> full name (User doc)
    member_ids = list({s["member"] for s in subs if s.get("member")})
    full_names = {}
    if member_ids:
        for u in frappe.get_all(
            "User",
            filters={"name": ["in", member_ids]},
            fields=["name", "full_name"],
        ):
            full_names[u["name"]] = u.get("full_name")

    for s in subs:
        s["member_name"] = full_names.get(s["member"]) or s["member"]

    return subs


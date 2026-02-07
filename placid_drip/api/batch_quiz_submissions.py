import frappe
from frappe import _

DT_BATCH = "LMS Batch"
DT_BATCH_COURSE = "Batch Course"
DT_COURSE_LESSON = "Course Lesson"

DT_QUIZ = "LMS Quiz"
DT_SUBMISSION = "LMS Quiz Submission"
DT_RESULT = "LMS Quiz Result"


def _is_admin_or_moderator(user: str) -> bool:
    roles = set(frappe.get_roles(user))
    return user == "Administrator" or ("System Manager" in roles) or ("Moderator" in roles)


def _can_access_batch(user: str, batch: str) -> bool:
    if _is_admin_or_moderator(user):
        return True
    return bool(
        frappe.db.exists(
            DT_BATCH_COURSE,
            {"parenttype": DT_BATCH, "parent": batch, "evaluator": user},
        )
    )


def _get_batch_student_ids(batch: str) -> list[str]:
    doc = frappe.get_doc(DT_BATCH, batch)
    students = getattr(doc, "students", None) or []

    ids: list[str] = []
    for s in students:
        if isinstance(s, str):
            ids.append(s)
        elif isinstance(s, dict) and s.get("student"):
            ids.append(s["student"])
        elif hasattr(s, "student"):
            ids.append(s.student)
        elif hasattr(s, "user"):
            ids.append(s.user)

    return [x for x in ids if x]


@frappe.whitelist()
def list_batch_quizzes(batch: str):
    user = frappe.session.user
    if not batch:
        frappe.throw(_("batch is required"))
    if not _can_access_batch(user, batch):
        frappe.throw(_("Not permitted"))

    courses = frappe.get_all(
        DT_BATCH_COURSE,
        filters={"parenttype": DT_BATCH, "parent": batch},
        pluck="course",
        limit_page_length=0,
    )
    courses = [c for c in courses if c]
    if not courses:
        return []

    # quiz_id is the common field on Course Lesson
    # If your field differs, change `quiz_id` below.
    quiz_rows = frappe.db.sql(
        """
        SELECT DISTINCT
            l.quiz_id AS quiz,
            q.title AS title
        FROM `tabCourse Lesson` l
        JOIN `tabLMS Quiz` q ON q.name = l.quiz_id
        WHERE
            l.course IN %(courses)s
            AND IFNULL(l.quiz_id, '') != ''
        ORDER BY q.modified DESC
        """,
        {"courses": tuple(courses)},
        as_dict=True,
    )

    return [{"name": r["quiz"], "title": r.get("title")} for r in quiz_rows if r.get("quiz")]


@frappe.whitelist()
def list_batch_quiz_submissions(batch: str, quiz: str):
    user = frappe.session.user
    if not batch or not quiz:
        frappe.throw(_("batch and quiz are required"))
    if not _can_access_batch(user, batch):
        frappe.throw(_("Not permitted"))

    student_ids = _get_batch_student_ids(batch)
    if not student_ids:
        return []

    # Most common fieldnames:
    # - quiz: Link to LMS Quiz
    # - member: user id
    fields = ["name", "member", "quiz", "score", "percentage", "status", "creation", "modified"]

    # If your doctype doesn't have some fields, Frappe will throw.
    # If that happens, run get_meta and adjust the list.
    rows = frappe.get_all(
        DT_SUBMISSION,
        filters={"quiz": quiz, "member": ["in", student_ids]},
        fields=fields,
        order_by="modified desc",
        limit_page_length=0,
    )
    return rows


@frappe.whitelist()
def get_submission_results(submission: str):
    """Return submission + associated results (LMS Quiz Result)"""
    user = frappe.session.user
    if not submission:
        frappe.throw(_("submission is required"))

    sub = frappe.get_doc(DT_SUBMISSION, submission)

    # Optional: tighten permissions later (ensure this submission belongs to a student in a batch evaluator can access)

    results = frappe.get_all(
        DT_RESULT,
        filters={"submission": submission},
        fields=["name", "question", "is_correct", "marks", "answer", "correct_answer", "creation"],
        limit_page_length=0,
    )

    return {"submission": sub.as_dict(), "results": results}
import frappe
from frappe.utils import now_datetime, get_datetime


def resolve_user_batch_for_course(user: str, course: str) -> str | None:
    rows = frappe.db.sql(
        """
        SELECT e.batch
        FROM `tabLMS Batch Enrollment` e
        JOIN `tabBatch Course` bc ON bc.parent = e.batch
        WHERE e.member = %s
          AND bc.course = %s
        LIMIT 1
        """,
        (user, course),
    )
    return rows[0][0] if rows else None

def can_access_lesson(user: str, course: str, lesson_name: str):
    """
    Enforce Batch Lesson Access:
      - find user's batch
      - if row exists for (batch, lesson), enforce available_from / force_lock
    Returns (allowed: bool, reason: str|None, next_at: datetime|None)
    """
    now = now_datetime()

    batch = resolve_user_batch_for_course(user, course)
    if not batch:
        return False, "You are not enrolled in a batch for this course.", None

    row = frappe.db.get_value(
        "Batch Lesson Access",
        {"batch": batch, "lesson": lesson_name},
        ["available_from", "force_lock"],
        as_dict=True,
    )

    # No schedule row => allow by default (non-breaking)
    if not row:
        return True, None, None

    if row.get("force_lock"):
        return False, "This lesson is locked by your cohort schedule.", None

    available_from = get_datetime(row.get("available_from"))
    if available_from and now < available_from:
        return False, f"Opens on {available_from}", available_from

    return True, None, None
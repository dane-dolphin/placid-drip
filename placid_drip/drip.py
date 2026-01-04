import frappe
from frappe.utils import now_datetime

def is_lesson_available(batch: str, lesson: str) -> bool:
    """
    Batch-level drip:
    - If no schedule row exists -> allow (non-breaking default)
    - If force_lock checked -> deny
    - Else allow only if now >= available_from
    """
    row = frappe.db.get_value(
        "Batch Lesson Access",
        {"batch": batch, "lesson": lesson},
        ["available_from", "force_lock"],
        as_dict=True,
    )

    if not row:
        return True  # default policy; change to False if you want "locked unless scheduled"

    if row.get("force_lock"):
        return False

    return now_datetime() >= row.get("available_from")
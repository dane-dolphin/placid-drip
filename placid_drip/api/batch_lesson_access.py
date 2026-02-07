import frappe
from frappe import _
from frappe.utils import now_datetime
from frappe.utils.data import get_datetime
import lms.lms.utils as lms_utils


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_evaluator_batches(doctype, txt, searchfield, start, page_len, filters=None):
    user = frappe.session.user
    roles = frappe.get_roles(user)

    # bypass for admins
    if user == "Administrator" or "System Manager" in roles or "Moderator" in roles:
        return frappe.db.sql("""
            select name, title
            from `tabLMS Batch`
            where (name like %(txt)s or title like %(txt)s)
            order by modified desc
            limit %(start)s, %(page_len)s
        """, {"txt": f"%{txt}%", "start": start, "page_len": page_len})

    # evaluator-only batches 
    return frappe.db.sql("""
        select b.name, b.title
        from `tabLMS Batch` b
        join `tabBatch Course` bc on bc.parent = b.name and bc.parenttype='LMS Batch'
        where bc.evaluator=%(user)s
          and (b.name like %(txt)s or b.title like %(txt)s)
        group by b.name, b.title
        order by b.modified desc
        limit %(start)s, %(page_len)s
    """, {"user": user, "txt": f"%{txt}%", "start": start, "page_len": page_len})


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_evaluator_courses(doctype, txt, searchfield, start, page_len, filters=None):
    user = frappe.session.user
    roles = frappe.get_roles(user)
    batch = (filters or {}).get("batch")

    if not batch:
        return []

    # Admin/moderator/system manager: show ALL courses in that batch
    if user == "Administrator" or "System Manager" in roles or "Moderator" in roles:
        return frappe.db.sql(
            """
            SELECT DISTINCT
                c.name,
                c.title
            FROM `tabBatch Course` bc
            JOIN `tabLMS Course` c ON c.name = bc.course
            WHERE
                bc.parenttype='LMS Batch'
                AND bc.parent=%(batch)s
                AND (c.name LIKE %(txt)s OR c.title LIKE %(txt)s)
            ORDER BY c.modified DESC
            LIMIT %(start)s, %(page_len)s
            """,
            {
                "batch": batch,
                "txt": f"%{txt}%",
                "start": start,
                "page_len": page_len,
            },
        )

    # Evaluator: only courses they evaluate in that batch
    return frappe.db.sql(
        """
        SELECT DISTINCT
            c.name,
            c.title
        FROM `tabBatch Course` bc
        JOIN `tabLMS Course` c ON c.name = bc.course
        WHERE
            bc.parenttype='LMS Batch'
            AND bc.parent=%(batch)s
            AND bc.evaluator=%(user)s
            AND (c.name LIKE %(txt)s OR c.title LIKE %(txt)s)
        ORDER BY c.modified DESC
        LIMIT %(start)s, %(page_len)s
        """,
        {
            "batch": batch,
            "user": user,
            "txt": f"%{txt}%",
            "start": start,
            "page_len": page_len,
        },
    )


def _is_admin_or_moderator(user: str) -> bool:
    roles = frappe.get_roles(user)
    return user == "Administrator" or "System Manager" in roles or "Moderator" in roles


def _is_evaluator_for_batch_course(user: str, batch: str, course: str) -> bool:
    return bool(
        frappe.db.exists(
            "Batch Course",
            {
                "parenttype": "LMS Batch",
                "parent": batch,
                "course": course,
                "evaluator": user,
            },
        )
    )


def _require_course_lock_access(user: str, batch: str, course: str):
    if _is_admin_or_moderator(user):
        return
    if _is_evaluator_for_batch_course(user, batch, course):
        return
    frappe.throw(_("Not permitted"))


@frappe.whitelist()
def get_batch_course_lock_details(batch: str, course: str):
    """
    Returns:
      - outline: original course outline (chapters + lessons)
      - locks_by_lesson: mapping of lesson -> {name, available_from, force_lock}
    """
    user = frappe.session.user
    if not batch or not course:
        frappe.throw(_("batch and course are required"))

    _require_course_lock_access(user, batch, course)

    # Call ORIGINAL outline function directly from module (not the overridden RPC route)
    outline = lms_utils.get_course_outline(course=course, progress=0)
    if isinstance(outline, dict) and "message" in outline:
        outline = outline["message"]

    outline = outline or []

    lesson_names = [
        l.get("name")
        for ch in outline
        for l in (ch.get("lessons") or [])
        if l.get("name")
    ]

    locks_by_lesson = {}
    if lesson_names:
        rows = frappe.get_all(
            "Batch Lesson Access",
            filters={"batch": batch, "lesson": ["in", lesson_names]},
            fields=["name", "lesson", "available_from", "force_lock"],
            limit_page_length=0,
        )
        for r in rows:
            locks_by_lesson[r["lesson"]] = {
                "name": r["name"],
                "available_from": str(r["available_from"]) if r.get("available_from") else None,
                "force_lock": int(r.get("force_lock") or 0),
            }

    return {
        "batch": batch,
        "course": course,
        "outline": outline,
        "locks_by_lesson": locks_by_lesson,
        "server_time": str(now_datetime()),
    }


@frappe.whitelist()
def bulk_save_batch_lesson_access(batch: str, course: str, changes):
    """
    changes: list of dicts
      [
        { "lesson": "LESSON-0001", "available_from": "2026-02-10" or None, "force_lock": 0/1 },
        ...
      ]

    Backend does NO diffing: it just upserts/deletes based on incoming changes.
    """
    user = frappe.session.user
    if not batch or not course:
        frappe.throw(_("batch and course are required"))

    # same permission logic as above (copy/import if you put in another module)
    roles = frappe.get_roles(user)
    is_adminish = user == "Administrator" or "System Manager" in roles or "Moderator" in roles
    if not is_adminish:
        ok = frappe.db.exists(
            "Batch Course",
            {
                "parenttype": "LMS Batch",
                "parent": batch,
                "course": course,
                "evaluator": user,
            },
        )
        if not ok:
            frappe.throw(_("Not permitted"))

    # parse JSON string if needed
    if isinstance(changes, str):
        changes = frappe.parse_json(changes)

    if not isinstance(changes, list):
        frappe.throw(_("changes must be a list"))

    # normalize and collect lessons
    normalized = []
    lesson_names = []
    for row in changes:
        if not isinstance(row, dict):
            continue
        lesson = row.get("lesson")
        if not lesson:
            continue
        available_from = row.get("available_from") or None
        force_lock = int(row.get("force_lock") or 0)

        # Optional: normalize available_from to datetime/date compatible
        # If your field is Date, sending "YYYY-MM-DD" is fine.
        # If it's Datetime, you can keep it as string; Frappe will parse.
        normalized.append(
            {
                "lesson": lesson,
                "available_from": available_from,
                "force_lock": force_lock,
            }
        )
        lesson_names.append(lesson)

    if not lesson_names:
        return {"inserted": 0, "updated": 0, "deleted": 0}

    # fetch existing docnames once (not diffing values; just to know what to update/delete)
    existing = frappe.get_all(
        "Batch Lesson Access",
        filters={"batch": batch, "course": course, "lesson": ["in", lesson_names]},
        fields=["name", "lesson"],
        limit_page_length=0,
    )
    existing_by_lesson = {r["lesson"]: r["name"] for r in existing}

    inserted = updated = deleted = 0

    for row in normalized:
        lesson = row["lesson"]
        available_from = row["available_from"]
        force_lock = row["force_lock"]

        name = existing_by_lesson.get(lesson)

        # Clear row => delete if exists
        if not available_from and not force_lock:
            if name:
                frappe.delete_doc("Batch Lesson Access", name, ignore_permissions=True)
                deleted += 1
            continue

        if name:
            frappe.db.set_value(
                "Batch Lesson Access",
                name,
                {"course": course, "available_from": available_from, "force_lock": force_lock},
                update_modified=True,
            )
            updated += 1
        else:
            doc = frappe.get_doc(
                {
                    "doctype": "Batch Lesson Access",
                    "batch": batch,
                    "course": course,  # ✅ REQUIRED
                    "lesson": lesson,
                    "available_from": available_from,
                    "force_lock": force_lock,
                }
            )
            doc.insert(ignore_permissions=True)
            inserted += 1
            existing_by_lesson[lesson] = doc.name

    return {"inserted": inserted, "updated": updated, "deleted": deleted}
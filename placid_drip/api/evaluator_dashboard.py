import frappe
from frappe import _
from typing import Dict, List, Any
from frappe.utils import flt

def _is_admin_or_moderator(user: str) -> bool:
    roles = frappe.get_roles(user)
    return user == "Administrator" or "System Manager" in roles or "Moderator" in roles

def _get_course_card_payload(course_name: str) -> dict:
    # Only real columns from `tabLMS Course`
    c = frappe.db.get_value(
        "LMS Course",
        course_name,
        [
            "name",
            "title",
            "image",
            "card_gradient",
            "short_introduction",
            "enrollments",
            "lessons",
            "rating",
            "featured",
            "tags",
        ],
        as_dict=True,
    )

    if not c:
        return {"name": course_name, "title": course_name, "instructors": []}

    # ✅ Child table: Course Instructor (parentfield=instructors)
    instr_rows = frappe.get_all(
        "Course Instructor",
        filters={
            "parenttype": "LMS Course",
            "parent": course_name,
            "parentfield": "instructors",
        },
        fields=["instructor"],
        limit_page_length=0,
    )

    instructor_ids = [r.get("instructor") for r in instr_rows if r.get("instructor")]

    # CourseCard expects `course.instructors.length` and passes each to <UserAvatar :user="instructor" />
    # Usually UserAvatar works fine with {name, full_name, user_image}
    instructors = []
    if instructor_ids:
        user_rows = frappe.get_all(
            "User",
            filters={"name": ["in", instructor_ids]},
            fields=["name", "full_name", "user_image"],
            limit_page_length=0,
        )
        # preserve original order
        by_name = {u["name"]: u for u in user_rows}
        for uid in instructor_ids:
            u = by_name.get(uid)
            if u:
                instructors.append(
                    {
                        "name": u["name"],
                        "full_name": u.get("full_name") or u["name"],
                        "user_image": u.get("user_image"),
                    }
                )

    c["instructors"] = instructors
    return c

    
@frappe.whitelist()
def get_evaluator_dashboard():
    user = frappe.session.user
    if user == "Guest" or _is_admin_or_moderator(user):
        return {"batches": [], "courses": [], "counts": {"batches": 0, "courses": 0}}

    rows = frappe.db.sql(
        """
        SELECT
            b.name AS batch_name,
            b.title AS batch_title,
            b.description AS batch_description,
            b.start_date AS batch_start_date,
            b.end_date AS batch_end_date,
            c.name AS course_name,
            c.title AS course_title
        FROM `tabBatch Course` bc
        INNER JOIN `tabLMS Batch` b
            ON b.name = bc.parent
            AND bc.parenttype = 'LMS Batch'
        INNER JOIN `tabLMS Course` c
            ON c.name = bc.course
        WHERE bc.evaluator = %(user)s
        ORDER BY b.modified DESC, c.modified DESC
        """,
        {"user": user},
        as_dict=True,
    )

    batches_by_name: Dict[str, Dict[str, Any]] = {}
    global_course_names: List[str] = []
    seen_global = set()

    for r in rows:
        bn = r["batch_name"]
        if bn not in batches_by_name:
            batches_by_name[bn] = {
                "name": bn,
                "title": r.get("batch_title") or bn,
                "description": r.get("batch_description"),
                "start_date": r.get("batch_start_date"),
                "end_date": r.get("batch_end_date"),
                "courses": [],
                "_course_set": set(),
            }

        course_name = r.get("course_name")
        course_title = r.get("course_title") or course_name
        if course_name:
            if course_name not in batches_by_name[bn]["_course_set"]:
                batches_by_name[bn]["_course_set"].add(course_name)
                batches_by_name[bn]["courses"].append({"name": course_name, "title": course_title})

            if course_name not in seen_global:
                seen_global.add(course_name)
                global_course_names.append(course_name)

    batches = []
    for b in batches_by_name.values():
        b.pop("_course_set", None)
        batches.append(b)

    # FULL counts (before preview slicing)
    total_batches = len(batches)
    total_courses = len(global_course_names)

    # PREVIEW slicing server-side (as you requested)
    batches_preview = batches[:4]
    course_names_preview = global_course_names[:8]

    # Build CourseCard-ready objects for the preview
    courses_preview = [_get_course_card_payload(n) for n in course_names_preview]

    return {
        "batches": batches_preview,
        "courses": courses_preview,
        "counts": {"batches": total_batches, "courses": total_courses},
    }
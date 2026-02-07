import frappe
import json

def on_quiz_submission_after_insert(doc, method=None):
    frappe.logger("quiz_progress").error(
        f"[QUIZ HOOK] fired | submission={doc.name} quiz={doc.quiz} member={doc.member}"
    )

    member = doc.member
    quiz = doc.quiz

    if not member or not quiz:
        return

    # Try to infer course from the quiz
    course = frappe.db.get_value("LMS Quiz", quiz, "course")

    # Fallback: scan all lessons (slower but safe)
    lesson = _find_lesson_for_quiz(course, quiz)

    frappe.logger("quiz_progress").error(
        f"[QUIZ HOOK] resolved lesson = {lesson}"
    )

    if not lesson:
        return

    _mark_lesson_complete(
        member=member,
        course=lesson["course"],
        lesson=lesson["name"],
    )


def _find_lesson_for_quiz(course, quiz):
    filters = {}
    if course:
        filters["course"] = course

    lessons = frappe.get_all(
        "Course Lesson",
        filters=filters,
        fields=["name", "course", "content"],
        limit_page_length=2000,
    )

    for l in lessons:
        if not l.content:
            continue
        try:
            data = json.loads(l.content)
        except Exception:
            continue

        for block in data.get("blocks", []):
            if block.get("type") == "quiz":
                d = block.get("data") or {}
                if (
                    d.get("quiz") == quiz
                    or d.get("quiz_id") == quiz
                    or d.get("id") == quiz
                ):
                    return {
                        "name": l.name,
                        "course": l.course,
                    }

    return None


def _mark_lesson_complete(member, course, lesson):
    exists = frappe.db.exists(
        "LMS Course Progress",
        {
            "member": member,
            "course": course,
            "lesson": lesson,
            "status": "Complete",
        },
    )

    if exists:
        return

    progress = frappe.new_doc("LMS Course Progress")
    progress.update(
        {
            "member": member,
            "course": course,
            "lesson": lesson,
            "status": "Complete",
        }
    )
    progress.insert(ignore_permissions=True)

    _update_enrollment_progress(member, course)


def _update_enrollment_progress(member, course):
    enrollment = frappe.db.get_value(
        "LMS Enrollment",
        {"member": member, "course": course},
        "name",
    )
    if not enrollment:
        return

    total = frappe.db.count("Course Lesson", {"course": course})
    if not total:
        return

    completed = frappe.db.count(
        "LMS Course Progress",
        {
            "member": member,
            "course": course,
            "status": "Complete",
        },
    )

    pct = int((completed / total) * 100)

    # ✅ progress is numeric, NOT "50%"
    frappe.db.set_value(
        "LMS Enrollment",
        enrollment,
        "progress",
        pct,
    )
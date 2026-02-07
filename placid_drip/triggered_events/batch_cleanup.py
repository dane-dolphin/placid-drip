import frappe

def on_batch_enrollment_removed(doc, method=None):
    """
    doc is an LMS Batch Enrollment row that is about to be deleted.
    Remove course enrollments for that member for courses in this batch,
    BUT ONLY if the member isn't in any other batch that includes that course.
    """
    member = doc.member
    batch = doc.batch

    # Get all courses linked to this batch
    batch_courses = frappe.get_all(
        "Batch Course",
        filters={"parent": batch},
        pluck="course",
    )

    if not batch_courses:
        return

    for course in batch_courses:
        # Is member enrolled in ANY OTHER batch that also has this course?
        still_has_course_elsewhere = frappe.db.exists(
            "LMS Batch Enrollment",
            {
                "member": member,
                "batch": ["!=", batch],
                # join condition via subquery-like check:
                # We'll check if that other batch has this course.
            },
        )

        # The above check alone isn't enough (it doesn't filter by course),
        # so do a proper query:
        if _member_has_course_in_other_batch(member, batch, course):
            continue

        # If no other batches keep them in this course, remove course enrollment.
        enrollment_name = frappe.db.get_value(
            "LMS Enrollment",
            {"member": member, "course": course},
            "name",
        )
        if enrollment_name:
            frappe.delete_doc("LMS Enrollment", enrollment_name, ignore_permissions=True, force=True)


def _member_has_course_in_other_batch(member: str, removed_batch: str, course: str) -> bool:
    """Return True if the member is enrolled in any other batch that includes this course."""
    BatchEnrollment = frappe.qb.DocType("LMS Batch Enrollment")
    BatchCourse = frappe.qb.DocType("Batch Course")

    # Join: other batch enrollments for member + courses attached to those batches
    res = (
        frappe.qb.from_(BatchEnrollment)
        .join(BatchCourse)
        .on(BatchCourse.parent == BatchEnrollment.batch)
        .select(BatchEnrollment.name)
        .where(BatchEnrollment.member == member)
        .where(BatchEnrollment.batch != removed_batch)
        .where(BatchCourse.course == course)
        .limit(1)
    ).run(as_dict=True)

    return bool(res)
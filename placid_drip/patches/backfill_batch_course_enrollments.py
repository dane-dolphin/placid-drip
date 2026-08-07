"""Backfill LMS Enrollment rows for students who were added to a batch while the
enrollment side-effect was broken.

Previously LMSBatchEnrollment created course enrollments inside `validate()` and
called `.save()` without `ignore_permissions`, so any student added by a user
without create rights on LMS Enrollment (notably the Batch Evaluator role) ended
up in the batch with no course enrollments. This reconciles the existing data.

Idempotent - re-running it enrolls nobody twice.
"""

from collections import defaultdict

import frappe

from lms.lms.doctype.lms_batch_enrollment.lms_batch_enrollment import (
	enroll_members_in_batch_courses,
)


def execute():
	enrollments = frappe.get_all(
		"LMS Batch Enrollment",
		fields=["batch", "member"],
		order_by="batch asc",
	)

	members_by_batch = defaultdict(list)
	for row in enrollments:
		if row.batch and row.member:
			members_by_batch[row.batch].append(row.member)

	total = 0
	affected_batches = 0

	for batch, members in members_by_batch.items():
		created = enroll_members_in_batch_courses(batch, members)
		created_count = sum(len(courses) for courses in created.values())
		if created_count:
			total += created_count
			affected_batches += 1
		# Long-running backfill: commit per batch so a timeout doesn't lose work.
		frappe.db.commit()  # nosemgrep

	print(
		f"backfill_batch_course_enrollments: created {total} course enrollment(s) "
		f"across {affected_batches} batch(es) from {len(enrollments)} batch enrollment(s)"
	)

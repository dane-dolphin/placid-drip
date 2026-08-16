"""Adding a course to a batch, with the evaluator resolved rather than picked.

The Add-a-course dialog used to insert the `Batch Course` row straight through
`frappe.client.insert` with whatever evaluator the user chose. For a facilitator
that question has only one right answer - they run the batch, so they evaluate
its courses - and getting it wrong is not cosmetic: `Batch Course.evaluator` is
one of the two things `facilitator.get_facilitated_batch_names` reads, so
leaving it blank or pointing it at somebody else silently changes who can see
the batch afterwards.

Going through a whitelisted endpoint instead also puts a scope check in front of
the insert. `Batch Evaluator` holds write on LMS Batch site-wide, so the generic
insert path let any facilitator add a course to any batch on the site.
"""

import frappe
from frappe import _

from placid_drip.api.permissions import require_batch_access
from placid_drip.facilitator import is_staff


@frappe.whitelist()
def add_batch_course(batch, course, evaluator=None):
	"""Attach `course` to `batch` and return the created row.

	`evaluator` is honoured for staff and ignored for everyone else - a
	facilitator is always recorded as the evaluator of a course they add, which is
	what the dialog now shows them instead of a picker.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Please log in."), frappe.PermissionError)

	if not batch or not course:
		frappe.throw(_("A batch and a course are required."))

	user = frappe.session.user
	require_batch_access(batch)

	if is_staff(user):
		evaluator = evaluator or None
	else:
		evaluator = ensure_course_evaluator(user)

	# Appended to the parent and saved through it, exactly as `frappe.client.insert`
	# does for a child row. Inserting the Batch Course on its own would skip
	# `LMS Batch.validate` - which is what rejects a duplicate course - and
	# `on_update`, which enrols the batch's existing students in the new course.
	parent = frappe.get_doc("LMS Batch", batch)
	row = parent.append("courses", {"course": course, "evaluator": evaluator})

	# The scope check above is stricter than the doctype permission would be: it is
	# bounded to batches this user actually runs, where the role is site-wide.
	parent.save(ignore_permissions=True)

	return row.as_dict()


def ensure_course_evaluator(user: str) -> str:
	"""The user's `Course Evaluator` record, created on first use.

	A facilitator is not guaranteed to have one - LMS only creates them when a
	moderator adds an evaluator in Settings or when someone opens their own
	availability page - and `Batch Course.evaluator` is a Link to that doctype, so
	assigning the caller without this would fail link validation.
	"""
	if frappe.db.exists("Course Evaluator", user):
		return user

	evaluator = frappe.new_doc("Course Evaluator")
	evaluator.evaluator = user
	evaluator.insert(ignore_permissions=True)

	return evaluator.name

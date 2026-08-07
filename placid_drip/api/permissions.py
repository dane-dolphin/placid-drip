import frappe

from placid_drip.facilitator import get_facilitated_batch_names


def is_system_staff():
	return (
		frappe.session.user == "Administrator"
		or frappe.has_role("System Manager")
		or frappe.has_role("Moderator")
	)


def require_batch_access(batch: str):
	"""
	- Staff: allowed
	- Facilitator: must evaluate a course in this batch, or be an instructor on it

	Previously this queried a doctype called "LMS Batch Evaluator", which does not
	exist anywhere in the bench - the call would have raised on a missing table for
	every non-staff user. Batch assignment actually lives on `Batch Course.evaluator`
	and `LMS Batch.instructors`.
	"""
	if is_system_staff():
		return

	if batch not in get_facilitated_batch_names(frappe.session.user):
		frappe.throw("Not permitted for this batch.", frappe.PermissionError)

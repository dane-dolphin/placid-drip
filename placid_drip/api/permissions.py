import frappe

from placid_drip.facilitator import get_facilitated_batch_names, is_staff


def is_system_staff():
	"""Delegates to `facilitator.is_staff` - same question, one answer.

	This used to call `frappe.has_role`, which does not exist in Frappe v15; the
	attribute lookup raised for every user except Administrator, who short-circuits
	on the check before it. Nothing called `require_batch_access` until now, so the
	crash sat here unnoticed rather than being caught by an existing caller.
	"""
	return is_staff(frappe.session.user)


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

import frappe

def is_system_staff():
	return frappe.has_role("System Manager") or frappe.has_role("Administrator") or frappe.has_role("Moderator")

def require_batch_access(batch: str):
	"""
	- Staff: allowed
	- Evaluator: must be assigned to this batch
	"""
	if is_system_staff():
		return

	user = frappe.session.user

	ok = frappe.db.exists("LMS Batch Evaluator", {"batch": batch, "evaluator": user})
	if not ok:
		frappe.throw("Not permitted for this batch.", frappe.PermissionError)

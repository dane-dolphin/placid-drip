import frappe

from placid_drip.facilitator import (
	BATCH_FIELDS,
	get_courses_for_batches,
	get_facilitated_batches,
)


def get_batch_details(batch_name: str):
	meta = frappe.get_meta("LMS Batch")
	fields = [f for f in BATCH_FIELDS if f == "name" or meta.has_field(f)]
	return frappe.get_value("LMS Batch", batch_name, fields, as_dict=True)


@frappe.whitelist()
def get_my_evaluator_batches(with_courses: bool = False):
	"""Batches the current user evaluates or instructs.

	Staff (Administrator / System Manager / Moderator) see every batch, as before.
	Everyone else sees the batches resolved by `placid_drip.facilitator`, which -
	unlike the previous version - also counts batches they are an instructor on,
	not only ones where they evaluate a course.
	"""
	user = frappe.session.user
	if user == "Guest":
		return []

	roles = frappe.get_roles(user)
	if user == "Administrator" or "System Manager" in roles or "Moderator" in roles:
		meta = frappe.get_meta("LMS Batch")
		fields = [f for f in BATCH_FIELDS if f == "name" or meta.has_field(f)]
		batches = frappe.get_all(
			"LMS Batch",
			fields=fields,
			order_by="modified desc",
			limit_page_length=200,
		)
	else:
		batches = get_facilitated_batches(user)

	if with_courses:
		courses_by_batch = get_courses_for_batches([b["name"] for b in batches])
		for batch in batches:
			batch["courses"] = courses_by_batch.get(batch["name"], [])

	return batches

"""Whitelisted surface for parishes: the picker on the batch form reads the list,
and the admin page adds, edits and removes them."""

import frappe
from frappe import _

from placid_drip import parishes

MAX_NAME_LENGTH = 140


@frappe.whitelist()
def get_parishes(with_counts: bool = False):
	"""Every parish, alphabetically. Open to any signed-in user - a facilitator
	needs the list to file their batch under one."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Please log in."), frappe.PermissionError)

	return parishes.list_parishes(with_counts=frappe.utils.sbool(with_counts))


@frappe.whitelist(methods=["POST"])
def save_parish(parish_name: str, name: str = "", description: str = "", image: str = "", cover_image: str = ""):
	"""Create a parish, or update the one called `name`. Returns the saved row.

	The name itself cannot be edited here: it is the record's id, and people and
	batches already point at it.
	"""
	parishes.assert_can_manage_parishes()

	parish_name = (parish_name or "").strip()
	if not parish_name:
		frappe.throw(_("Please enter the parish name."))
	if len(parish_name) > MAX_NAME_LENGTH:
		frappe.throw(_("The parish name is too long."))

	if name:
		doc = frappe.get_doc("Organization", name)
		if doc.org_type != parishes.PARISH:
			frappe.throw(_("{0} is not a parish.").format(name))
	else:
		if frappe.db.exists("Organization", parish_name):
			frappe.throw(_("A parish or diocese called {0} already exists.").format(parish_name))
		doc = frappe.new_doc("Organization")
		doc.organization_name = parish_name
		doc.org_type = parishes.PARISH

	doc.description = (description or "").strip()
	doc.image = image or None
	doc.cover_image = cover_image or None
	doc.save(ignore_permissions=True)

	return doc.as_dict()


@frappe.whitelist(methods=["POST"])
def delete_parish(name: str):
	"""Remove a parish that nothing points at any more."""
	parishes.assert_can_manage_parishes()

	if frappe.db.get_value("Organization", name, "org_type") != parishes.PARISH:
		frappe.throw(_("{0} is not a parish.").format(name))

	if parishes.batch_has_card_fields():
		batches = frappe.db.count("LMS Batch", {parishes.BATCH_PARISH_FIELD: name})
		if batches:
			frappe.throw(
				_("{0} batch(es) belong to this parish. Move them to another parish first.").format(batches)
			)

	if frappe.get_meta("User").has_field("organization"):
		people = frappe.db.count("User", {"organization": name})
		if people:
			frappe.throw(_("{0} people have this parish on their profile.").format(people))

	frappe.delete_doc("Organization", name, ignore_permissions=True)

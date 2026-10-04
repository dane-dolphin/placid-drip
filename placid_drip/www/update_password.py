from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import cint, now_datetime
from frappe.utils.data import sha256_hash

no_cache = 1


def get_context(context):
	context.no_breadcrumbs = True
	context.parents = [{"name": "me", "title": _("My Account")}]
	context.link_expired = is_reset_link_expired(frappe.form_dict.get("key"))


def is_reset_link_expired(key: str | None) -> bool:
	"""Same check frappe's update_password runs, done on page load instead.

	Without it a student only learns the link is dead after typing and confirming a
	new password. Every reset email overwrites the stored key, so a link from an
	older email can't be told apart from a used one - both are shown as expired.
	"""
	if not key:
		return False

	user = frappe.db.get_value(
		"User",
		{"reset_password_key": sha256_hash(key)},
		["name", "last_reset_password_key_generated_on"],
	)
	if not user:
		return True

	expiry = cint(frappe.db.get_single_value("System Settings", "reset_password_link_expiry_duration"))
	generated_on = user[1]
	return bool(expiry and generated_on and now_datetime() > generated_on + timedelta(seconds=expiry))

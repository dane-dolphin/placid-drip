"""Attach `User.organization` and `LMS Course.level` to the two new doctypes.

Custom Fields rather than edits to the `User` / `LMS Course` JSON, because both
doctypes belong to other apps - frappe and lms - and a field added to their JSON
would be reverted by the next upstream pull.

Created here rather than through the `fixtures` hook so the fields arrive on
`bench migrate` in a defined order (after the doctypes they link to exist) and so
they cannot be silently rewritten by a `bench export-fixtures` run in the lms app,
which exports every Custom Field on the site into lms's own fixture file.

`create_custom_fields` is idempotent - it updates in place on re-run - so this is
safe to leave in patches.txt permanently.
"""

import json

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

CUSTOM_FIELDS = {
	"User": [
		{
			"fieldname": "organization",
			"label": "Organization",
			"fieldtype": "Link",
			"options": "Organization",
			"insert_after": "location",
			# People belong to leaves (parishes), never to a container (diocese).
			# Desk-side guidance only - the server does not reject a group here, and
			# deliberately so: an admin may legitimately need to park a user one level
			# up while a parish record is still being set up.
			"link_filters": json.dumps([["Organization", "is_group", "=", 0]]),
			"description": "The parish this person belongs to. Not the same as College, which records where they studied.",
		}
	],
	"LMS Course": [
		{
			"fieldname": "level",
			"label": "Level",
			"fieldtype": "Link",
			"options": "Course Level",
			"insert_after": "category",
			"description": "Courses are grouped by level on the course page.",
		}
	],
}


def execute():
	# The link targets are created by the same migrate that runs this patch, but
	# model sync happens first for post_model_sync patches, so both exist by now.
	for doctype in ("Organization", "Course Level"):
		if not frappe.db.exists("DocType", doctype):
			frappe.throw(f"add_organization_and_level_fields: {doctype} missing, cannot create link field")

	create_custom_fields(CUSTOM_FIELDS)

	print("add_organization_and_level_fields: User.organization and LMS Course.level ready")

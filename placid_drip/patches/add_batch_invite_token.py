"""Attach `LMS Batch.invite_token`, the secret behind a batch's join link.

A Custom Field rather than an edit to the `LMS Batch` JSON, because the doctype
belongs to the lms app and a field added to its JSON would be reverted by the next
upstream pull. Created here rather than through the `fixtures` hook for the same
reasons as `add_organization_and_level_fields`.

Hidden in Desk: the token is a credential, and the LMS batch page is where it is
meant to be read (as a link and a QR code), reset, or switched off. `no_copy` so
that duplicating a batch does not hand the copy the original's open door.

`create_custom_fields` is idempotent, so this is safe to leave in patches.txt.
"""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

CUSTOM_FIELDS = {
	"LMS Batch": [
		{
			"fieldname": "invite_token",
			"label": "Join Link Token",
			"fieldtype": "Data",
			"length": 64,
			"insert_after": "allow_self_enrollment",
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			"search_index": 1,
			"description": "Secret behind the batch's join link. Managed from the batch page in the LMS, not here.",
		}
	],
}


def execute():
	create_custom_fields(CUSTOM_FIELDS)
	print("add_batch_invite_token: LMS Batch.invite_token ready")

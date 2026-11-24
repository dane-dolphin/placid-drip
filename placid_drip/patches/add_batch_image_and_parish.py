"""Give batches a picture and a parish.

`image` is what the batch's card shows; `parish` files the batch under one of the
parishes kept in `Organization` (see `placid_drip.parishes`). Both are Custom
Fields because LMS Batch belongs to the upstream app.
"""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

CUSTOM_FIELDS = {
	"LMS Batch": [
		{
			"fieldname": "image",
			"label": "Batch Image",
			"fieldtype": "Attach Image",
			"insert_after": "description",
			"description": "Shown on the batch's card. Falls back to the parish's cover picture.",
		},
		{
			"fieldname": "parish",
			"label": "Parish",
			"fieldtype": "Link",
			"options": "Organization",
			"insert_after": "image",
			"search_index": 1,
		},
	]
}


def execute():
	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)

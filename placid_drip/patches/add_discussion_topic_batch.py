"""Give lesson discussions a batch, and sort the existing ones into theirs.

Adds `Discussion Topic.batch` (see `placid_drip.discussions`) and backfills it
for topics that already exist: each goes to the batch its author is in for that
lesson's course. A topic whose author is in no such batch is left without one,
which makes it visible to staff and facilitators only - the alternative would be
guessing which batch should read it.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

CUSTOM_FIELDS = {
	"Discussion Topic": [
		{
			"fieldname": "batch",
			"label": "Batch",
			"fieldtype": "Link",
			"options": "LMS Batch",
			"insert_after": "reference_docname",
			"read_only": 1,
			"search_index": 1,
			"description": "Lesson discussions are shown only to this batch. Set automatically from the author's batch.",
		}
	]
}


def execute():
	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
	frappe.clear_cache(doctype="Discussion Topic")

	from placid_drip.discussions import batch_for_new_topic

	topics = frappe.get_all(
		"Discussion Topic",
		filters={"reference_doctype": "Course Lesson", "batch": ["is", "not set"]},
		fields=["name", "owner", "reference_docname"],
	)

	filled = 0
	for topic in topics:
		batch = batch_for_new_topic(topic.owner, topic.reference_docname)
		if batch:
			frappe.db.set_value("Discussion Topic", topic.name, "batch", batch, update_modified=False)
			filled += 1

	print(f"add_discussion_topic_batch: {filled} of {len(topics)} lesson topic(s) assigned to a batch")

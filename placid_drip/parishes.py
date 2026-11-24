"""Parishes, and the pictures a batch borrows from its parish.

A parish is an `Organization` whose `org_type` is "Parish" - the same record a
person's profile points at for "which parish do I belong to". A batch points at
one too (`LMS Batch.parish`, a Custom Field), which is what will let a teacher
see the other batches running in their own parish. Each parish carries a square
picture and a wide cover picture of the church; a batch with no image of its own
shows its parish's cover on its card.
"""

import frappe
from frappe import _

PARISH = "Parish"
PARISH_FIELDS = ["name", "organization_name", "description", "image", "cover_image", "parent_organization"]

#: Custom Fields on LMS Batch, added by `patches.add_batch_image_and_parish`.
BATCH_IMAGE_FIELD = "image"
BATCH_PARISH_FIELD = "parish"


def batch_has_card_fields() -> bool:
	meta = frappe.get_meta("LMS Batch")
	return meta.has_field(BATCH_IMAGE_FIELD) and meta.has_field(BATCH_PARISH_FIELD)


def list_parishes(with_counts: bool = False) -> list[dict]:
	parishes = frappe.get_all(
		"Organization",
		filters={"org_type": PARISH},
		fields=PARISH_FIELDS,
		order_by="organization_name asc",
	)

	if with_counts and parishes and batch_has_card_fields():
		rows = frappe.get_all(
			"LMS Batch",
			filters={BATCH_PARISH_FIELD: ["in", [p.name for p in parishes]]},
			fields=[BATCH_PARISH_FIELD, "count(name) as batches"],
			group_by=BATCH_PARISH_FIELD,
		)
		counts = {row[BATCH_PARISH_FIELD]: row["batches"] for row in rows}
		for parish in parishes:
			parish.batch_count = counts.get(parish.name, 0)

	return parishes


def attach_card_details(batches):
	"""Add what a batch card draws to each row: its image, parish and head-count.

	Upstream's batch lists are built from hardcoded field lists that know nothing
	about our Custom Fields, so they are fetched here in two queries for the whole
	page rather than by forking those functions.
	"""
	batches = [b for b in (batches or []) if b]
	if not batches or not batch_has_card_fields():
		return batches

	names = [b["name"] for b in batches]

	extras = {
		row.name: row
		for row in frappe.get_all(
			"LMS Batch",
			filters={"name": ["in", names]},
			fields=["name", BATCH_IMAGE_FIELD, BATCH_PARISH_FIELD],
		)
	}

	parish_names = {row.get(BATCH_PARISH_FIELD) for row in extras.values() if row.get(BATCH_PARISH_FIELD)}
	parishes = {}
	if parish_names:
		parishes = {
			row.name: row
			for row in frappe.get_all(
				"Organization",
				filters={"name": ["in", list(parish_names)]},
				fields=["name", "organization_name", "image", "cover_image"],
			)
		}

	counts = {
		row["batch"]: row["students"]
		for row in frappe.get_all(
			"LMS Batch Enrollment",
			filters={"batch": ["in", names]},
			fields=["batch", "count(name) as students"],
			group_by="batch",
		)
	}

	for batch in batches:
		extra = extras.get(batch["name"]) or {}
		parish = parishes.get(extra.get(BATCH_PARISH_FIELD)) or {}

		batch["image"] = extra.get(BATCH_IMAGE_FIELD)
		batch["parish"] = parish.get("name")
		batch["parish_name"] = parish.get("organization_name")
		batch["parish_image"] = parish.get("image")
		batch["parish_cover"] = parish.get("cover_image")
		batch["students_count"] = counts.get(batch["name"], 0)

	return batches


def assert_can_manage_parishes() -> None:
	from placid_drip.facilitator import is_staff

	if not is_staff(frappe.session.user):
		frappe.throw(_("Only administrators can manage parishes."), frappe.PermissionError)

"""Attaching a person's Organization to payloads that upstream builds without it.

`get_profile_details` and `get_batch_student_details` both read User through a
hardcoded field list, so a Custom Field like `organization` never appears no
matter how it is defined. Rather than forking either function - both do other
work that would then drift from upstream - the overrides call back here to fill
the column in afterwards, in one grouped query per response.

Every entry point tolerates the field not existing yet, so a site that has pulled
the code but not run `bench migrate` degrades to a blank column instead of a 500.
"""

import frappe

ORG_FIELD = "organization"


def has_organization_field() -> bool:
	return frappe.get_meta("User").has_field(ORG_FIELD)


def get_organizations(users) -> dict:
	"""Map of user id -> organization, skipping users who have none set."""
	users = [u for u in set(users or []) if u]
	if not users or not has_organization_field():
		return {}

	rows = frappe.get_all(
		"User",
		filters={"name": ["in", users]},
		fields=["name", ORG_FIELD],
	)

	return {row["name"]: row.get(ORG_FIELD) for row in rows if row.get(ORG_FIELD)}


def attach_organization(rows, user_key="name"):
	"""Set `organization` on every row, resolved via `row[user_key]`.

	`user_key` is not always "name": a batch student row reuses `name` for its
	LMS Batch Enrollment id and carries the actual user in `email`, so passing the
	wrong key here silently yields an all-blank column rather than an error.
	"""
	if not rows:
		return rows

	organizations = get_organizations([row.get(user_key) for row in rows])

	for row in rows:
		row[ORG_FIELD] = organizations.get(row.get(user_key))

	return rows

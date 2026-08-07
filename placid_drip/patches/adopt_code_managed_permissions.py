"""Hand permission management back to the DocType JSON files.

Frappe ignores a DocType's JSON permissions entirely as soon as a single
`Custom DocPerm` row exists for it (see frappe/permissions.py::get_valid_perms -
rows from DocPerm are dropped for any doctype present in
get_doctypes_with_custom_docperms()). These doctypes had been edited through the
Role Permissions Manager UI, so their JSON was dead weight.

The JSON files now encode the exact matrix that was live in production plus the
intended changes, so deleting the Custom DocPerm rows makes code authoritative
without changing effective access - except where deliberately intended.

Before deleting anything this snapshots the existing rows to
`sites/<site>/private/backups/custom_docperm_snapshot_<timestamp>.json`, so the
previous state can be restored if something was mis-encoded.
"""

import frappe
from frappe.permissions import reset_perms

from placid_drip.permissions_backup import dump

DOCTYPES = [
	"LMS Course",
	"LMS Quiz",
	"Course Lesson",
	"Batch Lesson Access",
	"LMS Enrollment",
	"LMS Batch Enrollment",
]


def execute():
	# Snapshot EVERY Custom DocPerm row, not only the ones about to be deleted -
	# a complete artefact is what makes this reversible.
	# Restore with: placid_drip.permissions_backup.restore
	dump()

	for doctype in DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			# Batch Lesson Access only exists once placid_drip is installed.
			continue

		had = frappe.db.count("Custom DocPerm", {"parent": doctype})
		if not had:
			continue

		# Deletes the Custom DocPerm rows; the standard DocPerm rows written from
		# the DocType JSON during this migrate's model sync then take over.
		reset_perms(doctype)
		print(f"  {doctype}: removed {had} custom row(s), now code-managed")

	frappe.clear_cache()

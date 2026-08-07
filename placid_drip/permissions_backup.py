"""Dump and restore `Custom DocPerm` rows - the UI-managed permission overrides.

Frappe discards a DocType's JSON permissions entirely once any Custom DocPerm row
exists for it, so these rows silently outrank everything in code. This module lets
you snapshot them to a file and put them back.

Run from the bench directory:

    # snapshot everything (do this BEFORE any migrate that touches permissions)
    bench --site placid.local execute placid_drip.permissions_backup.dump

    # human-readable view of a snapshot
    bench --site placid.local execute placid_drip.permissions_backup.show \\
        --kwargs '{"path": "/path/to/custom_docperm_<ts>.json"}'

    # put them back (adds only what is missing)
    bench --site placid.local execute placid_drip.permissions_backup.restore \\
        --kwargs '{"path": "/path/to/custom_docperm_<ts>.json"}'

    # put them back, wiping current rows for those doctypes first
    bench --site placid.local execute placid_drip.permissions_backup.restore \\
        --kwargs '{"path": "...", "replace": true}'

    # restore only some doctypes
    bench --site placid.local execute placid_drip.permissions_backup.restore \\
        --kwargs '{"path": "...", "doctypes": ["LMS Course", "LMS Quiz"]}'

Restoring re-establishes UI control over those doctypes, which means their JSON
permissions go back to being ignored. That is the point - it is the escape hatch
if code-managed permissions turn out wrong.
"""

import json
import os

import frappe

#: Every permission-bearing field on Custom DocPerm. `parent` is the DocType name.
PERM_FIELDS = [
	"parent",
	"role",
	"permlevel",
	"if_owner",
	"read",
	"write",
	"create",
	"delete",
	"submit",
	"cancel",
	"amend",
	"report",
	"export",
	"import",
	"share",
	"print",
	"email",
	"select",
]


def dump(path: str | None = None) -> str:
	"""Write every Custom DocPerm row to a JSON file. Returns the path."""
	rows = frappe.get_all("Custom DocPerm", fields=PERM_FIELDS, order_by="parent asc, role asc")

	payload = {
		"site": frappe.local.site,
		"captured_at": frappe.utils.now(),
		"row_count": len(rows),
		"complete": True,
		"rows": rows,
	}

	path = path or _default_path()
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "w", encoding="utf-8") as f:
		json.dump(payload, f, indent=2, ensure_ascii=False, default=str)

	doctypes = sorted({r["parent"] for r in rows})
	print(f"wrote {len(rows)} Custom DocPerm row(s) across {len(doctypes)} doctype(s) -> {path}")
	for dt in doctypes:
		roles = sorted(r["role"] for r in rows if r["parent"] == dt)
		print(f"  {dt}: {', '.join(roles)}")

	return path


def show(path: str | None = None) -> None:
	"""Print a snapshot (or the live rows if no path) as a readable table."""
	if path:
		rows = _read(path)["rows"]
	else:
		rows = frappe.get_all("Custom DocPerm", fields=PERM_FIELDS, order_by="parent asc, role asc")

	flags = ["create", "read", "write", "delete", "submit", "report", "export", "share", "if_owner"]
	print(f"{'DOCTYPE':32s} {'ROLE':20s} " + " ".join(f[:4].rjust(4) for f in flags))
	for r in rows:
		vals = " ".join(str(int(r.get(f) or 0)).rjust(4) for f in flags)
		print(f"{str(r.get('parent')):32s} {str(r.get('role')):20s} {vals}")
	print(f"\n{len(rows)} row(s)")


def restore(path: str, doctypes: list[str] | None = None, replace: bool = False) -> int:
	"""Recreate Custom DocPerm rows from a snapshot. Returns rows inserted."""
	payload = _read(path)
	rows = payload["rows"]

	if not payload.get("complete", False):
		print(
			"WARNING: this snapshot is marked incomplete - it does not carry every "
			"permission field. Review it before relying on the result."
		)

	if doctypes:
		wanted = set(doctypes)
		rows = [r for r in rows if r.get("parent") in wanted]

	targets = sorted({r["parent"] for r in rows})
	if not targets:
		print("nothing to restore")
		return 0

	if replace:
		for dt in targets:
			removed = frappe.db.count("Custom DocPerm", {"parent": dt})
			frappe.db.delete("Custom DocPerm", {"parent": dt})
			print(f"  {dt}: cleared {removed} existing row(s)")

	inserted = 0
	for r in rows:
		dt, role = r.get("parent"), r.get("role")
		if not dt or not role:
			continue
		if not frappe.db.exists("DocType", dt):
			print(f"  skip {dt}: doctype not installed")
			continue

		permlevel = frappe.utils.cint(r.get("permlevel"))
		if frappe.db.exists("Custom DocPerm", {"parent": dt, "role": role, "permlevel": permlevel}):
			continue

		doc = frappe.new_doc("Custom DocPerm")
		for field in PERM_FIELDS:
			doc.set(field, r.get(field))
		doc.insert(ignore_permissions=True)
		inserted += 1

	frappe.db.commit()  # nosemgrep
	frappe.clear_cache()

	print(f"restored {inserted} row(s) across {len(targets)} doctype(s)")
	print("note: these doctypes are now UI-managed again - their JSON permissions are ignored")
	return inserted


def _default_path() -> str:
	stamp = frappe.utils.now().replace(" ", "_").replace(":", "-").split(".")[0]
	return frappe.get_site_path("private", "backups", f"custom_docperm_{stamp}.json")


def _read(path: str) -> dict:
	with open(path, encoding="utf-8") as f:
		payload = json.load(f)
	if isinstance(payload, list):  # tolerate a bare array
		payload = {"rows": payload, "complete": False}
	return payload

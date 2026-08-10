"""Whitelisted surface for the Students page and the invite modal.

Every endpoint here is scoped the same way: staff see the whole site, a
facilitator sees only batches they evaluate or instruct. The scoping lives in
`placid_drip.invites` so the list view and the write path cannot drift apart and
start disagreeing about which batches belong to whom.
"""

import frappe
from frappe import _

from placid_drip import invites
from placid_drip.facilitator import get_facilitated_batches, is_staff

INVITE_FIELDS = ["name", "email", "status", "invited_by", "accepted_user", "accepted_on", "creation"]


def _assert_signed_in():
	if frappe.session.user == "Guest":
		frappe.throw(_("Please log in."), frappe.PermissionError)


@frappe.whitelist()
def get_invitable_batches():
	"""Batches the current user may invite into - the modal's batch picker."""
	_assert_signed_in()
	user = frappe.session.user

	if is_staff(user):
		return frappe.get_all(
			"LMS Batch",
			fields=["name", "title"],
			order_by="start_date desc",
		)

	return [{"name": b["name"], "title": b.get("title") or b["name"]} for b in get_facilitated_batches(user)]


@frappe.whitelist()
def send_invites(emails, batches):
	"""Invite a pasted list of addresses into one or more batches.

	`emails` may be a blob of comma / semicolon / newline / space separated
	addresses, or a list. Returns a per-address breakdown rather than a bare
	count, because "37 invited" hides the three typos that silently did nothing.
	"""
	_assert_signed_in()

	batches = frappe.parse_json(batches) if isinstance(batches, str) else batches
	if isinstance(batches, str):
		batches = [batches]

	return invites.send_invites(emails, batches or [])


@frappe.whitelist()
def get_invites(status=None, batch=None):
	"""Invites the current user is allowed to see, newest first."""
	_assert_signed_in()
	user = frappe.session.user

	allowed = invites.get_invitable_batches(user)
	if allowed is not None and not allowed:
		return []

	names = _invite_names_for_batches(allowed, batch)
	if names is not None and not names:
		return []

	filters = {}
	if status:
		filters["status"] = status
	if names is not None:
		filters["name"] = ["in", names]

	rows = frappe.get_all(
		"Student Invite",
		filters=filters,
		fields=INVITE_FIELDS,
		order_by="creation desc",
		limit_page_length=200,
	)

	_attach_batches(rows)
	_attach_links(rows)

	return rows


def _invite_names_for_batches(allowed, batch):
	"""Invite names visible given the user's batch scope and any batch filter.

	Returns None when no restriction applies at all, so the caller can skip the
	`name in (...)` clause entirely rather than building one over every invite.
	"""
	if allowed is None and not batch:
		return None

	scope = list(allowed) if allowed is not None else None

	if batch:
		if scope is not None and batch not in scope:
			frappe.throw(_("Not permitted"), frappe.PermissionError)
		scope = [batch]

	return frappe.get_all(
		"Student Invite Batch",
		filters={"parenttype": "Student Invite", "batch": ["in", scope]},
		pluck="parent",
		distinct=True,
	)


def _attach_batches(rows):
	if not rows:
		return

	batch_rows = frappe.get_all(
		"Student Invite Batch",
		filters={"parenttype": "Student Invite", "parent": ["in", [r["name"] for r in rows]]},
		fields=["parent", "batch", "batch_title", "idx"],
		order_by="parent asc, idx asc",
	)

	by_invite = {}
	for row in batch_rows:
		by_invite.setdefault(row["parent"], []).append(
			{"name": row["batch"], "title": row.get("batch_title") or row["batch"]}
		)

	for row in rows:
		row["batches"] = by_invite.get(row["name"], [])


def _attach_links(rows):
	"""Expose the invite link only for invites that can still be accepted.

	The key is fetched here rather than in `INVITE_FIELDS` so it never rides along
	in a payload for an already-accepted or cancelled invite, where the link is
	dead weight and still a credential.
	"""
	pending = [r["name"] for r in rows if r["status"] == "Pending"]
	keys = {}

	if pending:
		keys = {
			r["name"]: r["invite_key"]
			for r in frappe.get_all(
				"Student Invite",
				filters={"name": ["in", pending]},
				fields=["name", "invite_key"],
			)
		}

	for row in rows:
		key = keys.get(row["name"])
		row["invite_url"] = invites.get_invite_url(key) if key else None


def _get_scoped_invite(name):
	invite = frappe.get_doc("Student Invite", name)
	allowed = invites.get_invitable_batches(frappe.session.user)

	if allowed is not None and not set(invite.batch_names()) & set(allowed):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	return invite


@frappe.whitelist()
def revoke_invite(name):
	"""Cancel a pending invite so registering with that address enrols nothing."""
	_assert_signed_in()
	invite = _get_scoped_invite(name)

	if invite.status != "Pending":
		frappe.throw(_("Only a pending invite can be cancelled."))

	invite.status = "Cancelled"
	invite.save(ignore_permissions=True)

	return {"status": invite.status}


@frappe.whitelist()
def resend_invite(name):
	"""Re-send whichever email can actually get this person in.

	Once the account exists - which is now the normal case, since invites
	provision it up front - the invite link is useless to someone who has no
	password and cannot self-register one. The password-setup email is the one
	that helps, so that is what gets resent.
	"""
	_assert_signed_in()
	invite = _get_scoped_invite(name)

	if invite.status == "Cancelled":
		frappe.throw(_("This invite was cancelled."))

	user = invite.accepted_user or frappe.db.exists("User", {"email": invite.email})
	if user:
		return {"sent": invites.resend_account_setup(user), "kind": "password"}

	return {"sent": invites.send_invite_email(invite), "kind": "invite"}

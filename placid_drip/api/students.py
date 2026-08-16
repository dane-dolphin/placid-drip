"""The roster behind the Students page.

A facilitator's "my students" is the union of two things that are tracked
separately: people enrolled in a batch they run, and people they personally
invited. Neither alone is the answer - an invite that has been accepted becomes
a batch enrolment and would be double counted, while an invite into a batch
somebody else runs would otherwise vanish from the inviter's own list. So both
sources are collected and merged on the user's email.

Staff see every batch, matching `get_invitable_batches`, so the page does not
quietly become facilitator-only for an admin who also runs a batch.
"""

import frappe
from frappe import _

from placid_drip import membership
from placid_drip.facilitator import get_facilitated_batch_names, is_staff


@frappe.whitelist()
def get_my_students():
	"""One row per person, with every batch of theirs the caller can see.

	`batches` is a list rather than a joined string so the frontend can sort and
	filter on it without having to parse a display value apart again.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Please log in."), frappe.PermissionError)

	user = frappe.session.user
	batch_names = None if is_staff(user) else get_facilitated_batch_names(user)

	rows = {}
	_add_batch_members(rows, batch_names)
	_add_invitees(rows, user)

	students = sorted(rows.values(), key=lambda r: (r["full_name"] or r["email"] or "").lower())

	_attach_names(students)
	# Keyed on `user`, not `email`: rows are merged on a lowercased address, which
	# is not guaranteed to be the User id, and a not-yet-redeemed invite has no
	# User at all.
	membership.attach_organization(students, user_key="user")

	return students


def _blank(email):
	return {"email": email, "full_name": "", "user": None, "batches": [], "invited": False}


def _add_batch_members(rows, batch_names):
	"""Everyone enrolled in a batch the caller runs.

	`batch_names is None` means staff, i.e. no batch restriction at all; an empty
	list means a facilitator who runs nothing yet, which is a different thing and
	must not be allowed to fall through to "every batch on the site".
	"""
	filters = {}
	if batch_names is not None:
		if not batch_names:
			return
		filters["batch"] = ["in", batch_names]

	enrollments = frappe.get_all(
		"LMS Batch Enrollment",
		filters=filters,
		fields=["member", "batch"],
		limit_page_length=0,
	)
	if not enrollments:
		return

	titles = _batch_titles({e["batch"] for e in enrollments})
	emails = _user_emails({e["member"] for e in enrollments})

	for enrollment in enrollments:
		email = emails.get(enrollment["member"])
		if not email:
			# The enrolment outlived the User record. Skipped rather than shown as
			# a nameless row, which would be a roster entry nobody can act on.
			continue

		row = rows.setdefault(email, _blank(email))
		row["user"] = enrollment["member"]
		_add_batch(row, enrollment["batch"], titles.get(enrollment["batch"]))


def _add_invitees(rows, user):
	"""People this user invited, including invites that have not landed yet.

	Scoped to `invited_by` rather than to the caller's batches: an invite is the
	inviter's own action, and it stays on their list even if the batch it pointed
	at is now run by somebody else.
	"""
	invites = frappe.get_all(
		"Student Invite",
		filters={"invited_by": user, "status": ["!=", "Cancelled"]},
		fields=["name", "email", "accepted_user"],
		limit_page_length=0,
	)
	if not invites:
		return

	by_name = {}
	for invite in invites:
		email = (invite.get("email") or "").strip().lower()
		if not email:
			continue

		row = rows.setdefault(email, _blank(email))
		row["invited"] = True
		if invite.get("accepted_user"):
			row["user"] = invite["accepted_user"]
		by_name[invite["name"]] = row

	_add_invite_batches(by_name)


def _add_invite_batches(rows_by_invite):
	if not rows_by_invite:
		return

	batch_rows = frappe.get_all(
		"Student Invite Batch",
		filters={"parenttype": "Student Invite", "parent": ["in", list(rows_by_invite)]},
		fields=["parent", "batch", "batch_title"],
		limit_page_length=0,
	)

	for batch_row in batch_rows:
		row = rows_by_invite.get(batch_row["parent"])
		if row:
			_add_batch(row, batch_row["batch"], batch_row.get("batch_title"))


def _add_batch(row, name, title):
	if not name:
		return

	if any(b["name"] == name for b in row["batches"]):
		return

	row["batches"].append({"name": name, "title": title or name})


def _batch_titles(names):
	names = [n for n in names if n]
	if not names:
		return {}

	return dict(
		frappe.get_all(
			"LMS Batch",
			filters={"name": ["in", names]},
			fields=["name", "title"],
			as_list=True,
		)
	)


def _user_emails(user_ids):
	user_ids = [u for u in user_ids if u]
	if not user_ids:
		return {}

	rows = frappe.get_all(
		"User",
		filters={"name": ["in", user_ids]},
		fields=["name", "email"],
	)

	return {r["name"]: (r["email"] or r["name"]).strip().lower() for r in rows}


def _attach_names(students):
	"""Fill `full_name` for everyone who has an account.

	Rows without one are invites that have not been redeemed yet; they keep an
	empty name rather than borrowing the email, so the frontend can decide how to
	present a person who has not signed in.
	"""
	user_ids = [s["user"] for s in students if s.get("user")]
	if not user_ids:
		return

	names = dict(
		frappe.get_all(
			"User",
			filters={"name": ["in", user_ids]},
			fields=["name", "full_name"],
			as_list=True,
		)
	)

	for student in students:
		student["full_name"] = names.get(student.get("user")) or ""

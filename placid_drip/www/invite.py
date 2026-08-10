"""Landing page for an invite link.

Handles the two ways someone arrives here. Already logged in - which happens
whenever an existing member is re-invited, or the person signs up first and
clicks the link afterwards - and the invite is applied on the spot. Not logged
in, and the page names what they have been invited to and sends them to log in
or sign up; the enrolment then lands via `User.after_insert` regardless of which
route they take, so nothing depends on them returning to this URL.
"""

import frappe
from frappe import _

from placid_drip import invites

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = False

	key = (frappe.form_dict.get("key") or "").strip()
	context.invite_valid = False
	context.accepted = False
	context.batches = []

	if not key:
		context.message = _("This invite link is missing its key.")
		return context

	invite = _get_invite(key)
	if not invite:
		# Same message for "no such key" and "already used" - distinguishing them
		# tells an unauthenticated visitor which keys exist.
		context.message = _("This invite link is not valid, or has already been used.")
		return context

	context.invite_valid = True
	context.email = invite.email
	context.batches = _batch_titles(invite)
	context.login_url = f"/login?redirect-to=/invite?key={key}"

	if frappe.session.user != "Guest":
		_accept_now(invite, context)

	return context


def _get_invite(key: str):
	name = frappe.db.exists("Student Invite", {"invite_key": key, "status": "Pending"})
	return frappe.get_doc("Student Invite", name) if name else None


def _batch_titles(invite) -> list[str]:
	return [
		frappe.db.get_value("LMS Batch", row.batch, "title") or row.batch for row in invite.batches
	]


def _accept_now(invite, context):
	"""Apply the invite to the signed-in user.

	Only when the addresses match. A logged-in member opening somebody else's
	invite link must not be enrolled in their place, and must not consume the
	invite either - so the invite is left Pending for its actual recipient.
	"""
	user = frappe.session.user
	user_email = (frappe.db.get_value("User", user, "email") or user).strip().lower()

	if user_email != invite.email:
		context.message = _(
			"This invite was sent to {0}, but you are signed in as {1}. "
			"Sign out and sign up with the invited address to accept it."
		).format(invite.email, user_email)
		return

	invites.enroll_in_batches(user, invite.batch_names())

	invite.status = "Accepted"
	invite.accepted_user = user
	invite.accepted_on = frappe.utils.now_datetime()
	invite.save(ignore_permissions=True)

	context.accepted = True

"""Landing page for an invite link.

Works out which of five screens the visitor needs and leaves the rendering to
the template. A guest with no account gets the registration form; a guest who
already has one is sent to log in and come back; a signed-in invitee picks the
batches to join; a signed-in stranger is told whose link this is; and anything
unknown or cancelled gets a dead-end message that reveals nothing about which
keys exist. The actual writes happen in `placid_drip.api.invite_landing`.
"""

from urllib.parse import quote

import frappe
import frappe.sessions
from frappe import _

from placid_drip import invites

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = False
	context.no_breadcrumbs = True

	key = (frappe.form_dict.get("key") or "").strip()
	context.key = key
	context.mode = "unavailable"
	context.batches = []
	context.message = None

	invite = invites.get_invite_by_key(key) if key else None

	if not invite or invite.status == "Cancelled":
		context.message = (
			_("This invite link is not valid, or has been cancelled.")
			if key
			else _("This invite link is missing its key.")
		)
		return context

	context.email = invite.email
	context.batches = [
		{"name": row.batch, "title": title}
		for row, title in zip(invite.batches, invites.batch_titles(invite))
	]
	context.login_url = "/login?redirect-to=" + quote(f"/invite?key={key}", safe="")

	user = frappe.session.user

	if user == "Guest":
		if invite.status == "Accepted":
			context.mode = "login"
			context.message = _("This invitation has already been accepted. Log in to continue.")
		elif invites.user_for_email(invite.email):
			context.mode = "login"
			context.message = _("You already have an account with this address. Log in to accept the invitation.")
		else:
			context.mode = "register"
		return context

	# A session that has only ever rendered website pages may not have a CSRF
	# token yet, in which case the page would print "None" and the accept POST
	# would break the moment another tab (the LMS app, say) minted one. Mint it
	# here so the page always carries the real token.
	frappe.sessions.get_csrf_token()

	if not invites.is_invitee(invite, user):
		context.mode = "mismatch"
		context.user_email = (frappe.db.get_value("User", user, "email") or user).strip().lower()
		return context

	context.first_name = frappe.db.get_value("User", user, "first_name") or ""
	context.mode = "accepted" if invite.status == "Accepted" else "accept"
	return context

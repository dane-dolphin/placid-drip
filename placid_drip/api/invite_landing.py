"""The student's side of an invite link: create the account, then join batches.

Both endpoints are keyed on the invite's secret rather than on anything the
caller says about themselves. `register` is open to guests because a brand-new
student is by definition not logged in, and the key is what authorises creating
an account on a site where self-signup is otherwise switched off. `accept`
requires a session, and then insists the session belongs to the invited address
- a forwarded link must not enrol the wrong person.
"""

import frappe
from frappe import _

from placid_drip import invites
from placid_drip.rate_limits import check_ip_rate_limits


def _pending_invite(key: str):
	invite = invites.get_invite_by_key(key)
	if not invite or invite.status != "Pending":
		# Same message for "no such key" and "already used" - distinguishing them
		# tells an unauthenticated visitor which keys exist.
		frappe.throw(
			_("This invite link is not valid, or has already been used."),
			frappe.DoesNotExistError,
		)
	return invite


@frappe.whitelist(allow_guest=True, methods=["POST"])
def register(key: str, first_name: str, last_name: str = "", password: str = ""):
	"""Create the invited student's account and sign them in.

	Returns where to send the browser next: back to the invite page, which now
	shows the batches to join. Refuses when a session already exists, because
	silently replacing it with the new account would surprise whoever is logged
	in - the page tells them to sign out first instead.
	"""
	check_ip_rate_limits("invite_register")

	if frappe.session.user != "Guest":
		frappe.throw(
			_("You are already signed in. Sign out first to create a new account."),
			frappe.PermissionError,
		)

	user = invites.register(key, first_name, last_name, password)
	frappe.local.login_manager.login_as(user.name)

	return {"redirect_to": f"/invite?key={key}"}


@frappe.whitelist(methods=["POST"])
def accept(key: str, batches=None):
	"""Join the chosen batches off a pending invite.

	`batches` is a JSON list of batch names from the invite; omitted means all of
	them. Returns the titles joined, so the page can confirm them by name.
	"""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please log in."), frappe.PermissionError)

	invite = _pending_invite(key)

	if not invites.is_invitee(invite, user):
		frappe.throw(
			_("This invite was sent to {0}. Sign out and continue with that account.").format(invite.email),
			frappe.PermissionError,
		)

	if isinstance(batches, str):
		batches = frappe.parse_json(batches)
	if isinstance(batches, str):
		batches = [batches]

	invites.accept(invite, user, batches)

	return {"batches": invites.batch_titles(invite), "redirect_to": "/lms/batches"}

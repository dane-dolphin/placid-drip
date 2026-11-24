"""Whitelisted surface for a batch's join link.

Two audiences. The facilitator's modal reads, resets and switches off the link,
and every one of those checks that the caller may invite into that batch. The
join page itself redeems the link: `join` for someone signed in, and
`join_with_email` for everyone else, which is open to guests because a brand-new
student is by definition not logged in - the token is their authorisation.
"""

from urllib.parse import quote

import frappe
from frappe import _

from placid_drip import batch_links
from placid_drip.rate_limits import check_ip_rate_limits


def _assert_signed_in():
	if frappe.session.user == "Guest":
		frappe.throw(_("Please log in."), frappe.PermissionError)


def _login_then(path: str) -> str:
	return "/login?redirect-to=" + quote(path, safe="")


# ---------------------------------------------------------------------------
# Facilitator side
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_link(batch: str):
	"""The batch's join link and QR code, minting the link on first use."""
	_assert_signed_in()
	batch_links.assert_can_share(batch, frappe.session.user)

	batch_links.ensure_token(batch)
	return batch_links.link_payload(batch)


@frappe.whitelist(methods=["POST"])
def reset_link(batch: str):
	"""Issue a fresh link; whatever was shared before stops working."""
	_assert_signed_in()
	batch_links.assert_can_share(batch, frappe.session.user)

	batch_links.reset_token(batch)
	return batch_links.link_payload(batch)


@frappe.whitelist(methods=["POST"])
def disable_link(batch: str):
	"""Switch the link off. `get_link` will mint a new one when next asked."""
	_assert_signed_in()
	batch_links.assert_can_share(batch, frappe.session.user)

	batch_links.clear_token(batch)
	return batch_links.link_payload(batch)


# ---------------------------------------------------------------------------
# Student side
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def join(token: str):
	"""Enrol the signed-in user in the batch behind the link."""
	_assert_signed_in()

	result = batch_links.join(token, frappe.session.user)
	result["redirect_to"] = batch_links.landing_path(result["batch"])
	return result


@frappe.whitelist(allow_guest=True, methods=["POST"])
def join_with_email(token: str, email: str, first_name: str, last_name: str = "", password: str = ""):
	"""Join by name and email: enrol an existing account, or create one and enrol it.

	A new account is signed in straight away - whoever is at the keyboard just
	chose its password. An existing account is enrolled but NOT signed in, since
	typing someone's address proves nothing about who is typing; the response
	sends them through the login page and on to their course.

	Refuses when a session already exists: the page shows a one-click Join for
	signed-in visitors instead. Rate limited per IP because it creates accounts,
	and answers whether an address is registered, for anyone holding the link.
	"""
	check_ip_rate_limits("batch_join_register")

	if frappe.session.user != "Guest":
		frappe.throw(
			_("You are already signed in. Sign out first to join with a different email."),
			frappe.PermissionError,
		)

	result = batch_links.join_with_email(token, email, first_name, last_name, password)

	if result["status"] == "password_required":
		return result

	landing = batch_links.landing_path(result["batch"])

	if result["status"] == "created":
		frappe.local.login_manager.login_as(result.pop("user"))
		result["redirect_to"] = landing
	else:
		result["redirect_to"] = _login_then(landing)

	return result

"""Whitelisted surface for a batch's join link.

Two audiences. The facilitator's modal reads, resets and switches off the link,
and every one of those checks that the caller may invite into that batch. The
join page itself redeems the link: `join` for someone signed in, and
`register_and_join` for a newcomer, which is open to guests because a brand-new
student is by definition not logged in - the token is their authorisation.
"""

import frappe
from frappe import _

from placid_drip import batch_links
from placid_drip.rate_limits import check_ip_rate_limits


def _assert_signed_in():
	if frappe.session.user == "Guest":
		frappe.throw(_("Please log in."), frappe.PermissionError)


def _batch_page(batch: str) -> str:
	return f"/lms/batches/{batch}"


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
	result["redirect_to"] = _batch_page(result["batch"])
	return result


@frappe.whitelist(allow_guest=True, methods=["POST"])
def register_and_join(token: str, email: str, first_name: str, last_name: str = "", password: str = ""):
	"""Create a newcomer's account, enrol it, and sign them in.

	Refuses when a session already exists: silently replacing it with the new
	account would surprise whoever is logged in, so the page offers sign-out
	instead. Rate limited per IP because it creates accounts for anyone.
	"""
	check_ip_rate_limits("batch_join_register")

	if frappe.session.user != "Guest":
		frappe.throw(
			_("You are already signed in. Sign out first to create a new account."),
			frappe.PermissionError,
		)

	result = batch_links.register_and_join(token, email, first_name, last_name, password)

	frappe.local.login_manager.login_as(result.pop("user"))

	result["redirect_to"] = _batch_page(result["batch"])
	return result

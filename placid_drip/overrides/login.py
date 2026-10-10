"""Overrides for `frappe.www.login` whitelisted methods (login with email link).

Email links are replaced by login codes (`placid_drip.login_code`): no new links
are sent, but links already in inboxes keep working until they expire.
"""

import inspect

import frappe
from frappe import _
from frappe.www import login as frappe_login

from placid_drip.rate_limits import check_ip_rate_limits

# Unwrapped past frappe's type-check and rate_limit decorators so its System
# Settings limit doesn't stack on top of ours. Our own @whitelist type-checks.
_upstream_login_via_key = inspect.unwrap(frappe_login.login_via_key)


@frappe.whitelist(allow_guest=True)
def send_login_link(email: str):
	frappe.throw(
		_("Login links have been replaced by login codes. Please use \"Login with Email Code\"."),
		frappe.PermissionError,
	)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def login_via_key(key: str):
	check_ip_rate_limits("login_via_key")
	return _upstream_login_via_key(key)

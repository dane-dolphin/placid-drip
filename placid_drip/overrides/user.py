"""Overrides for `frappe.core.doctype.user.user` whitelisted methods."""

import inspect

import frappe
from frappe.core.doctype.user import user as frappe_user

from placid_drip.rate_limits import check_ip_rate_limits

# Unwrapped past frappe's type-check and rate_limit decorators so its System
# Settings limit doesn't stack on top of ours. Our own @whitelist type-checks.
_upstream_reset_password = inspect.unwrap(frappe_user.reset_password)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def reset_password(user: str) -> str:
	check_ip_rate_limits("reset_password")
	return _upstream_reset_password(user)

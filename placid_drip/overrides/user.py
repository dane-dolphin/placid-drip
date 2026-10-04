"""Overrides for `frappe.core.doctype.user.user` whitelisted methods."""

import inspect

import frappe
from frappe import _
from frappe.core.doctype.user import user as frappe_user

#: Password-reset requests allowed per IP, as (limit, window in seconds). These
#: replace frappe's single hourly `password_reset_limit` from System Settings,
#: which no longer applies to this endpoint.
RESET_PASSWORD_LIMITS_PER_IP = (
	(50, 60 * 60),
	(1000, 24 * 60 * 60),
)

_upstream_reset_password = inspect.unwrap(frappe_user.reset_password)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def reset_password(user: str) -> str:
	_check_rate_limits()
	# Unwrap past frappe's type-check and rate_limit decorators so its System
	# Settings limit doesn't stack on top of ours. Our own @whitelist already
	# type-checks `user`.
	return _upstream_reset_password(user)


def _check_rate_limits():
	"""Fixed windows per IP, same shape as frappe's rate_limit decorator.

	frappe's decorator can't be stacked for two windows: it keys its counter on
	the request's cmd and IP only, so both windows would share one counter.
	"""
	ip = frappe.local.request_ip
	if not ip:
		return

	for limit, seconds in RESET_PASSWORD_LIMITS_PER_IP:
		cache_key = frappe.cache.make_key(f"rl:reset_password:{seconds}:{ip}")
		if not frappe.cache.get(cache_key):
			frappe.cache.setex(cache_key, seconds, 0)

		if frappe.cache.incrby(cache_key, 1) > limit:
			frappe.throw(
				_("You hit the rate limit because of too many requests. Please try after sometime."),
				frappe.RateLimitExceededError,
			)

"""Overrides for `frappe.core.doctype.user.user` whitelisted methods."""

import frappe
from frappe import _
from frappe.core.doctype.user import user as frappe_user

#: Daily ceiling on password-reset requests from one IP. The hourly limit is
#: frappe's own `password_reset_limit` in System Settings, which still applies
#: because we call through to the decorated upstream function.
RESET_PASSWORD_DAILY_LIMIT_PER_IP = 1000
ONE_DAY = 24 * 60 * 60


@frappe.whitelist(allow_guest=True, methods=["POST"])
def reset_password(user: str) -> str:
	_check_daily_limit()
	return frappe_user.reset_password(user)


def _check_daily_limit():
	"""Fixed 24h window per IP, same shape as frappe's rate_limit decorator.

	frappe's decorator can't be stacked for a second window here: it keys its
	counter on the request's cmd and IP only, so a daily and an hourly limit on
	the same method would share one counter.
	"""
	ip = frappe.local.request_ip
	if not ip:
		return

	cache_key = frappe.cache.make_key(f"rl-daily:reset_password:{ip}")
	if not frappe.cache.get(cache_key):
		frappe.cache.setex(cache_key, ONE_DAY, 0)

	if frappe.cache.incrby(cache_key, 1) > RESET_PASSWORD_DAILY_LIMIT_PER_IP:
		frappe.throw(
			_("You hit the rate limit because of too many requests. Please try after sometime."),
			frappe.RateLimitExceededError,
		)

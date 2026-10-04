"""Per-IP rate limits for the guest login/password endpoints we override."""

import frappe
from frappe import _

#: Requests allowed per IP for each limited endpoint, as (limit, window in seconds).
#: These replace frappe's single hourly limits from System Settings
#: (`password_reset_limit`, `rate_limit_email_link_login`), which no longer apply.
PER_IP_LIMITS = (
	(50, 60 * 60),
	(1000, 24 * 60 * 60),
)


def check_ip_rate_limits(name: str):
	"""Fixed windows per IP, same shape as frappe's rate_limit decorator.

	frappe's decorator can't be stacked for two windows: it keys its counter on
	the request's cmd and IP only, so both windows would share one counter.
	`name` keeps each endpoint's counters separate.
	"""
	ip = frappe.local.request_ip
	if not ip:
		return

	for limit, seconds in PER_IP_LIMITS:
		cache_key = frappe.cache.make_key(f"rl:{name}:{seconds}:{ip}")
		if not frappe.cache.get(cache_key):
			frappe.cache.setex(cache_key, seconds, 0)

		if frappe.cache.incrby(cache_key, 1) > limit:
			frappe.throw(
				_("You hit the rate limit because of too many requests. Please try after sometime."),
				frappe.RateLimitExceededError,
			)

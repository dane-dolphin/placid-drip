"""Shorten the login lockout window from 60s to 10s.

frappe/auth.py:257 runs two failed-login trackers: one keyed by `user.name` and
one keyed by `frappe.local.request_ip`. Ten consecutive failures therefore lock
the whole IP, not just the account - so one person fat-fingering a password
during testing stalls everyone behind that address.

The threshold (`allow_consecutive_login_attempts`) deliberately stays at 10, so
a brute-force attempt is still throttled to roughly 60 guesses per minute rather
than being let loose. Only the wait after tripping it is reduced, which is what
actually interrupts a testing session.

Both values remain editable in System Settings; this patch only lowers the wait
if it is currently longer than the target.
"""

import frappe

TARGET_LOCK_SECONDS = 10
FIELD = "allow_login_after_fail"


def execute():
	settings = frappe.get_single("System Settings")

	if not settings.meta.has_field(FIELD):
		return

	current = frappe.utils.cint(settings.get(FIELD))

	# 0 disables the wait entirely - never "raise" it to 10 by accident.
	if current and current <= TARGET_LOCK_SECONDS:
		print(f"shorten_login_lockout: {FIELD} already {current}s, leaving alone")
		return

	frappe.db.set_single_value("System Settings", FIELD, TARGET_LOCK_SECONDS)
	frappe.clear_cache()

	threshold = frappe.utils.cint(settings.get("allow_consecutive_login_attempts"))
	print(
		f"shorten_login_lockout: {FIELD} {current}s -> {TARGET_LOCK_SECONDS}s "
		f"(threshold unchanged at {threshold} consecutive failures)"
	)

"""Log users out after 21 days of inactivity instead of frappe's ~7 (170:00).

Students use the site on a weekly cadence, often from a shared desktop, and the
7-day idle timeout logged them out between sessions. The timeout is idle time:
frappe re-issues the sid cookie on every request, so active users never expire.

frappe reads the timeout from the global default (frappe/sessions.py
get_expiry_period), not from the System Settings single - saving the settings
form copies one into the other via set_defaults(). Setting the single alone
would show 504:00 in Desk while sessions still expired at 170:00, so both are
written here.

Still editable in System Settings afterwards; this patch only runs once.
"""

import frappe

TARGET_EXPIRY = "504:00"  # hours:minutes - 21 days
FIELD = "session_expiry"


def execute():
	current = frappe.db.get_single_value("System Settings", FIELD)

	frappe.db.set_single_value("System Settings", FIELD, TARGET_EXPIRY)
	frappe.db.set_default(FIELD, TARGET_EXPIRY)
	frappe.clear_cache()

	print(f"set_session_expiry_21_days: {FIELD} {current} -> {TARGET_EXPIRY}")

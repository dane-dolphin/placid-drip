"""Log users out after 21 days of inactivity instead of frappe's ~7 (170:00).

Students use the site on a weekly cadence, often from a shared desktop, and the
7-day idle timeout logged them out between sessions. The timeout is idle time:
frappe re-issues the sid cookie on every request, so active users never expire.

frappe reads the timeout from the global default (frappe/sessions.py
get_expiry_period), not from the System Settings single - saving the settings
form copies one into the other via set_defaults(). Setting the single alone
would show 504:00 in Desk while sessions still expired at 170:00, so both are
written here.

Sessions that already exist keep the expiry they were created with (frappe
stores it in each session's data) until the user next logs in.

Only ever raises the timeout: a longer value already set in System Settings is
left alone. Still editable there afterwards; this patch only runs once.
"""

import frappe
from frappe.sessions import get_expiry_in_seconds

TARGET_EXPIRY = "504:00"  # hours:minutes - 21 days
FIELD = "session_expiry"


def execute():
	current = frappe.db.get_default(FIELD) or frappe.db.get_single_value("System Settings", FIELD)

	if current and get_expiry_in_seconds(_with_seconds(current)) >= get_expiry_in_seconds(
		_with_seconds(TARGET_EXPIRY)
	):
		print(f"set_session_expiry_21_days: {FIELD} already {current}, leaving alone")
		return

	frappe.db.set_single_value("System Settings", FIELD, TARGET_EXPIRY)
	frappe.db.set_default(FIELD, TARGET_EXPIRY)
	frappe.clear_cache()

	print(f"set_session_expiry_21_days: {FIELD} {current} -> {TARGET_EXPIRY}")


def _with_seconds(value: str) -> str:
	# Stored as "hh:mm"; get_expiry_in_seconds expects "hh:mm:ss".
	return value + ":00" if len(value.split(":")) == 2 else value

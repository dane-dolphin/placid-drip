"""Multiply the DB-backed login limits by 10.

The request-rate limits live in files (site_config.json, lms RATE_LIMIT,
placid_drip RATE_LIMIT) and are already raised there. These two live in the
System Settings single doctype, so they need a patch.

`allow_login_after_fail` is deliberately NOT touched - it is the lockout
*duration*, so multiplying it would make lockouts ten times longer, not looser.
"""

import frappe

MULTIPLIER = 10

# fieldname -> value to assume when the setting has never been set
FIELDS = {
	"allow_consecutive_login_attempts": 10,
	"rate_limit_email_link_login": 5,
}


def execute():
	settings = frappe.get_single("System Settings")

	for fieldname, fallback in FIELDS.items():
		if not settings.meta.has_field(fieldname):
			continue

		current = frappe.utils.cint(settings.get(fieldname)) or fallback

		# 0 means "no limit" in Frappe - scaling it would silently re-enable a limit.
		if not current:
			continue

		frappe.db.set_single_value("System Settings", fieldname, current * MULTIPLIER)

	frappe.clear_cache()

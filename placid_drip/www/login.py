# Overriding login.html also replaces frappe's controller, so reuse its context
# (logo, signup/social-login flags, redirect for logged-in users).
from frappe.www.login import get_context  # noqa: F401

no_cache = True

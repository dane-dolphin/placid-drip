"""Passwordless login with a 6-digit code sent by email.

Replaces frappe's "login with email link". It is switched on by the same System
Settings checkbox (`login_with_email_link`), which is what makes the login page
show the option.

One active code per user, kept in redis. Requesting another code while one is
still active resends the same code (and restarts its clock) rather than
replacing it, so every code email a student has received keeps working - the
"only the newest email works" trap that password reset links have.

Guessing is capped twice: MAX_ATTEMPTS per code, and MAX_FAILURES_PER_HOUR per
account across codes, since requesting a fresh code would otherwise reset the
per-code count.
"""

import hmac
import secrets

import frappe
from frappe import _
from frappe.apps import get_default_path
from frappe.website.utils import get_home_page
from frappe.www.login import sanitize_redirect

from placid_drip.rate_limits import check_ip_rate_limits

CODE_LENGTH = 6
CODE_TTL_SECONDS = 10 * 60
MAX_ATTEMPTS = 5
MAX_FAILURES_PER_HOUR = 15


@frappe.whitelist(allow_guest=True, methods=["POST"])
def send_login_code(email: str):
	check_ip_rate_limits("send_login_code")
	_ensure_enabled()
	user = _get_enabled_user(email)

	code = _get_active_code(user) or _new_code(user)
	# Restart the clock on every send, so the code in the email the student just
	# received is good for the full window.
	_store_code(user, code)
	_send_code_email(user, code)
	return {"expires_in_minutes": CODE_TTL_SECONDS // 60}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def verify_login_code(email: str, code: str, redirect_to: str | None = None):
	check_ip_rate_limits("verify_login_code")
	_ensure_enabled()
	user = _get_enabled_user(email)
	code = (code or "").strip()

	_check_failures_per_hour(user)

	active_code = _get_active_code(user)
	if not active_code:
		frappe.throw(
			_("This code has expired. Please request a new one."),
			frappe.AuthenticationError,
			title=_("Code expired"),
		)

	if not hmac.compare_digest(active_code.encode(), code.encode()):
		_record_failure(user)
		# Atomic, so parallel guesses can't each see a stale count.
		remaining = MAX_ATTEMPTS - frappe.cache.incrby(_key(user, "attempts"), 1)
		if remaining <= 0:
			_clear_code(user)
			message = _("That code is incorrect. Please request a new code.")
		else:
			message = _("That code is incorrect. {0} attempt(s) left.").format(remaining)
		frappe.throw(message, frappe.AuthenticationError, title=_("Incorrect code"))

	_clear_code(user)
	frappe.local.login_manager.login_as(user)
	return _post_login_path(user, redirect_to)


def _ensure_enabled():
	if not frappe.get_system_settings("login_with_email_link"):
		frappe.throw(_("Login with an email code is not enabled."), frappe.PermissionError)


def _get_enabled_user(email: str) -> str:
	email = (email or "").strip()
	user = email and frappe.db.get_value("User", {"email": email, "enabled": 1}, "name")
	if not user or user in ("Administrator", "Guest"):
		frappe.throw(
			_("We could not find an account with that email. Please check the spelling, or contact your facilitator."),
			frappe.DoesNotExistError,
			title=_("Account not found"),
		)
	return user


def _key(user: str, part: str) -> str:
	return frappe.cache.make_key(f"login_code:{part}:{user}")


def _new_code(user: str) -> str:
	return f"{secrets.randbelow(10**CODE_LENGTH):0{CODE_LENGTH}d}"


def _get_active_code(user: str) -> str | None:
	code = frappe.cache.get(_key(user, "code"))
	return code.decode() if code else None


def _store_code(user: str, code: str):
	"""(Re)start the code's window. The per-code attempt count carries over a
	resend; it only resets when a brand new code is issued."""
	if frappe.cache.get(_key(user, "code")) is None:
		frappe.cache.setex(_key(user, "attempts"), CODE_TTL_SECONDS, 0)
	else:
		frappe.cache.expire(_key(user, "attempts"), CODE_TTL_SECONDS)
	frappe.cache.setex(_key(user, "code"), CODE_TTL_SECONDS, code)


def _clear_code(user: str):
	frappe.cache.delete(_key(user, "code"), _key(user, "attempts"))


def _check_failures_per_hour(user: str):
	failures = int(frappe.cache.get(_key(user, "failures")) or 0)
	if failures >= MAX_FAILURES_PER_HOUR:
		frappe.throw(
			_("Too many incorrect codes for this account. Please try again in an hour."),
			frappe.RateLimitExceededError,
		)


def _record_failure(user: str):
	key = _key(user, "failures")
	if frappe.cache.get(key) is None:
		frappe.cache.setex(key, 60 * 60, 0)
	frappe.cache.incrby(key, 1)


def _send_code_email(user: str, code: str):
	app_name = (
		frappe.get_website_settings("app_name") or frappe.get_system_settings("app_name") or "Placid Academy"
	)
	minutes = CODE_TTL_SECONDS // 60
	message = f"""
		<p>{_("Here is your login code for {0}:").format(frappe.utils.escape_html(app_name))}</p>
		<p style="font-size: 32px; font-weight: 700; letter-spacing: 8px; margin: 24px 0;">{code}</p>
		<p>{_("Enter it on the login page. It works for {0} minutes.").format(minutes)}</p>
		<p style="color: #6b7280;">{_("If you did not ask for this code, you can ignore this email.")}</p>
	"""
	frappe.sendmail(
		recipients=[user],
		subject=_("{0} is your {1} login code").format(code, app_name),
		message=message,
		now=True,
	)


def _post_login_path(user: str, redirect_to: str | None) -> str:
	redirect_to = sanitize_redirect(redirect_to)
	if redirect_to and redirect_to != "login":
		return redirect_to
	if frappe.db.get_value("User", user, "user_type") == "System User":
		return get_default_path() or "/app"
	return get_default_path() or get_home_page()

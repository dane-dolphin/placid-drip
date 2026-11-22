"""Passwordless login with a 6-digit code sent by email.

Replaces frappe's "login with email link". It is switched on by the same System
Settings checkbox (`login_with_email_link`), which is what makes the login page
show the option.

One active code per user, kept in redis. Requesting another code while one is
still active resends the same code (and restarts its clock) rather than
replacing it, so every code email a student has received keeps working - the
"only the newest email works" trap that password reset links have.

Guessing is capped twice: MAX_ATTEMPTS per code, and MAX_GUESSES_PER_HOUR per
account across codes, since requesting a fresh code would otherwise reset the
per-code count. Both are counted before the code is compared, so concurrent
guesses can't slip past either cap.

Accounts with two-factor auth can't use this: login_as() would skip their
second factor.
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
MAX_GUESSES_PER_HOUR = 15


@frappe.whitelist(allow_guest=True, methods=["POST"])
def send_login_code(email: str):
	check_ip_rate_limits("send_login_code")
	_ensure_enabled()
	user, user_email = _get_enabled_user(email)

	code = _get_active_code(user)
	is_new = code is None
	if is_new:
		code = _new_code()
	# Restart the clock on every send, so the code in the email the student just
	# received is good for the full window.
	_store_code(user, code, is_new)
	_send_code_email(user_email, code)
	return {"expires_in_minutes": CODE_TTL_SECONDS // 60}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def verify_login_code(email: str, code: str, redirect_to: str | None = None):
	check_ip_rate_limits("verify_login_code")
	_ensure_enabled()
	user, _user_email = _get_enabled_user(email)
	code = (code or "").strip()

	active_code = _get_active_code(user)
	if not active_code:
		frappe.throw(
			_("This code has expired. Please request a new one."),
			frappe.AuthenticationError,
			title=_("Code expired"),
		)

	# Count the guess before comparing. INCR is atomic, so of any number of
	# concurrent requests only the first MAX_ATTEMPTS get to compare at all.
	if _incr_with_ttl(_key(user, "guesses"), 60 * 60) > MAX_GUESSES_PER_HOUR:
		frappe.throw(
			_("Too many incorrect codes for this account. Please try again in an hour."),
			frappe.RateLimitExceededError,
		)
	attempt = _incr_with_ttl(_key(user, "attempts"), CODE_TTL_SECONDS)
	if attempt > MAX_ATTEMPTS:
		_clear_code(user)
		frappe.throw(
			_("Too many wrong attempts. Please request a new code."),
			frappe.AuthenticationError,
			title=_("Code expired"),
		)

	if not hmac.compare_digest(active_code.encode(), code.encode()):
		remaining = MAX_ATTEMPTS - attempt
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


def _get_enabled_user(email: str) -> tuple[str, str]:
	"""Return (user name, email). They differ if the email was edited after the
	account was created - the code must go to the email, not the name."""
	from frappe.twofactor import two_factor_is_enabled

	email = (email or "").strip()
	row = email and frappe.db.get_value("User", {"email": email, "enabled": 1}, ["name", "email"])
	if not row or row[0] in ("Administrator", "Guest"):
		frappe.throw(
			_("We could not find an account with that email. Please check the spelling, or contact your facilitator."),
			frappe.DoesNotExistError,
			title=_("Account not found"),
		)
	if two_factor_is_enabled(user=row[0]):
		frappe.throw(
			_("This account uses two-factor authentication. Please log in with your password."),
			frappe.PermissionError,
		)
	return row[0], row[1]


def _key(user: str, part: str) -> str:
	return frappe.cache.make_key(f"login_code:{part}:{user}")


def _new_code() -> str:
	return f"{secrets.randbelow(10**CODE_LENGTH):0{CODE_LENGTH}d}"


def _get_active_code(user: str) -> str | None:
	code = frappe.cache.get(_key(user, "code"))
	return code.decode() if code else None


def _store_code(user: str, code: str, is_new: bool):
	"""(Re)start the code's window. The per-code attempt count carries over a
	resend; it only resets when a brand new code is issued."""
	if is_new:
		frappe.cache.delete(_key(user, "attempts"))
	else:
		frappe.cache.expire(_key(user, "attempts"), CODE_TTL_SECONDS)
	frappe.cache.setex(_key(user, "code"), CODE_TTL_SECONDS, code)


def _clear_code(user: str):
	frappe.cache.delete(_key(user, "code"), _key(user, "attempts"))


def _incr_with_ttl(key: str, seconds: int) -> int:
	"""INCR, giving the key its expiry when this call created it. Unlike
	get/setex/incr, a key that expires mid-way can't be recreated without one."""
	value = frappe.cache.incrby(key, 1)
	if value == 1:
		frappe.cache.expire(key, seconds)
	return value


def _send_code_email(email: str, code: str):
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
		recipients=[email],
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

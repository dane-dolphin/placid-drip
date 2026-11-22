"""Creating a student's account from something other than self-signup.

Self-registration is switched off on this site (`Website Settings.disable_signup`),
so every student account is created here, on the strength of whatever authorised
it - an invite key for their address, or a batch's join link. The caller has
already checked that authorisation; this module only knows how to turn an email,
a name and a password into a working Website User.
"""

import frappe
from frappe import _
from frappe.utils.password import update_password

#: `User.first_name` / `last_name` are Data fields.
MAX_NAME_LENGTH = 140

#: Same ceiling frappe applies in `update_password`.
MAX_PASSWORD_LENGTH = 512


def user_for_email(email: str) -> str | None:
	"""The User id for `email`, or None if nobody has registered with it."""
	email = (email or "").strip().lower()
	if not email:
		return None
	return frappe.db.exists("User", {"email": email})


def validate_name_and_password(first_name: str, last_name: str, password: str) -> tuple[str, str]:
	"""Trim and bound the free-text inputs. Returns (first_name, last_name).

	Password *strength* is deliberately not checked here: `User.validate` enforces
	the System Settings policy with frappe's own messages, and does it with the
	person's name and address as inputs, which a standalone check would not have.
	"""
	first_name = (first_name or "").strip()
	last_name = (last_name or "").strip()

	if not first_name:
		frappe.throw(_("Please enter your first name."))
	if len(first_name) > MAX_NAME_LENGTH or len(last_name) > MAX_NAME_LENGTH:
		frappe.throw(_("Name is too long."))

	if not password:
		frappe.throw(_("Please choose a password."))
	if len(password) > MAX_PASSWORD_LENGTH:
		frappe.throw(_("Password size exceeded the maximum allowed size."))

	return first_name, last_name


def create_student_account(
	email: str,
	first_name: str,
	last_name: str,
	password: str,
	skip_pending_invites: bool = False,
):
	"""Create an enabled Website User with a working password, and return it.

	No welcome email: the person chose their password a moment ago and is about to
	be signed in, so a "set up your account" mail would only confuse them.

	`skip_pending_invites` tells the `User.after_insert` hook in `placid_drip.invites`
	not to apply pending email invites for this address - wanted when the person is
	registering off one of those invites and will pick their batches on the next
	screen, not wanted otherwise.
	"""
	first_name, last_name = validate_name_and_password(first_name, last_name, password)

	user = frappe.new_doc("User")
	user.email = email
	user.first_name = first_name
	user.last_name = last_name or None
	user.user_type = "Website User"
	user.enabled = 1
	user.send_welcome_email = 0
	# Checked against the System Settings password policy in `User.validate`, with
	# the person's name and address as inputs, so a weak choice fails here.
	user.new_password = password
	user.flags.no_welcome_mail = True
	user.flags.skip_pending_invites = skip_pending_invites
	user.insert(ignore_permissions=True)

	# Stored explicitly rather than trusting the insert to do it. `User.on_update`
	# would, except that `lms.lms.user.after_insert` grants LMS Student through
	# `add_roles`, which saves the document again first; that re-run of `validate`
	# sees an empty `new_password` and overwrites the one queued for storage, so
	# the account ends up with no password at all.
	update_password(user.name, password)

	return user

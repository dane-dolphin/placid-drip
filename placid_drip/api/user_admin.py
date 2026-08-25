"""Creating accounts from the admin flow, with one LMS role each.

This backs the "Add Users" page. It exists because the two routes an admin had
before both fall down:

- Desk's User Import needs a `First Name` column. A template filled in with
  `Full Name` instead silently produces a blank name, because `User.validate()`
  recomputes `full_name` from first/last - and a blank name then sends
  `lms.lms.user.validate_username_duplicates` into an infinite loop that holds a
  write lock on `tabDefaultValue` and blocks every user save on the site.
- `lms.lms.api.add_an_evaluator` only ever grants Batch Evaluator, so there was
  no single place to add a Course Creator or a plain Student.

So `first_name` here is never allowed to end up empty, whatever the caller sends.
"""

import re

import frappe
from frappe import _
from frappe.database import savepoint

from placid_drip.invites import parse_emails

#: UI label -> Frappe role. Deliberately a closed allowlist: this endpoint
#: creates accounts, so letting a caller name any role would turn it into a way
#: to mint Moderators or System Managers. The labels are the ones the rest of the
#: app already shows - a Batch Evaluator is called a "Facilitator" everywhere in
#: the frontend (see `UserDropdown.vue`), and the page's select mirrors these.
ASSIGNABLE_ROLES = {
	"Facilitator": "Batch Evaluator",
	"Course Creator": "Course Creator",
	"Student": "LMS Student",
}


@frappe.whitelist()
def create_users(emails, role, full_name=None):
	"""Create an account per address and grant all of them `role`.

	`emails` may be a pasted blob (commas, semicolons, spaces or newlines) or a
	list. Returns a per-address breakdown rather than a count, because "9 users
	added" hides the one typo that did nothing.

	`full_name` is applied only when a single address was given - naming a whole
	pasted column the same thing is never what was meant - and is reported back
	as ignored otherwise rather than silently dropped.
	"""
	frappe.only_for("Moderator")

	role_name = ASSIGNABLE_ROLES.get((role or "").strip())
	if not role_name:
		frappe.throw(
			_("Pick one of: {0}.").format(", ".join(ASSIGNABLE_ROLES)),
			title=_("Unknown role"),
		)

	valid, invalid = parse_emails(emails)
	if not valid:
		frappe.throw(_("No valid email addresses found."))

	result = {
		"role": role,
		"created": [],
		"role_granted": [],
		"already_had_role": [],
		"failed": [],
		"invalid": invalid,
		# Set when a name was typed but more than one address was pasted, so the
		# page can say so instead of leaving the admin to notice the names later.
		"full_name_ignored": bool((full_name or "").strip()) and len(valid) > 1,
	}

	first_name, last_name = ("", "")
	if len(valid) == 1:
		first_name, last_name = split_full_name(full_name)

	# Tracebacks are collected and written after the loop: `frappe.log_error`
	# writes a document, so logging inside the savepoint below would roll the log
	# back along with the failure it was describing.
	failures = []

	for email in valid:
		outcome = {}

		# One bad address must not take the whole batch down with it. Frappe's
		# savepoint swallows the exception after rolling back, hence the flag
		# rather than a try/except around the loop body.
		with savepoint():
			try:
				outcome["bucket"] = _add_user(email, role_name, first_name, last_name)
			except Exception:
				outcome["traceback"] = frappe.get_traceback()
				raise

		if "bucket" in outcome:
			result[outcome["bucket"]].append(email)
		else:
			result["failed"].append(email)
			failures.append((email, outcome.get("traceback", "")))

	for email, traceback in failures:
		frappe.log_error(
			title="Add Users: could not create account",
			message=f"email={email}\nrole={role_name}\n\n{traceback}",
		)

	return result


def split_full_name(full_name) -> tuple[str, str]:
	"""Split a typed name into (first_name, last_name).

	The last word is the surname and everything before it is the first name, so
	"Mary Anne Van Der Berg" keeps its four leading words together instead of
	being cut after the first. A single word is a first name with no surname -
	User only requires the one.
	"""
	parts = (full_name or "").split()

	if not parts:
		return "", ""
	if len(parts) == 1:
		return parts[0], ""

	return " ".join(parts[:-1]), parts[-1]


def name_from_email(email: str) -> str:
	"""A provisional first name for an address with no name attached.

	`User` requires a non-empty first name, and an empty one is actively
	dangerous here - see the module docstring. Kept obviously provisional rather
	than guessing a surname out of the local part, since a wrong name is harder
	to spot than a placeholder one.
	"""
	local = email.split("@")[0]
	cleaned = re.sub(r"[._\-+]+", " ", local).strip()
	return cleaned.title() or email


def _add_user(email: str, role_name: str, first_name: str, last_name: str) -> str:
	"""Create or update one account. Returns the result bucket for `create_users`."""
	existing = frappe.db.exists("User", {"email": email})

	if existing:
		# Already on the site - this is a role grant, not a signup. Their name is
		# left alone: it is theirs, and may well be better than what was typed here.
		granted = _grant_role(existing, role_name)
		_ensure_evaluator_record(existing, role_name)
		return "role_granted" if granted else "already_had_role"

	user = frappe.new_doc("User")
	user.email = email
	user.first_name = first_name or name_from_email(email)
	user.last_name = last_name
	user.user_type = "Website User"
	user.enabled = 1
	# Without this the account exists but is unreachable: signup is disabled on
	# this site, so there is no other way for them to get a password - or to log
	# in and correct the placeholder name.
	user.send_welcome_email = 1
	user.insert(ignore_permissions=True)

	# `lms.lms.user.after_insert` has already granted LMS Student to every new
	# user, so for a Student this is a no-op and correctly reports "created".
	_grant_role(user.name, role_name)
	_ensure_evaluator_record(user.name, role_name)

	return "created"


def _grant_role(user: str, role_name: str) -> bool:
	"""Give `user` the role. Returns False if they already had it."""
	if frappe.db.exists("Has Role", {"parent": user, "role": role_name}):
		return False

	frappe.get_doc(
		{
			"doctype": "Has Role",
			"parent": user,
			"role": role_name,
			"parenttype": "User",
			"parentfield": "roles",
		}
	).save(ignore_permissions=True)

	frappe.clear_cache(user=user)
	return True


def _ensure_evaluator_record(user: str, role_name: str) -> None:
	"""Facilitators need a Course Evaluator row, not just the role.

	`lms.lms.api.add_an_evaluator` creates both, and the evaluation scheduling
	pages look the row up rather than checking the role, so granting Batch
	Evaluator on its own produces a facilitator who does not appear as one.
	"""
	if role_name != "Batch Evaluator":
		return

	if frappe.db.exists("Course Evaluator", {"evaluator": user}):
		return

	evaluator = frappe.new_doc("Course Evaluator")
	evaluator.evaluator = user
	evaluator.insert(ignore_permissions=True)

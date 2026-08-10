"""Bulk student invites, and the enrolment they turn into.

Two things are missing from what the site can do today. Frappe's own member
invite creates an account but knows nothing about batches, so an invited student
lands with no batch and no courses. And only administrators can send it, which
leaves a facilitator unable to populate the batch they run.

This closes both. An invite is a standing offer keyed on an email address; the
enrolment is applied by `accept_for_user`, driven off `User.after_insert`. Keying
on email rather than on the invite token is deliberate - it means the enrolment
lands however the account is eventually created, including an admin adding the
person by hand in Desk, which a token-redemption flow would miss entirely.

Creating the `LMS Batch Enrollment` row is all that is needed to enrol someone in
the batch's courses too: `LMSBatchEnrollment.after_insert` already calls
`enroll_member_in_batch_courses`. That is exactly the step the stock invite skips.
"""

import re

import frappe
from frappe import _
from frappe.utils import get_url, now_datetime, validate_email_address

from placid_drip.facilitator import get_facilitated_batch_names, is_staff

#: Anything a human might paste between addresses: commas, semicolons, newlines,
#: tabs or plain spaces. Pasting a column out of a spreadsheet has to just work.
SPLIT_PATTERN = re.compile(r"[,;\s]+")

#: `Anna Smith <anna@example.com>` - the shape you get pasting out of a mail client.
#: The display name is consumed along with the brackets, not just stripped off the
#: address, so it never reaches the splitter and gets reported as a bad address.
ANGLE_PATTERN = re.compile(r'(?:"[^"]*"\s*|[^,;<>]*)<([^<>@\s]+@[^<>@\s]+)>')


def parse_emails(raw) -> tuple[list[str], list[str]]:
	"""Split a pasted blob into (valid, invalid) address lists.

	Order is preserved and duplicates are dropped, so the facilitator gets a
	result list they can actually reconcile against what they pasted.
	"""
	text = " ".join(str(i or "") for i in raw) if isinstance(raw, (list, tuple)) else str(raw or "")

	# Pull "Anna Smith <anna@example.com>" down to the address first. Splitting on
	# whitespace without this would turn the display name into two entries and
	# report them back as invalid addresses, which reads as a failure when the
	# paste was in fact perfectly good.
	text = ANGLE_PATTERN.sub(lambda m: f" {m.group(1)} ", text)

	candidates = SPLIT_PATTERN.split(text)

	valid, invalid, seen = [], [], set()

	for candidate in candidates:
		email = candidate.strip().strip("<>").lower()
		if not email:
			continue
		if email in seen:
			continue
		seen.add(email)

		if validate_email_address(email):
			valid.append(email)
		else:
			invalid.append(email)

	return valid, invalid


def get_invitable_batches(user: str) -> list[str] | None:
	"""Batches `user` may invite into. `None` means "no restriction"."""
	if is_staff(user):
		return None

	return get_facilitated_batch_names(user)


def assert_can_invite(batches: list[str], user: str) -> None:
	"""A facilitator may only invite into batches they evaluate or instruct.

	Without this, the Batch Evaluator write permission on Student Invite would let
	any facilitator enrol students into any batch on the site - a wider grant than
	the feature is asking for.
	"""
	allowed = get_invitable_batches(user)
	if allowed is None:
		return

	forbidden = [b for b in batches if b not in set(allowed)]
	if forbidden:
		frappe.throw(
			_("You can only invite students to batches you evaluate or instruct: {0}").format(
				", ".join(forbidden)
			),
			frappe.PermissionError,
		)


def enroll_in_batches(member: str, batches: list[str]) -> list[str]:
	"""Enrol `member` into each batch. Returns the batches newly enrolled into.

	`ignore_permissions` because the caller has already been authorised by
	`assert_can_invite`, which is a stricter check than the doctype-level one: it
	is bounded to the facilitator's own batches, whereas a create right on
	LMS Batch Enrollment would apply to every batch on the site.
	"""
	added = []

	for batch in batches:
		if not batch:
			continue

		if frappe.db.exists("LMS Batch Enrollment", {"batch": batch, "member": member}):
			continue

		try:
			enrollment = frappe.new_doc("LMS Batch Enrollment")
			enrollment.batch = batch
			enrollment.member = member
			# after_insert on this doctype enrolls the member into the batch's
			# courses, which is the whole point of routing through it rather than
			# writing the row directly.
			enrollment.insert(ignore_permissions=True)
			added.append(batch)
		except Exception:
			# One failing batch must not strand the others, but it must not vanish
			# either - a silently half-applied invite is worse than a loud one.
			frappe.log_error(
				title="Student invite enrollment failed",
				message=f"batch={batch} member={member}\n\n{frappe.get_traceback()}",
			)

	return added


def _existing_pending_invite(email: str):
	name = frappe.db.exists("Student Invite", {"email": email, "status": "Pending"})
	return frappe.get_doc("Student Invite", name) if name else None


def create_or_update_invite(email: str, batches: list[str]):
	"""One pending invite per address, accumulating batches on re-invite.

	Re-inviting somebody who is already pending adds the new batches to the
	existing invite instead of creating a second one, so a second invite cannot
	quietly supersede the batches named by the first.
	"""
	invite = _existing_pending_invite(email)

	if invite:
		known = set(invite.batch_names())
		for batch in batches:
			if batch not in known:
				invite.append("batches", {"batch": batch})
		invite.save(ignore_permissions=True)
		return invite, False

	invite = frappe.new_doc("Student Invite")
	invite.email = email
	for batch in batches:
		invite.append("batches", {"batch": batch})
	invite.insert(ignore_permissions=True)

	return invite, True


def send_invite_email(invite) -> bool:
	"""Best-effort delivery. Returns whether it was handed to the mail queue.

	Never raises: a mail failure must not roll back the invite, because the UI
	offers the link for copying and the invite is perfectly usable without the
	email ever arriving.
	"""
	try:
		batch_titles = [
			frappe.db.get_value("LMS Batch", row.batch, "title") or row.batch
			for row in invite.batches
		]

		frappe.sendmail(
			recipients=[invite.email],
			subject=_("You have been invited to join {0}").format(
				frappe.db.get_single_value("Website Settings", "app_name") or "Placid Academy"
			),
			message=_invite_email_body(invite, batch_titles),
			reference_doctype=invite.doctype,
			reference_name=invite.name,
			retry=3,
		)
		return True
	except Exception:
		frappe.log_error(
			title="Student invite email failed",
			message=f"invite={invite.name} email={invite.email}\n\n{frappe.get_traceback()}",
		)
		return False


def _invite_email_body(invite, batch_titles: list[str]) -> str:
	items = "".join(f"<li>{frappe.utils.escape_html(t)}</li>" for t in batch_titles)

	return f"""
		<p>{_("You have been invited to join the following on Placid Academy:")}</p>
		<ul>{items}</ul>
		<p>
			<a href="{invite.invite_url}">{_("Accept your invitation")}</a>
		</p>
		<p style="color:#666;font-size:13px">
			{_("Please sign up using this address: {0}").format(invite.email)}
		</p>
	"""


def send_invites(emails, batches: list[str]) -> dict:
	"""Invite each address to each batch. See `api.student_invites.send_invites`."""
	user = frappe.session.user
	batches = [b for b in dict.fromkeys(batches or []) if b]

	if not batches:
		frappe.throw(_("Select at least one batch."))

	missing = [b for b in batches if not frappe.db.exists("LMS Batch", b)]
	if missing:
		frappe.throw(_("Unknown batch: {0}").format(", ".join(missing)))

	assert_can_invite(batches, user)

	valid, invalid = parse_emails(emails)
	if not valid:
		frappe.throw(_("No valid email addresses found."))

	result = {
		"invited": [],
		"enrolled": [],
		"already_enrolled": [],
		"invalid": invalid,
		"email_failed": [],
		"account_failed": [],
	}

	for email in valid:
		existing_user = frappe.db.exists("User", {"email": email})

		if existing_user:
			# They already have an account, so there is nothing to wait for - enrol
			# them now rather than sending a signup link they do not need.
			added = enroll_in_batches(existing_user, batches)
			(result["enrolled"] if added else result["already_enrolled"]).append(email)
			continue

		# The invite row is written before the account so that the User.after_insert
		# hook finds it and does the enrolment - one code path, whether the account
		# is created here or by an admin in Desk later.
		invite, _created = create_or_update_invite(email, batches)

		try:
			create_account(email)
			result["invited"].append(email)
		except Exception:
			frappe.log_error(
				title="Student invite account creation failed",
				message=f"email={email}\n\n{frappe.get_traceback()}",
			)
			result["account_failed"].append(email)
			# Fall back to the link, which still works if signup is ever re-enabled
			# or an admin creates the account by hand.
			if not send_invite_email(invite):
				result["email_failed"].append(email)

	return result


def create_account(email: str):
	"""Create the invited student's account and let Frappe mail the setup link.

	Self-registration is disabled on this site, so `sign_up` throws "Sign Up is
	disabled" and any flow that waits for the invitee to register themselves can
	never complete. The invite therefore provisions the account directly - which
	is what Frappe's own member invite already does, minus the batch and course
	enrolment that is the whole point here.

	Two hooks fire off this insert and between them do the rest of the work:
	`lms.lms.user.after_insert` grants the LMS Student role, and
	`placid_drip.invites.accept_for_user` applies the pending invite written just
	above. Nothing here needs to repeat either.

	`send_welcome_email` is what gets the person a password-setup link; without it
	the account exists but is unreachable, since they have no password and cannot
	self-register one.
	"""
	user = frappe.new_doc("User")
	user.email = email
	user.first_name = _name_from_email(email)
	user.user_type = "Website User"
	user.enabled = 1
	user.send_welcome_email = 1
	user.insert(ignore_permissions=True)

	return user


def _name_from_email(email: str) -> str:
	"""A placeholder first name, since User requires one and we only have an address.

	The person can correct it on their profile. Guessing beyond this - splitting
	on dots to invent a surname - gets names wrong more often than it gets them
	right, and a wrong name is harder to notice than an obviously provisional one.
	"""
	local = email.split("@")[0]
	cleaned = re.sub(r"[._\-+]+", " ", local).strip()
	return cleaned.title() or email


def accept_for_user(doc, method=None) -> None:
	"""`User.after_insert` hook: apply any pending invite for this address.

	Runs for every new User on the site, so it exits immediately when there is no
	pending invite - which is the overwhelmingly common case.
	"""
	email = (doc.email or doc.name or "").strip().lower()
	if not email:
		return

	# This hook is registered against User, so it also fires while the app is being
	# installed or migrated - potentially before Student Invite has been synced.
	# Querying a table that does not exist yet would abort the install.
	if frappe.flags.in_install or frappe.flags.in_migrate:
		return

	if not frappe.db.table_exists("Student Invite"):
		return

	pending = frappe.get_all(
		"Student Invite",
		filters={"email": email, "status": "Pending"},
		pluck="name",
	)
	if not pending:
		return

	for name in pending:
		invite = frappe.get_doc("Student Invite", name)

		enroll_in_batches(doc.name, invite.batch_names())

		invite.status = "Accepted"
		invite.accepted_user = doc.name
		invite.accepted_on = now_datetime()
		invite.save(ignore_permissions=True)


def get_invite_url(key: str) -> str:
	return f"{get_url()}/invite?key={key}"


def resend_account_setup(user: str) -> bool:
	"""Re-send the password-setup link for an account that exists but is unused.

	This, not the invite link, is the actionable email once the account has been
	provisioned: someone who has never set a password cannot log in, and with
	self-registration disabled they cannot create one either. Returns whether it
	was queued, so the UI can fall back to telling the facilitator to chase it.
	"""
	try:
		frappe.get_doc("User", user).reset_password(send_email=True)
		return True
	except Exception:
		frappe.log_error(
			title="Student invite password email failed",
			message=f"user={user}\n\n{frappe.get_traceback()}",
		)
		return False

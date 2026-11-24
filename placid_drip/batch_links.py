"""A batch's join link: one URL (and QR code) that enrols whoever opens it.

This is the open-door counterpart to `placid_drip.invites`. An email invite names
a person; a join link names a batch. The facilitator copies the link or shows the
QR code, and anyone who follows it can join by giving their name and email. An
address that already has an account is simply enrolled; a new one is asked for a
password and gets an account on the spot. Self-registration is otherwise switched
off on this site, so holding the link is what authorises creating the account.

The link is a random token stored on the batch itself (`LMS Batch.invite_token`,
a Custom Field added by `patches.add_batch_invite_token`). Resetting the token
kills every copy of the old link at once; clearing it closes the door entirely.
Both are written with `db.set_value` so that neither runs the batch's own save
logic, which re-enrols every student in every course on each `on_update`.
"""

from base64 import b64encode
from io import BytesIO

import frappe
from frappe import _
from frappe.utils import cint, get_url, validate_email_address

from placid_drip.invites import assert_can_invite, enroll_in_batches
from placid_drip.facilitator import get_facilitated_batch_names, is_staff
from placid_drip.student_accounts import MAX_NAME_LENGTH, create_student_account, user_for_email

TOKEN_FIELD = "invite_token"
TOKEN_LENGTH = 32

#: Columns the join page and the facilitator's modal both need.
BATCH_FIELDS = ["name", "title", "description", "start_date", "end_date", "seat_count", TOKEN_FIELD]


# ---------------------------------------------------------------------------
# Facilitator side
# ---------------------------------------------------------------------------


def assert_can_share(batch: str, user: str) -> None:
	"""Same rule as emailing invites: staff, or a facilitator of this batch."""
	if not frappe.db.exists("LMS Batch", batch):
		frappe.throw(_("Unknown batch: {0}").format(batch), frappe.DoesNotExistError)
	assert_can_invite([batch], user)


def get_token(batch: str) -> str | None:
	return frappe.db.get_value("LMS Batch", batch, TOKEN_FIELD) or None


def _set_token(batch: str, token: str | None) -> None:
	frappe.db.set_value("LMS Batch", batch, TOKEN_FIELD, token, update_modified=False)


def ensure_token(batch: str) -> str:
	"""The batch's current token, minting one if it has none yet."""
	token = get_token(batch)
	if not token:
		token = frappe.generate_hash(length=TOKEN_LENGTH)
		_set_token(batch, token)
	return token


def reset_token(batch: str) -> str:
	"""Replace the token. Every copy of the old link stops working immediately."""
	token = frappe.generate_hash(length=TOKEN_LENGTH)
	_set_token(batch, token)
	return token


def clear_token(batch: str) -> None:
	"""Close the door: the batch has no working join link until one is made."""
	_set_token(batch, None)


def join_url(token: str) -> str:
	return f"{get_url()}/join/{token}"


def qr_svg_data_uri(text: str) -> str:
	"""The QR code for `text` as an SVG data URI, ready for an <img src>.

	SVG rather than PNG because it stays crisp at any size on screen and the
	bench's pyqrcode has no PNG backend installed; the modal rasterises it in the
	browser when a PNG download is wanted.
	"""
	from pyqrcode import create as qrcreate

	code = qrcreate(text, error="M")
	stream = BytesIO()
	try:
		code.svg(stream, scale=8, quiet_zone=2, module_color="#111111", background="#ffffff")
		svg = stream.getvalue()
	finally:
		stream.close()

	return "data:image/svg+xml;base64," + b64encode(svg).decode()


def link_payload(batch: str) -> dict:
	"""Everything the invite modal shows. `url` and `qr` are None when the link is off."""
	row = frappe.db.get_value("LMS Batch", batch, ["title", TOKEN_FIELD], as_dict=True)
	token = row.get(TOKEN_FIELD) if row else None
	url = join_url(token) if token else None

	return {
		"batch": batch,
		"title": (row and row.title) or batch,
		"enabled": bool(token),
		"url": url,
		"qr": qr_svg_data_uri(url) if url else None,
	}


# ---------------------------------------------------------------------------
# Student side
# ---------------------------------------------------------------------------


def get_batch_by_token(token: str):
	"""The batch a join link points at, or None for an unknown or cleared token."""
	token = (token or "").strip()
	if not token or len(token) > 64:
		return None

	name = frappe.db.get_value("LMS Batch", {TOKEN_FIELD: token}, "name")
	if not name:
		return None

	return frappe.db.get_value("LMS Batch", name, BATCH_FIELDS, as_dict=True)


def seats_left(batch) -> int | None:
	"""Free seats, or None when the batch has no seat limit."""
	if not cint(batch.seat_count):
		return None
	taken = frappe.db.count("LMS Batch Enrollment", {"batch": batch.name})
	return max(cint(batch.seat_count) - taken, 0)


def is_enrolled(batch: str, user: str) -> bool:
	return bool(user and user != "Guest" and frappe.db.exists("LMS Batch Enrollment", {"batch": batch, "member": user}))


def _batch_for_join(token: str):
	batch = get_batch_by_token(token)
	if not batch:
		# One message for "no such token" and "link switched off": telling a guest
		# which is which would tell them which tokens exist.
		frappe.throw(
			_("This join link is not valid, or is no longer active."),
			frappe.DoesNotExistError,
		)
	return batch


def join(token: str, user: str) -> dict:
	"""Enrol the signed-in `user` in the batch behind `token`.

	Idempotent: joining a batch you are already in is a success, not an error -
	the link is on a slide somewhere and people will scan it twice.
	"""
	batch = _batch_for_join(token)

	if is_enrolled(batch.name, user):
		return {"batch": batch.name, "title": batch.title, "joined": False}

	if seats_left(batch) == 0:
		frappe.throw(_("This batch is full. Please contact your facilitator."))

	enroll_in_batches(user, [batch.name])

	# `enroll_in_batches` logs rather than raises, so that one bad batch cannot
	# strand the rest of an email invite. Here there is only one batch, and a
	# silent failure would leave the person staring at a page saying they are in.
	if not is_enrolled(batch.name, user):
		frappe.throw(_("Could not join the batch. Please try again, or contact your facilitator."))

	return {"batch": batch.name, "title": batch.title, "joined": True}


def join_with_email(token: str, email: str, first_name: str, last_name: str, password: str = "") -> dict:
	"""Enrol whoever owns `email`, creating their account first if they have none.

	Three outcomes, told apart by `status`:

	* ``enrolled`` - the address already has an account, which is now in the batch.
	  Its name is updated to what was typed (see `_update_name`), but the caller
	  must NOT sign the visitor in: knowing an email address is enough to be
	  enrolled, but never enough to be logged in.
	* ``password_required`` - no account yet and no password given. Nothing was
	  written; the page shows its password fields and submits again.
	* ``created`` - a new account was made and enrolled; `user` names it so the
	  caller can sign them in.

	Creating and enrolling is one database transaction: if the enrolment fails,
	the account disappears with it rather than leaving an orphan that cannot join.
	"""
	batch = _batch_for_join(token)

	email = (email or "").strip().lower()
	if not email:
		frappe.throw(_("Please enter your email address."))
	validate_email_address(email, throw=True)

	if not (first_name or "").strip():
		frappe.throw(_("Please enter your first name."))

	existing = user_for_email(email)
	if existing:
		if not cint(frappe.db.get_value("User", existing, "enabled")):
			frappe.throw(_("This account cannot join right now. Please contact your facilitator."))
		result = join(token, existing)
		_update_name(existing, first_name, last_name)
		result["status"] = "enrolled"
		return result

	if seats_left(batch) == 0:
		frappe.throw(_("This batch is full. Please contact your facilitator."))

	if not password:
		return {"batch": batch.name, "title": batch.title, "status": "password_required"}

	user = create_student_account(email, first_name, last_name, password)

	result = join(token, user.name)
	result["status"] = "created"
	result["user"] = user.name
	return result


def _update_name(user: str, first_name: str, last_name: str) -> None:
	"""Bring a returning student's name in line with what they just typed.

	Students are often pre-registered with a placeholder or misspelt name; the
	join form is where they correct it. A blank last name leaves the stored one
	alone rather than erasing it.

	Staff and facilitators are skipped. The form is open to anyone holding the
	link, and it should not be a way to rename the people who run the site.

	Written with `db.set_value`: a full `User.save` re-runs role assignment and
	the LMS hooks for what is a two-column change.
	"""
	if is_staff(user) or get_facilitated_batch_names(user):
		return

	first_name = (first_name or "").strip()[:MAX_NAME_LENGTH]
	last_name = (last_name or "").strip()[:MAX_NAME_LENGTH]
	if not first_name:
		return

	current = frappe.db.get_value("User", user, ["first_name", "middle_name", "last_name"], as_dict=True)
	last_name = last_name or (current.last_name or "")

	if first_name == (current.first_name or "") and last_name == (current.last_name or ""):
		return

	full_name = " ".join(part for part in (first_name, current.middle_name, last_name) if part)
	frappe.db.set_value(
		"User",
		user,
		{"first_name": first_name, "last_name": last_name, "full_name": full_name},
	)
	frappe.clear_cache(user=user)


# ---------------------------------------------------------------------------
# Where a new member lands
# ---------------------------------------------------------------------------


def first_course(batch: str) -> str | None:
	"""The batch's first course, in the order the facilitator arranged them."""
	rows = frappe.get_all(
		"Batch Course",
		filters={"parenttype": "LMS Batch", "parent": batch},
		pluck="course",
		order_by="idx asc",
		limit=1,
	)
	return rows[0] if rows else None


def landing_path(batch: str) -> str:
	"""Where someone who has just joined should go: the first course, ready to start.

	The batch's own page is a list of tabs; a newcomer wants the one button that
	begins the first class. A batch with no courses yet falls back to its page.
	"""
	course = first_course(batch)
	if course:
		return f"/lms/batches/{batch}/courses/{course}"
	return f"/lms/batches/{batch}"

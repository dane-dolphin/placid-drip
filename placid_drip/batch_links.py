"""A batch's join link: one URL (and QR code) that enrols whoever opens it.

This is the open-door counterpart to `placid_drip.invites`. An email invite names
a person; a join link names a batch. The facilitator copies the link or shows the
QR code, and anyone who follows it can join - signing in if they already have an
account, creating one on the spot if not. Self-registration is otherwise switched
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
from placid_drip.student_accounts import create_student_account, user_for_email

TOKEN_FIELD = "invite_token"
TOKEN_LENGTH = 32

#: Columns the join page and the facilitator's modal both need.
BATCH_FIELDS = ["name", "title", "description", "start_date", "end_date", "seat_count", TOKEN_FIELD]


class AccountExistsError(frappe.ValidationError):
	"""Registration attempted with an address that already has an account.

	Its own class so the join page can tell this apart from every other failure
	and offer a log-in button instead of a red line.
	"""


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


def register_and_join(token: str, email: str, first_name: str, last_name: str, password: str) -> dict:
	"""Create an account for a newcomer and enrol it. Returns `join`'s result plus `user`.

	The whole thing is one database transaction: if the enrolment fails, the
	account disappears with it rather than leaving an orphan that cannot join.
	"""
	batch = _batch_for_join(token)

	email = (email or "").strip().lower()
	if not email:
		frappe.throw(_("Please enter your email address."))
	validate_email_address(email, throw=True)

	if user_for_email(email):
		frappe.throw(
			_("An account already exists for {0}. Log in to join this batch.").format(email),
			AccountExistsError,
		)

	if seats_left(batch) == 0:
		frappe.throw(_("This batch is full. Please contact your facilitator."))

	user = create_student_account(email, first_name, last_name, password)

	result = join(token, user.name)
	result["user"] = user.name
	return result

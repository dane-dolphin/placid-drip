"""A standing offer of a place in one or more batches, keyed on an email address.

Nothing is created for the invitee until they actually have an account. The
enrolment happens in `placid_drip.invites.accept_for_user`, driven off
`User.after_insert`, which means it fires however the account comes into
existence - self-signup through the invite link, an admin adding them in Desk,
or a social login. Matching on email rather than on the invite key is what buys
that: a key can only be redeemed by someone who clicked the link.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_url


class StudentInvite(Document):
	def before_insert(self):
		if not self.invite_key:
			self.invite_key = frappe.generate_hash(length=32)

		if not self.invited_by:
			self.invited_by = frappe.session.user

	def validate(self):
		self.email = (self.email or "").strip().lower()
		self.validate_batches()

	def validate_batches(self):
		"""Reject duplicate rows so an invite cannot enrol someone twice."""
		seen = set()
		deduped = []

		for row in self.batches:
			if not row.batch or row.batch in seen:
				continue
			seen.add(row.batch)
			deduped.append(row)

		if not deduped:
			frappe.throw(_("An invite must name at least one batch."))

		self.batches = deduped
		for idx, row in enumerate(self.batches, start=1):
			row.idx = idx

	@property
	def invite_url(self) -> str:
		return f"{get_url()}/invite?key={self.invite_key}"

	def batch_names(self) -> list[str]:
		return [row.batch for row in self.batches if row.batch]

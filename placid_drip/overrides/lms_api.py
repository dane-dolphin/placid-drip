"""Overrides for `lms.lms.api` whitelisted methods."""

import frappe
from frappe import _
from lms.lms import api as lms_api

from placid_drip.facilitator import get_facilitated_batch_names, is_staff
from placid_drip.membership import attach_organization

#: Doctypes a facilitator may delete through `delete_documents`, mapped to the
#: field that leads back to the batch owning the document. Everything else still
#: requires Moderator, exactly as before.
#:
#: The field differs by doctype and getting it wrong fails closed rather than
#: open: `LMS Batch Enrollment` is a top-level doctype with a `batch` link, while
#: `Batch Course` is a child table of LMS Batch, so its owning batch is `parent`
#: and it has no `batch` column at all.
BATCH_FIELD_BY_DOCTYPE = {
	"LMS Batch Enrollment": "batch",
	"Batch Course": "parent",
}

FACILITATOR_DELETABLE = set(BATCH_FIELD_BY_DOCTYPE)


@frappe.whitelist()
def delete_documents(doctype, documents):
	"""Delete documents, letting facilitators manage their own batch's contents.

	`lms.lms.api.delete_documents` is a generic delete endpoint gated on
	`frappe.only_for("Moderator")`, so a Batch Evaluator could not remove a student
	or a course from a batch they run - the same endpoint also deletes quiz
	questions, email templates and Zoom settings, so the role could not simply be
	widened.

	Facilitators are allowed through only for the doctypes in
	`BATCH_FIELD_BY_DOCTYPE`, and only for batches they actually evaluate or
	instruct. The delete itself runs with `ignore_permissions` because that scoping
	check is stricter than the doctype-level permission would be: it is bounded to
	their own batches, whereas a doctype-level delete right would apply to every
	batch in the system.
	"""
	documents = _as_list(documents)
	if not documents:
		return

	user = frappe.session.user

	if not is_staff(user):
		if doctype not in FACILITATOR_DELETABLE:
			# Preserves the original error for every other doctype.
			frappe.only_for("Moderator")

		_require_own_batch(doctype, documents, user)

	for name in documents:
		frappe.delete_doc(doctype, name, ignore_permissions=True)


def _require_own_batch(doctype, documents, user):
	batches = set(get_facilitated_batch_names(user))
	if not batches:
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	batch_field = BATCH_FIELD_BY_DOCTYPE[doctype]

	for name in documents:
		batch = frappe.db.get_value(doctype, name, batch_field)
		if not batch or batch not in batches:
			frappe.throw(
				_("You can only change batches you evaluate or instruct."),
				frappe.PermissionError,
			)


@frappe.whitelist()
def get_profile_details(username):
	"""Upstream profile payload plus the person's organization.

	Deliberately `@frappe.whitelist()` with no `allow_guest`, matching upstream -
	an override that widened this to guests would quietly turn a logged-in-only
	endpoint into a public one, which is not a decision a field addition should be
	making.
	"""
	details = lms_api.get_profile_details(username)

	if details:
		attach_organization([details], user_key="name")

	return details


def _as_list(documents):
	if isinstance(documents, str):
		documents = frappe.parse_json(documents)
	if isinstance(documents, str):  # a bare "NAME" rather than a JSON array
		documents = [documents]
	return [d for d in (documents or []) if d]

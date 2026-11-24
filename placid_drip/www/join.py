"""Landing page for a batch's join link - `/join/<token>`.

Works out which screen the visitor needs and leaves the rendering to the template.
A guest gets a name-and-email form (the password fields appear only if that
address has no account yet); someone signed in gets a single "Join" button;
someone already in the batch is pointed at its first course; and an unknown or switched-off token gets a dead
end that reveals nothing about which tokens exist. The writes happen in
`placid_drip.api.batch_join`.
"""

from urllib.parse import quote

import frappe
import frappe.sessions
from frappe import _
from frappe.utils import formatdate

from placid_drip import batch_links

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = False
	context.no_breadcrumbs = True

	token = (frappe.form_dict.get("token") or "").strip()
	context.token = token
	context.mode = "unavailable"
	context.message = None

	batch = batch_links.get_batch_by_token(token) if token else None

	if not batch:
		context.message = (
			_("This join link is not valid, or is no longer active.")
			if token
			else _("This join link is missing its code.")
		)
		return context

	context.batch = _describe(batch)
	context.batch_url = batch_links.landing_path(batch.name)
	context.login_url = "/login?redirect-to=" + quote(f"/join/{token}", safe="")

	user = frappe.session.user

	if user != "Guest":
		# A session that has only ever rendered website pages may not have a CSRF
		# token yet, in which case the page would print "None" and the join POST
		# would break the moment another tab (the LMS app, say) minted one.
		frappe.sessions.get_csrf_token()

		if batch_links.is_enrolled(batch.name, user):
			context.mode = "enrolled"
			return context

		context.first_name = frappe.db.get_value("User", user, "first_name") or ""
		context.user_email = (frappe.db.get_value("User", user, "email") or user).strip().lower()

	if batch_links.seats_left(batch) == 0:
		context.mode = "full"
		return context

	context.mode = "join" if user != "Guest" else "register"
	return context


def _describe(batch) -> dict:
	"""What the visitor is being asked to join: title, dates and who runs it."""
	instructors = frappe.get_all(
		"Course Instructor",
		filters={"parenttype": "LMS Batch", "parentfield": "instructors", "parent": batch.name},
		pluck="instructor",
		order_by="idx asc",
	)
	names = []
	for instructor in instructors:
		full_name = frappe.db.get_value("User", instructor, "full_name")
		if full_name:
			names.append(full_name)

	dates = None
	if batch.start_date and batch.end_date:
		dates = _("{0} to {1}").format(formatdate(batch.start_date, "d MMM yyyy"), formatdate(batch.end_date, "d MMM yyyy"))
	elif batch.start_date:
		dates = _("From {0}").format(formatdate(batch.start_date, "d MMM yyyy"))

	return {
		"name": batch.name,
		"title": batch.title or batch.name,
		"description": batch.description or "",
		"dates": dates,
		"instructors": names,
	}

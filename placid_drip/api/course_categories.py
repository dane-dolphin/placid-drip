"""The category options the course page's filter dropdown offers.

The dropdown used to be built client-side from whatever courses happened to be
on screen. `get_courses` returns 30 rows at a time ordered by `enrollments
desc`, so a freshly created category sat behind every popular course and never
made it into the first page - and `Courses.vue` additionally stopped refreshing
the list once it had been populated once. The net effect was a filter that could
only ever offer the categories that existed on the day the page was first
opened.

Reading the categories from the courses themselves - rather than from the
`LMS Category` list - keeps a category out of the dropdown until something is
actually filed under it, which is what stops the filter from offering options
that lead to an empty grid. It also sidesteps a permission problem: `LMS
Category` grants read to staff roles only, so students and guests cannot list it
directly.
"""

import frappe
from frappe.rate_limiter import rate_limit

from placid_drip.constants import RATE_LIMIT, RATE_LIMIT_WINDOW


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=RATE_LIMIT, seconds=RATE_LIMIT_WINDOW)
def get_course_categories():
	"""Distinct categories of the courses this user is allowed to see.

	Visibility is deliberately resolved through the same `_can_see_drafts` check
	the course list itself uses, so the dropdown never advertises a category that
	only exists on a draft the viewer cannot open.
	"""
	# Imported here rather than at module scope: `overrides.lms_utils` imports
	# `api.course_levels`, and a top-level import back into overrides would close
	# that loop.
	from placid_drip.overrides.lms_utils import _can_see_drafts

	filters = {"category": ["is", "set"]}
	if not _can_see_drafts(frappe.session.user):
		filters["published"] = 1

	rows = frappe.get_all(
		"LMS Course",
		filters=filters,
		fields=["category"],
		group_by="category",
		order_by="category asc",
	)

	return [row["category"] for row in rows if row.get("category")]

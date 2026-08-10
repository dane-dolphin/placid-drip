"""The level tiles the course page shows before it shows any courses.

Upstream `get_courses` already filters on any unknown key handed to it, so
drilling into a level needs no new endpoint - `{"level": "Level 1"}` works. What
does not exist upstream is the screen *before* that: the list of levels, ordered
for display, each with a count so a tile can say how much is behind it.

The Unassigned bucket is not cosmetic. `LMS Course.level` arrives as a Custom
Field on an existing catalogue, so every course starts out with a null level. A
level-first page that only listed courses *inside* a level would make the entire
current catalogue unreachable the moment it shipped, and would keep hiding any
course an author forgot to categorise. So null is a real bucket, surfaced to
everyone rather than only to staff, and it disappears on its own once it empties.
"""

import frappe
from frappe.rate_limiter import rate_limit

from placid_drip.constants import RATE_LIMIT, RATE_LIMIT_WINDOW

LEVEL_FIELDS = ["name", "level_name", "sequence", "description", "image"]

#: Sentinel the frontend sends back to drill into "courses with no level yet".
#: A literal empty string would be indistinguishable from "no level chosen".
UNASSIGNED = "__unassigned__"


def _sees_unpublished(user: str) -> bool:
	"""Staff count every course; everyone else counts only published ones.

	Matches what the viewer lands on after clicking a tile, so the number on the
	tile is not contradicted by the list behind it. Staff who then switch to the
	Unpublished tab will see a subset of their count - the tile deliberately
	reports the whole level rather than tracking the tab.
	"""
	if user == "Administrator":
		return True

	return bool(
		set(frappe.get_roles(user)) & {"System Manager", "Moderator", "Course Creator", "Batch Evaluator"}
	)


def _course_filters(user: str) -> dict:
	return {} if _sees_unpublished(user) else {"published": 1}


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=RATE_LIMIT, seconds=RATE_LIMIT_WINDOW)
def get_course_levels(include_empty: bool = False):
	"""Levels for the tile screen, in display order, each with a course count.

	Empty levels are dropped by default - a tile leading to nothing is a dead end
	for a learner. Staff editing the catalogue can pass `include_empty` to see a
	level they have created but not yet filled.
	"""
	if not frappe.get_meta("LMS Course").has_field("level"):
		# Patch has not run yet. Returning [] lets the page fall back to its flat
		# list rather than 500-ing on a half-migrated site.
		return []

	user = frappe.session.user
	include_empty = frappe.utils.sbool(include_empty)

	counts = _get_counts_by_level(user)

	levels = frappe.get_all(
		"Course Level",
		filters={"published": 1},
		fields=LEVEL_FIELDS,
		order_by="sequence asc, level_name asc",
	)

	out = []
	for level in levels:
		count = counts.get(level["name"], 0)
		if not count and not include_empty:
			continue
		level["course_count"] = count
		out.append(level)

	if not out:
		# No level has any courses in it yet. Returning [] keeps the course page on
		# its existing flat grid instead of replacing it with a picker of one.
		return []

	unassigned = counts.get(None, 0)
	if unassigned:
		out.append(
			{
				"name": UNASSIGNED,
				"level_name": frappe._("Other Courses"),
				"sequence": 9999,
				"description": frappe._("Courses that have not been assigned a level yet."),
				"image": None,
				"course_count": unassigned,
			}
		)

	return out


def _get_counts_by_level(user: str) -> dict:
	"""One grouped query rather than a count per level."""
	rows = frappe.get_all(
		"LMS Course",
		filters=_course_filters(user),
		fields=["level", "count(name) as course_count"],
		group_by="level",
		ignore_ifnull=True,
	)

	counts = {}
	for row in rows:
		# Frappe hands back "" for an empty Link column on some backends and None on
		# others; both mean "no level".
		key = row.get("level") or None
		counts[key] = counts.get(key, 0) + row["course_count"]

	return counts


def apply_level_filter(filters: dict) -> dict:
	"""Translate the UNASSIGNED sentinel into a real "is not set" filter.

	Called from the `get_courses` override so the sentinel never reaches
	`frappe.get_all`, where it would match a level literally named
	`__unassigned__` and silently return nothing.
	"""
	if not filters or "level" not in filters:
		return filters

	if filters["level"] == UNASSIGNED:
		filters["level"] = ["is", "not set"]

	return filters

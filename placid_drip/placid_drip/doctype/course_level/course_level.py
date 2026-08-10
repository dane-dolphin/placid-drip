"""A band of courses - the first thing a learner picks on the course page.

Kept as a doctype rather than a Select on LMS Course so a level is a thing with
an identity: it carries the image, blurb and ordering the level tiles render
from, and adding or reordering one is a Desk edit rather than a code change and
a migrate.

`sequence` rather than relying on `creation` because the display order is an
editorial decision (Level 1 before Level 2) that has nothing to do with the order
someone happened to type them in.
"""

import frappe
from frappe.model.document import Document


class CourseLevel(Document):
	def on_trash(self):
		"""Refuse to orphan courses.

		`LMS Course.level` is a Custom Field, and Frappe's link-integrity check
		covers it - but the default message points at a course name without saying
		why it blocks. Failing here lets us say what to do about it.
		"""
		linked = frappe.get_all(
			"LMS Course", filters={"level": self.name}, pluck="name", limit=5
		)
		if not linked:
			return

		count = frappe.db.count("LMS Course", {"level": self.name})
		frappe.throw(
			frappe._(
				"{0} course(s) are still on this level, including {1}. "
				"Move them to another level before deleting it."
			).format(count, ", ".join(frappe.bold(name) for name in linked))
		)

"""A course as seen from inside one batch - the data behind `/lms/batches/<batch>/courses/<course>`.

The stock course page describes a course to the whole site: every learner who
ever enrolled, public reviews, related courses to buy. A student who arrived
through a batch has none of those questions. They want to know that this is
their cohort's course, how far along they are, and where the button is that
starts the next class. This endpoint answers exactly that, and nothing wider:
the head-count is the batch's, not the site's.
"""

import frappe
from frappe import _
from lms.lms import utils as lms_utils

from placid_drip.access import resolve_user_batch_for_course
from placid_drip.batch_links import is_enrolled
from placid_drip.facilitator import can_manage_batch_course
from placid_drip.overrides.lms_utils import (
	_is_evaluator_for_course,
	_is_locked_for_user,
	_resolve_lesson_docname,
	_scope_enrollments_to_batch,
	_should_enforce_drip,
)


@frappe.whitelist()
def get_batch_course(batch: str, course: str):
	"""One course of one batch, for a member of that batch or someone who runs it."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please log in."), frappe.PermissionError)

	if not batch or not course:
		frappe.throw(_("A batch and a course are required."))

	courses = frappe.get_all(
		"Batch Course",
		filters={"parenttype": "LMS Batch", "parent": batch},
		pluck="course",
		order_by="idx asc",
	)

	can_manage = can_manage_batch_course(user, batch, course)
	is_student = is_enrolled(batch, user)

	# One refusal for "no such batch", "course is not in it" and "you are not in
	# it": a member of some other batch has no business learning which is which.
	if course not in courses or not (is_student or can_manage):
		frappe.throw(_("This course is not available to you in this batch."), frappe.PermissionError)

	details = lms_utils.get_course_details(course)
	_scope_enrollments_to_batch(batch, [details])

	batch_row = frappe.db.get_value("LMS Batch", batch, ["name", "title", "start_date", "end_date"], as_dict=True)
	position = courses.index(course)
	next_course = courses[position + 1] if position + 1 < len(courses) else None

	return {
		"batch": batch_row,
		"course": {
			"name": details.name,
			"title": details.title,
			"short_introduction": details.short_introduction,
			"description": details.description,
			"image": details.image,
			"lessons": details.lessons,
			"instructors": details.instructors,
		},
		"position": position + 1,
		"course_count": len(courses),
		"next_course": (
			{"name": next_course, "title": frappe.db.get_value("LMS Course", next_course, "title")}
			if next_course
			else None
		),
		# Batch members enrolled in this course - not the site-wide counter.
		"classmates": details.enrollments,
		"batch_size": frappe.db.count("LMS Batch Enrollment", {"batch": batch}),
		"is_student": is_student,
		"can_manage": can_manage,
		"progress": _progress(details),
		"resume": _resume_point(course, details),
	}


def _progress(details) -> int | None:
	"""The caller's own progress through the course, or None if not enrolled in it."""
	if not details.membership:
		return None
	return int(round(float(details.membership.progress or 0)))


def _resume_point(course: str, details) -> dict | None:
	"""Where the big button goes: the lesson the caller was last on, else the first.

	Carries the drip lock for that lesson, so the page can say "opens on ..."
	instead of sending someone into a locked lesson. None if the course has no
	lessons yet.
	"""
	started = bool(details.membership and details.membership.current_lesson)
	index = details.get("current_lesson") if started else "1-1"
	chapter, lesson = (int(part) for part in str(index).split("-", 1))

	lesson_name = _resolve_lesson_docname(course, chapter, lesson)
	if not lesson_name:
		return None

	locked, opens_at, reason = False, None, None
	if _should_enforce_drip() and not _is_evaluator_for_course(frappe.session.user, course):
		locked, opens_at, reason = _is_locked_for_user(course, lesson_name)

	return {
		"chapter": chapter,
		"lesson": lesson,
		"title": frappe.db.get_value("Course Lesson", lesson_name, "title"),
		"started": started,
		"locked": bool(locked),
		"opens_at": opens_at,
		"lock_reason": reason,
	}


@frappe.whitelist()
def get_my_batch_courses():
	"""The caller's batches, each with its courses - a student's whole catalogue.

	Students are not shown the site-wide course list: the courses that matter to
	them are the ones their batches run, in the order the facilitator arranged
	them. Each course carries the same fields the course card renders, with the
	head-count scoped to the batch.
	"""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please log in."), frappe.PermissionError)

	batch_names = frappe.get_all("LMS Batch Enrollment", filters={"member": user}, pluck="batch")
	if not batch_names:
		return []

	batches = frappe.get_all(
		"LMS Batch",
		filters={"name": ["in", batch_names]},
		fields=["name", "title", "start_date", "end_date"],
		order_by="start_date desc",
	)

	for batch in batches:
		course_names = frappe.get_all(
			"Batch Course",
			filters={"parenttype": "LMS Batch", "parent": batch.name},
			pluck="course",
			order_by="idx asc",
		)
		courses = [lms_utils.get_course_details(name) for name in course_names]
		batch.courses = _scope_enrollments_to_batch(batch.name, courses)

	return batches


@frappe.whitelist()
def get_batch_for_course(course: str):
	"""The batch through which the caller takes `course`, or None.

	Lets the public course page hand a student over to the batch's own page for
	that course instead of showing them the site-wide one.
	"""
	user = frappe.session.user
	if user == "Guest" or not course:
		return None

	return resolve_user_batch_for_course(user, course)

"""Keeping lesson and batch discussions inside the batch they belong to.

Upstream ties a lesson's "Community" thread to the lesson alone, so every learner
of a course - in every batch, past and present - reads and writes the same
thread. Here a lesson topic also records the batch it was started in
(`Discussion Topic.batch`, a Custom Field), and is shown only to that batch.

Who sees a topic:

* its author, always;
* staff (System Manager / Moderator), always;
* for a lesson topic: members and facilitators of the topic's batch, and the
  instructors of the lesson's course;
* for a batch's own discussion: members and facilitators of that batch;
* a lesson topic with no batch (started by someone who is in no batch for that
  course) is seen by staff, facilitators and course instructors only.

The same rule is enforced three ways, because there are three ways in: the two
LMS endpoints the pages call (overridden in `overrides.lms_utils`), and the
generic `frappe.client` API, which is covered by the `has_permission` and
`permission_query_conditions` hooks below. Replies inherit their topic's rule.
"""

import frappe
from frappe import _

from placid_drip.facilitator import get_facilitated_batch_names, get_instructed_course_names, is_staff

LESSON = "Course Lesson"
BATCH = "LMS Batch"
BATCH_FIELD = "batch"


def member_batches(user: str) -> list[str]:
	if not user or user == "Guest":
		return []
	return frappe.get_all("LMS Batch Enrollment", filters={"member": user}, pluck="batch")


def visible_batches(user: str) -> list[str]:
	"""Batches whose discussions `user` takes part in: as a member or as facilitator."""
	return list(set(member_batches(user)) | set(get_facilitated_batch_names(user)))


def batches_running(course: str) -> list[str]:
	return frappe.get_all(
		"Batch Course", filters={"parenttype": BATCH, "course": course}, pluck="parent", order_by="creation desc"
	)


def batch_for_new_topic(user: str, lesson: str) -> str | None:
	"""The batch a lesson topic started by `user` belongs to.

	A student's own batch for that course. For a facilitator, the batch they run
	that has the course - but only if there is exactly one, since nothing on the
	lesson page says which of several they mean.
	"""
	course = frappe.db.get_value(LESSON, lesson, "course")
	if not course:
		return None

	running = batches_running(course)

	mine = [b for b in running if b in set(member_batches(user))]
	if mine:
		return mine[0]

	facilitated = [b for b in running if b in set(get_facilitated_batch_names(user))]
	if len(facilitated) == 1:
		return facilitated[0]

	return None


def can_see_topic(topic, user: str | None = None) -> bool:
	"""`topic` is a Discussion Topic doc or a row with owner, reference_* and batch."""
	user = user or frappe.session.user
	if user == "Guest":
		return False

	if is_staff(user) or topic.get("owner") == user:
		return True

	doctype = topic.get("reference_doctype")
	docname = topic.get("reference_docname")

	if doctype == BATCH:
		return docname in visible_batches(user)

	if doctype == LESSON:
		batch = topic.get(BATCH_FIELD)
		if batch and batch in visible_batches(user):
			return True
		if frappe.db.get_value(LESSON, docname, "course") in get_instructed_course_names(user):
			return True
		return not batch and bool(get_facilitated_batch_names(user))

	return True


def get_topic_row(name: str):
	return frappe.db.get_value(
		"Discussion Topic",
		name,
		["name", "owner", "reference_doctype", "reference_docname", BATCH_FIELD],
		as_dict=True,
	)


def assert_can_see_topic(name: str) -> None:
	topic = get_topic_row(name)
	if not topic or not can_see_topic(topic):
		frappe.throw(_("This discussion is not available to you."), frappe.PermissionError)


# ---------------------------------------------------------------------------
# Document hooks
# ---------------------------------------------------------------------------


def set_topic_batch(doc, method=None):
	"""before_insert: stamp a lesson topic with its author's batch.

	Whatever the client sent is discarded for everyone but staff - the generic
	insert API would otherwise let a student post into another batch's thread.
	"""
	if doc.reference_doctype == BATCH:
		if not is_staff(frappe.session.user) and doc.reference_docname not in visible_batches(frappe.session.user):
			frappe.throw(_("You are not a member of this batch."), frappe.PermissionError)
		return

	if doc.reference_doctype != LESSON:
		return

	if is_staff(frappe.session.user) and doc.get(BATCH_FIELD):
		return

	doc.set(BATCH_FIELD, batch_for_new_topic(frappe.session.user, doc.reference_docname))


def topic_has_permission(doc, ptype=None, user=None):
	if doc.is_new():
		return True
	return can_see_topic(doc, user or frappe.session.user)


def reply_has_permission(doc, ptype=None, user=None):
	if not doc.get("topic"):
		return True
	topic = get_topic_row(doc.topic)
	return bool(topic) and can_see_topic(topic, user or frappe.session.user)


# ---------------------------------------------------------------------------
# List queries (frappe.client.get_list and friends)
# ---------------------------------------------------------------------------


def _in(values) -> str:
	return "(" + ", ".join(frappe.db.escape(v) for v in values) + ")" if values else "('')"


def _topic_condition(user: str, table: str = "`tabDiscussion Topic`") -> str:
	batches = _in(visible_batches(user))
	courses = _in(get_instructed_course_names(user))

	clauses = [
		f"{table}.owner = {frappe.db.escape(user)}",
		f"({table}.reference_doctype = 'LMS Batch' and {table}.reference_docname in {batches})",
		f"({table}.reference_doctype = 'Course Lesson' and {table}.`{BATCH_FIELD}` in {batches})",
		f"({table}.reference_doctype = 'Course Lesson' and {table}.reference_docname in "
		f"(select name from `tabCourse Lesson` where course in {courses}))",
		f"ifnull({table}.reference_doctype, '') not in ('LMS Batch', 'Course Lesson')",
	]
	if get_facilitated_batch_names(user):
		clauses.append(
			f"({table}.reference_doctype = 'Course Lesson' and ifnull({table}.`{BATCH_FIELD}`, '') = '')"
		)

	return "(" + " or ".join(clauses) + ")"


def topic_query_conditions(user=None):
	user = user or frappe.session.user
	if is_staff(user):
		return ""
	return _topic_condition(user)


def reply_query_conditions(user=None):
	user = user or frappe.session.user
	if is_staff(user):
		return ""
	return (
		"`tabDiscussion Reply`.topic in "
		f"(select t.name from `tabDiscussion Topic` t where {_topic_condition(user, 't')})"
	)

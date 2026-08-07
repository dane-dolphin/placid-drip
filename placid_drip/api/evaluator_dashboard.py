import frappe

from placid_drip.facilitator import (
	get_courses_for_batches,
	get_facilitated_batches,
)

COURSE_CARD_FIELDS = [
	"name",
	"title",
	"image",
	"card_gradient",
	"short_introduction",
	"enrollments",
	"lessons",
	"rating",
	"featured",
	"tags",
]


def _get_course_card_payloads(course_names: list[str]) -> dict[str, dict]:
	"""CourseCard-ready payloads for many courses in a fixed number of queries.

	The previous version issued three queries per course, which made the home page
	scale linearly with the number of courses a facilitator runs.
	"""
	if not course_names:
		return {}

	meta = frappe.get_meta("LMS Course")
	fields = [f for f in COURSE_CARD_FIELDS if f == "name" or meta.has_field(f)]

	courses = frappe.get_all("LMS Course", filters={"name": ["in", course_names]}, fields=fields)
	by_name = {c["name"]: c for c in courses}

	# One query for every instructor row across every course.
	instructor_rows = frappe.get_all(
		"Course Instructor",
		filters={
			"parenttype": "LMS Course",
			"parentfield": "instructors",
			"parent": ["in", course_names],
		},
		fields=["parent", "instructor", "idx"],
		order_by="parent asc, idx asc",
	)

	user_ids = {r["instructor"] for r in instructor_rows if r.get("instructor")}
	users_by_id = {}
	if user_ids:
		users_by_id = {
			u["name"]: u
			for u in frappe.get_all(
				"User",
				filters={"name": ["in", list(user_ids)]},
				fields=["name", "full_name", "user_image"],
			)
		}

	for course in by_name.values():
		course["instructors"] = []

	for row in instructor_rows:
		course = by_name.get(row["parent"])
		user = users_by_id.get(row.get("instructor"))
		if not course or not user:
			continue
		course["instructors"].append(
			{
				"name": user["name"],
				"full_name": user.get("full_name") or user["name"],
				"user_image": user.get("user_image"),
			}
		)

	# Courses that vanished between the two queries still need a usable placeholder.
	for name in course_names:
		by_name.setdefault(name, {"name": name, "title": name, "instructors": []})

	return by_name


@frappe.whitelist()
def get_evaluator_dashboard():
	"""Every batch the current user evaluates or instructs, plus every course in them.

	Returns the full lists - the caller decides how many to show. Previously this
	sliced to 4 batches / 8 courses server-side, so "See all" could not show more
	than the home page already did.
	"""
	user = frappe.session.user
	if user == "Guest":
		return {"batches": [], "courses": [], "counts": {"batches": 0, "courses": 0}}

	batches = get_facilitated_batches(user)
	batch_names = [b["name"] for b in batches]
	courses_by_batch = get_courses_for_batches(batch_names)

	# Flatten to a de-duplicated, order-preserving list of course names.
	course_names: list[str] = []
	seen: set[str] = set()
	for name in batch_names:
		for course in courses_by_batch.get(name, []):
			if course["name"] not in seen:
				seen.add(course["name"])
				course_names.append(course["name"])

	card_payloads = _get_course_card_payloads(course_names)

	for batch in batches:
		batch["courses"] = courses_by_batch.get(batch["name"], [])

	courses = [card_payloads[n] for n in course_names if n in card_payloads]

	return {
		"batches": batches,
		"courses": courses,
		"counts": {"batches": len(batches), "courses": len(courses)},
	}

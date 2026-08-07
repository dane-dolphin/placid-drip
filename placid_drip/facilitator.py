"""Shared resolution of "which batches does this user facilitate".

A user facilitates a batch if either:
  * they are the evaluator on one of the batch's courses (`Batch Course.evaluator`), or
  * they are listed as an instructor on the batch itself (`LMS Batch.instructors`).

Both the facilitator home page and the Batches list go through here so the two
never disagree about what "my batches" means.
"""

import frappe

# Everything BatchCard.vue actually reads, minus the values it computes itself.
BATCH_FIELDS = [
	"name",
	"title",
	"description",
	"start_date",
	"end_date",
	"start_time",
	"end_time",
	"timezone",
	"medium",
	"category",
	"seat_count",
	"paid_batch",
	"amount",
	"currency",
]


def is_staff(user: str) -> bool:
	return user == "Administrator" or bool(
		set(frappe.get_roles(user)) & {"System Manager", "Moderator"}
	)


def can_manage_batch_course(user: str, batch: str, course: str) -> bool:
	"""May this user manage content/scheduling for `course` inside `batch`?

	Staff always may. Otherwise the user qualifies three ways:
	  * evaluator on that Batch Course row,
	  * instructor on the batch,
	  * instructor on the course itself.

	The last two were previously missing, so an instructor could not lock the
	lessons of a course they teach.
	"""
	if not batch or not course:
		return False

	if is_staff(user):
		return True

	if frappe.db.exists(
		"Batch Course",
		{"parenttype": "LMS Batch", "parent": batch, "course": course, "evaluator": user},
	):
		return True

	if frappe.db.exists(
		"Course Instructor",
		{
			"parenttype": "LMS Batch",
			"parentfield": "instructors",
			"parent": batch,
			"instructor": user,
		},
	):
		return True

	return bool(
		frappe.db.exists(
			"Course Instructor",
			{
				"parenttype": "LMS Course",
				"parentfield": "instructors",
				"parent": course,
				"instructor": user,
			},
		)
	)


def get_instructed_course_names(user: str) -> list[str]:
	"""Courses the user is directly listed as an instructor on."""
	if not user or user == "Guest":
		return []

	return frappe.get_all(
		"Course Instructor",
		filters={
			"parenttype": "LMS Course",
			"parentfield": "instructors",
			"instructor": user,
		},
		pluck="parent",
	)


def get_facilitated_batch_names(user: str) -> list[str]:
	"""Batch names this user evaluates or instructs, most recently modified first."""
	if not user or user == "Guest":
		return []

	as_evaluator = frappe.get_all(
		"Batch Course",
		filters={"parenttype": "LMS Batch", "evaluator": user},
		pluck="parent",
	)

	as_instructor = frappe.get_all(
		"Course Instructor",
		filters={
			"parenttype": "LMS Batch",
			"parentfield": "instructors",
			"instructor": user,
		},
		pluck="parent",
	)

	names = set(as_evaluator) | set(as_instructor)
	if not names:
		return []

	# Re-query so the ordering is stable and any dangling child rows whose parent
	# batch was deleted are dropped.
	return frappe.get_all(
		"LMS Batch",
		filters={"name": ["in", list(names)]},
		order_by="modified desc",
		pluck="name",
	)


def get_facilitated_batches(user: str) -> list[dict]:
	"""Full batch rows for `get_facilitated_batch_names`, order preserved."""
	names = get_facilitated_batch_names(user)
	if not names:
		return []

	meta = frappe.get_meta("LMS Batch")
	fields = [f for f in BATCH_FIELDS if f == "name" or meta.has_field(f)]

	rows = frappe.get_all("LMS Batch", filters={"name": ["in", names]}, fields=fields)
	by_name = {r["name"]: r for r in rows}

	_attach_instructors(by_name)

	return [by_name[n] for n in names if n in by_name]


def _attach_instructors(batches_by_name: dict[str, dict]) -> None:
	"""Populate `instructors` on each batch - BatchCard renders avatars from it."""
	for batch in batches_by_name.values():
		batch["instructors"] = []

	if not batches_by_name:
		return

	rows = frappe.get_all(
		"Course Instructor",
		filters={
			"parenttype": "LMS Batch",
			"parentfield": "instructors",
			"parent": ["in", list(batches_by_name)],
		},
		fields=["parent", "instructor", "idx"],
		order_by="parent asc, idx asc",
	)

	user_ids = {r["instructor"] for r in rows if r.get("instructor")}
	if not user_ids:
		return

	users_by_id = {
		u["name"]: u
		for u in frappe.get_all(
			"User",
			filters={"name": ["in", list(user_ids)]},
			fields=["name", "full_name", "user_image"],
		)
	}

	for row in rows:
		batch = batches_by_name.get(row["parent"])
		user = users_by_id.get(row.get("instructor"))
		if not batch or not user:
			continue
		batch["instructors"].append(
			{
				"name": user["name"],
				"full_name": user.get("full_name") or user["name"],
				"user_image": user.get("user_image"),
			}
		)


def get_courses_for_batches(batch_names: list[str]) -> dict[str, list[dict]]:
	"""Map of batch name -> its courses, in the batch's own course order."""
	if not batch_names:
		return {}

	rows = frappe.get_all(
		"Batch Course",
		filters={"parenttype": "LMS Batch", "parent": ["in", batch_names]},
		fields=["parent", "course", "title", "idx"],
		order_by="parent asc, idx asc",
	)

	out: dict[str, list[dict]] = {name: [] for name in batch_names}
	for r in rows:
		if not r.get("course"):
			continue
		out.setdefault(r["parent"], []).append(
			{"name": r["course"], "title": r.get("title") or r["course"]}
		)
	return out

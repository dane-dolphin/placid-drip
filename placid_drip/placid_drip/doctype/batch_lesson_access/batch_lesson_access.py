import frappe
from frappe.model.document import Document

class BatchLessonAccess(Document):
    def autoname(self):
        # exactly ONE doc per (batch, course, lesson)
        self.name = f"{self.batch}::{self.course}::{self.lesson}"

    def validate(self):
        self._enforce_unique_lock()
        self._enforce_evaluator_scope()

    def _enforce_unique_lock(self):
        # uniqueness must match your autoname dimensions
        existing = frappe.db.exists(
            "Batch Lesson Access",
            {
                "batch": self.batch,
                "course": self.course,
                "lesson": self.lesson,
                "name": ["!=", self.name],
            },
        )
        if existing:
            frappe.throw(
                "Lock already exists for this batch + course + lesson.",
                frappe.ValidationError,
            )

    def _enforce_evaluator_scope(self):
        user = frappe.session.user

        # allow admins/system managers to bypass
        if user == "Administrator" or "System Manager" in frappe.get_roles(user):
            return

        # must have Batch Evaluator role
        if "Batch Evaluator" not in frappe.get_roles(user):
            frappe.throw("Only Batch Evaluators can create lesson locks.", frappe.PermissionError)

        if not (self.batch and self.course and self.lesson):
            frappe.throw("Batch, Course, and Lesson are required.", frappe.ValidationError)

        # evaluator must be assigned for that course in that batch
        allowed = frappe.db.exists(
            "Batch Course",
            {
                "parenttype": "LMS Batch",
                "parent": self.batch,
                "course": self.course,
                "evaluator": user,
            },
        )
        if not allowed:
            frappe.throw(
                "You can only create locks for batches/courses you evaluate.",
                frappe.PermissionError,
            )
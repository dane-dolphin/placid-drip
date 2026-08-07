import frappe
from frappe.model.document import Document

from placid_drip.facilitator import can_manage_batch_course

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
        """Restrict locks to the batch/course the user actually facilitates.

        Previously this required the Batch Evaluator role specifically and the
        per-course evaluator assignment, which locked out both Moderators and
        instructors. Instructors are expected to be able to lock the lessons of a
        course they teach.
        """
        user = frappe.session.user

        if not (self.batch and self.course and self.lesson):
            frappe.throw("Batch, Course, and Lesson are required.", frappe.ValidationError)

        if not can_manage_batch_course(user, self.batch, self.course):
            frappe.throw(
                "You can only create locks for batches/courses you evaluate or instruct.",
                frappe.PermissionError,
            )
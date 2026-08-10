"""The org chart people belong to: dioceses containing parishes.

Deliberately one self-referencing tree rather than a `Diocese` and a `Parish`
doctype. Today the shape is exactly two deep, but "diocese > parish" is a naming
convention, not a constraint the data model needs to know about - a deanery or a
second campus can be slotted in later by adding an `org_type` option, with no new
doctype and no migration of the link field on User.

This is *membership*, not biography. It answers "who does this person belong to
at Placid", which is a different question from the `college` field LMS already
ships on User (where they studied). The two are intentionally not merged.

Being a nested set, `lft`/`rgt` make the roll-up query - "everyone anywhere under
this diocese" - a single indexed range scan rather than a chain of joins that
grows a term every time the hierarchy gets deeper.
"""

import frappe
from frappe import _
from frappe.utils.nestedset import NestedSet


class Organization(NestedSet):
	nsm_parent_field = "parent_organization"

	def validate(self):
		self.validate_not_own_parent()
		self.validate_parent_is_group()

	def validate_not_own_parent(self):
		if self.parent_organization and self.parent_organization == self.name:
			frappe.throw(_("An organization cannot be its own parent."))

	def validate_parent_is_group(self):
		"""Only group nodes may hold children.

		NestedSet's own `validate_ledger` catches this from the other direction
		(un-ticking Is Group on a node that already has children). This catches it
		at the point the child is created, where the admin can actually act on it -
		the error names the parent they need to fix.
		"""
		if not self.parent_organization:
			return

		if not frappe.db.get_value("Organization", self.parent_organization, "is_group"):
			frappe.throw(
				_("{0} cannot hold child organizations. Tick <b>Is Group</b> on it first.").format(
					frappe.bold(self.parent_organization)
				)
			)


def get_descendants(organization: str, include_self: bool = True) -> list[str]:
	"""Every organization at or under `organization`, via one lft/rgt range scan.

	The entry point for future roll-ups ("all students in this diocese"). Kept as
	a module function rather than a method so callers do not have to load the doc
	just to ask about its subtree.
	"""
	if not organization:
		return []

	bounds = frappe.db.get_value("Organization", organization, ["lft", "rgt"], as_dict=True)
	if not bounds:
		return []

	names = frappe.get_all(
		"Organization",
		filters={"lft": [">=", bounds.lft], "rgt": ["<=", bounds.rgt]},
		order_by="lft asc",
		pluck="name",
	)

	if not include_self:
		names = [n for n in names if n != organization]

	return names

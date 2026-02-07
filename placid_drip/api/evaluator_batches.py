import frappe
from frappe.utils import getdate

def get_batch_details(batch_name: str):
    return frappe.get_value(
        "LMS Batch",
        batch_name,
        [
            "name",
            "title",
            "description",
            "start_date",
            "end_date",
            "start_time",
            "end_time",
            "timezone",
        ],
        as_dict=True,
    )

@frappe.whitelist()
def get_my_evaluator_batches():
    user = frappe.session.user
    if user == "Guest":
        return []

    roles = frappe.get_roles(user)
    if user == "Administrator" or "System Manager" in roles or "Moderator" in roles:
        rows = frappe.get_all("LMS Batch", fields=["name"], order_by="modified desc", limit_page_length=200)
        return [get_batch_details(r["name"]) for r in rows if get_batch_details(r["name"])]

    # ✅ pull from Batch Course child table
    BatchCourse = frappe.qb.DocType("Batch Course")

    results = (
        frappe.qb.from_(BatchCourse)
        .select(BatchCourse.parent)                 # parent = LMS Batch name
        .where(BatchCourse.parenttype == "LMS Batch")
        .where(BatchCourse.evaluator == user)
        .groupby(BatchCourse.parent)
        .limit(200)
    ).run(as_dict=True)

    out = []
    for row in results:
        batch_name = row["parent"]
        d = get_batch_details(batch_name)
        if d:
            out.append(d)
    return out
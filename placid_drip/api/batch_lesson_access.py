import frappe

@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_evaluator_batches(doctype, txt, searchfield, start, page_len, filters=None):
    user = frappe.session.user
    roles = frappe.get_roles(user)

    # bypass for admins
    if user == "Administrator" or "System Manager" in roles or "Moderator" in roles:
        return frappe.db.sql("""
            select name, title
            from `tabLMS Batch`
            where (name like %(txt)s or title like %(txt)s)
            order by modified desc
            limit %(start)s, %(page_len)s
        """, {"txt": f"%{txt}%", "start": start, "page_len": page_len})

    # evaluator-only batches
    return frappe.db.sql("""
        select b.name, b.title
        from `tabLMS Batch` b
        join `tabBatch Course` bc on bc.parent = b.name and bc.parenttype='LMS Batch'
        where bc.evaluator=%(user)s
          and (b.name like %(txt)s or b.title like %(txt)s)
        group by b.name, b.title
        order by b.modified desc
        limit %(start)s, %(page_len)s
    """, {"user": user, "txt": f"%{txt}%", "start": start, "page_len": page_len})


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_evaluator_courses(doctype, txt, searchfield, start, page_len, filters=None):
    user = frappe.session.user
    roles = frappe.get_roles(user)
    batch = (filters or {}).get("batch")

    if not batch:
        return []

    # Admin/moderator/system manager: show ALL courses in that batch
    if user == "Administrator" or "System Manager" in roles or "Moderator" in roles:
        return frappe.db.sql(
            """
            SELECT DISTINCT
                c.name,
                c.title
            FROM `tabBatch Course` bc
            JOIN `tabLMS Course` c ON c.name = bc.course
            WHERE
                bc.parenttype='LMS Batch'
                AND bc.parent=%(batch)s
                AND (c.name LIKE %(txt)s OR c.title LIKE %(txt)s)
            ORDER BY c.modified DESC
            LIMIT %(start)s, %(page_len)s
            """,
            {
                "batch": batch,
                "txt": f"%{txt}%",
                "start": start,
                "page_len": page_len,
            },
        )

    # Evaluator: only courses they evaluate in that batch
    return frappe.db.sql(
        """
        SELECT DISTINCT
            c.name,
            c.title
        FROM `tabBatch Course` bc
        JOIN `tabLMS Course` c ON c.name = bc.course
        WHERE
            bc.parenttype='LMS Batch'
            AND bc.parent=%(batch)s
            AND bc.evaluator=%(user)s
            AND (c.name LIKE %(txt)s OR c.title LIKE %(txt)s)
        ORDER BY c.modified DESC
        LIMIT %(start)s, %(page_len)s
        """,
        {
            "batch": batch,
            "user": user,
            "txt": f"%{txt}%",
            "start": start,
            "page_len": page_len,
        },
    )
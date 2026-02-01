import frappe

def set_home_to_lms():
    """
    Ensure the website home page is /lms (route: 'lms') so '/' doesn't send users to /login.
    This is tracked in code and applied on install/migrate.
    """
    frappe.db.set_single_value("Website Settings", "home_page", "lms")
    frappe.clear_cache()
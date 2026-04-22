import frappe

no_cache = 1
login_required = 1


def get_context(context):
    if frappe.session.user == "Guest":
        frappe.throw(frappe._("You must be logged in to access this page."), frappe.PermissionError)

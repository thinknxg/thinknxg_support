"""1.16: website sources that already exist keep reading the whole site (new ones stay under their start address)."""
import frappe


def execute():
    if frappe.db.has_column("Support Knowledge Website", "stay_under_start"):
        site = frappe.qb.DocType("Support Knowledge Website")
        frappe.qb.update(site).set(site.stay_under_start, 0).run()

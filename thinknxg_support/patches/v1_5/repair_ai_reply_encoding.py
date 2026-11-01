"""1.5.1: repair assistant replies saved before the streaming fix, where UTF-8 text was read as ISO-8859-1
("Iâ€™m" instead of "I’m"). Only AI and bot messages that clearly show the pattern are changed."""
import re

import frappe

MOJIBAKE = re.compile("[\u00c2-\u00f4][\u0080-\u00bf]")


def repair(text: str) -> str | None:
    if not text or not MOJIBAKE.search(text):
        return None
    try:
        fixed = text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None  # mixed text that is not a clean round trip: leave it alone
    return fixed if fixed != text else None


def execute():
    if not frappe.db.exists("DocType", "Support Portal Message"):
        return
    fixed = 0
    for m in frappe.get_all("Support Portal Message", filters={"sender_type": ["in", ["AI", "Bot"]]},
                            fields=["name", "content"], limit=200000):
        new = repair(m.content)
        if new:
            frappe.db.set_value("Support Portal Message", m.name, "content", new, update_modified=False)
            fixed += 1
    if fixed:
        print(f"thinkNXG Support: repaired the text of {fixed} assistant messages")

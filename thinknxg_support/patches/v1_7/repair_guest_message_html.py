"""1.7.1: visitors' chat messages saved with visible tags ("<p>When will you be available?</p>") because the widget's
HTML was escaped as text. Turn them back into the message the visitor typed."""
import frappe


def execute():
    from thinknxg_support.integrations.conversations import _text_to_html
    from thinknxg_support.integrations.live_chat import guest_text

    if not frappe.db.exists("DocType", "Support Portal Message"):
        return
    fixed = 0
    for m in frappe.get_all("Support Portal Message",
                            filters={"direction": "Inbound", "content": ["like", "%&lt;p&gt;%"]},
                            fields=["name", "content"], limit=200000):
        text = guest_text(guest_text(m.content))  # outer <p> from saving, then the widget's escaped <p>
        new = _text_to_html(text)
        if new and new != m.content:
            frappe.db.set_value("Support Portal Message", m.name, "content", new, update_modified=False)
            fixed += 1
    if fixed:
        print(f"thinkNXG Support: repaired {fixed} visitor chat messages")

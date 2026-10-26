"""thinkNXG Support portal API, version 1.

Logical routes map to Frappe whitelisted methods, e.g.
GET /api/v1/portal/tickets  ->  GET /api/method/thinknxg_support.api.v1.tickets.list_tickets
Every method resolves the caller with security.get_portal_user() and validates any
client-supplied organisation / document identifier before touching data.
"""

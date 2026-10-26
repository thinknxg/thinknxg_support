import frappe
from frappe import _


class IntegrationUnavailable(frappe.ValidationError):
    """Raised when an optional integration (Helpdesk / Raven) is missing or disabled."""

    http_status_code = 503

    def __init__(self, integration: str, detail: str | None = None):
        self.integration = integration
        msg = _("{0} is not available on this site right now.").format(integration)
        if detail:
            msg = f"{msg} {detail}"
        super().__init__(msg)

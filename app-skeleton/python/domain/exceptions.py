class ReconciliationError(Exception):
    """Base class for exceptions in this module."""
    pass

class MisfiledInvoiceError(ReconciliationError):
    """Raised when an invoice's amounts and payer match a different study than its stamped study_id."""
    def __init__(self, invoice_id: str, stamped_study: str, matched_study: str):
        self.invoice_id = invoice_id
        self.stamped_study = stamped_study
        self.matched_study = matched_study
        self.message = f"MISFILED Invoice {invoice_id} stamped with study {stamped_study} but amounts/payer match study {matched_study}"
        super().__init__(self.message)

class UnresolvedStudyError(ReconciliationError):
    """Raised when an invoice cannot be routed to any known study."""
    def __init__(self, invoice_id: str):
        self.invoice_id = invoice_id
        self.message = f"Cannot resolve study for invoice {invoice_id}. Manual Review required."
        super().__init__(self.message)

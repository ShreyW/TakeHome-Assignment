from dataclasses import dataclass
from typing import Optional
from utils.financial import to_cents, from_cents

@dataclass
class VisitLog:
    study_key: str
    subject_id: str
    visit_name: str
    source_system: str
    activity_id: str
    status: str
    date: Optional[str] = None

@dataclass
class InvoiceLineItem:
    description: str
    amount_cents: int

    @classmethod
    def from_dict(cls, d: dict):
        return cls(
            description=d.get("description", ""),
            amount_cents=to_cents(d.get("amount", 0))
        )
        
    def to_dict(self):
        return {
            "description": self.description,
            "amount": from_cents(self.amount_cents)
        }

@dataclass
class Invoice:
    invoice_id: str
    study_id: str
    study_key: Optional[str]
    payer: str
    total_amount_cents: int
    line_items: list[InvoiceLineItem]
    subject_id: Optional[str]
    service_date: Optional[str]
    invoice_date: Optional[str]

    @classmethod
    def from_dict(cls, d: dict):
        lines = [InvoiceLineItem.from_dict(l) for l in d.get("line_items", [])]
        return cls(
            invoice_id=d.get("invoice_id", ""),
            study_id=d.get("study_id", ""),
            study_key=d.get("study_key"),
            payer=d.get("payer", ""),
            total_amount_cents=to_cents(d.get("total_amount", 0)),
            line_items=lines,
            subject_id=d.get("subject_id"),
            service_date=d.get("service_date"),
            invoice_date=d.get("invoice_date")
        )

    def to_dict(self):
        return {
            "type": "Invoice",
            "invoice_id": self.invoice_id,
            "study_id": self.study_id,
            "study_key": self.study_key,
            "payer": self.payer,
            "total_amount": from_cents(self.total_amount_cents),
            "line_items": [l.to_dict() for l in self.line_items],
            "subject_id": self.subject_id,
            "service_date": self.service_date,
            "invoice_date": self.invoice_date
        }

@dataclass
class Deposit:
    transaction_id: str
    amount_cents: int
    date: str
    name: str

    @classmethod
    def from_dict(cls, d: dict):
        return cls(
            transaction_id=d.get("transaction_id", ""),
            amount_cents=to_cents(d.get("amount", 0)),
            date=d.get("date", ""),
            name=d.get("name", "")
        )

    def to_dict(self):
        return {
            "transaction_id": self.transaction_id,
            "amount": from_cents(self.amount_cents),
            "date": self.date,
            "name": self.name
        }

@dataclass
class RemittanceLineItem:
    invoice_id: str
    amount_paid_cents: int
    gross_amount_cents: int

    @classmethod
    def from_dict(cls, d: dict):
        return cls(
            invoice_id=d.get("invoice_id", ""),
            amount_paid_cents=to_cents(d.get("amount_paid", 0)),
            gross_amount_cents=to_cents(d.get("gross_amount", d.get("amount_paid", 0)))
        )

    def to_dict(self):
        return {
            "invoice_id": self.invoice_id,
            "amount_paid": from_cents(self.amount_paid_cents),
            "gross_amount": from_cents(self.gross_amount_cents)
        }

@dataclass
class Remittance:
    remittance_id: str
    payment_date: str
    payor: str
    total_paid_cents: int
    lines: list[RemittanceLineItem]

    @classmethod
    def from_dict(cls, d: dict):
        lines = [RemittanceLineItem.from_dict(l) for l in d.get("lines", [])]
        return cls(
            remittance_id=d.get("remittance_id", ""),
            payment_date=d.get("date") or d.get("payment_date") or "",
            payor=d.get("payor", ""),
            total_paid_cents=to_cents(d.get("total_paid") or d.get("amount") or 0),
            lines=lines
        )

    def to_dict(self):
        return {
            "type": "Remittance",
            "remittance_id": self.remittance_id,
            "payment_date": self.payment_date,
            "payor": self.payor,
            "total_paid": from_cents(self.total_paid_cents),
            "lines": [l.to_dict() for l in self.lines]
        }

@dataclass
class Comm:
    study_key: Optional[str]
    date: str
    content_summary: str
    status_update: str
    mentions_invoices: list[str]

    @classmethod
    def from_dict(cls, d: dict):
        return cls(
            study_key=d.get("study_key"),
            date=d.get("date", ""),
            content_summary=d.get("content_summary", ""),
            status_update=d.get("status_update", ""),
            mentions_invoices=d.get("mentions_invoices") if isinstance(d.get("mentions_invoices"), list) else []
        )

    def to_dict(self):
        return {
            "type": "Comm",
            "study_key": self.study_key,
            "date": self.date,
            "content_summary": self.content_summary,
            "status_update": self.status_update,
            "mentions_invoices": self.mentions_invoices
        }

@dataclass
class BudgetLine:
    visit_name: str
    amount_cents: int
    is_autopaid: bool

    @classmethod
    def from_dict(cls, d: dict):
        return cls(
            visit_name=d.get("visit_name", ""),
            amount_cents=to_cents(d.get("amount", 0)),
            is_autopaid=d.get("is_autopaid", False)
        )

    def to_dict(self):
        return {
            "visit_name": self.visit_name,
            "amount": from_cents(self.amount_cents),
            "is_autopaid": self.is_autopaid
        }

@dataclass
class SiteFee:
    name: str
    amount_cents: int

    @classmethod
    def from_dict(cls, d: dict):
        return cls(
            name=d.get("name", ""),
            amount_cents=to_cents(d.get("amount", 0))
        )

    def to_dict(self):
        return {
            "name": self.name,
            "amount": from_cents(self.amount_cents)
        }

@dataclass
class StudyMeta:
    study_id: str
    site_id: Optional[str]
    investigator: Optional[str]
    sponsor: str
    keywords: list[str]
    holdback: float
    overhead: float
    budget: list[BudgetLine]
    site_fees: list[SiteFee]
    effective_date: str
    autopayer_system: Optional[str]
    net_days: int

    def to_dict(self):
        return {
            "study_id": self.study_id,
            "site_id": self.site_id,
            "investigator": self.investigator,
            "sponsor": self.sponsor,
            "keywords": self.keywords,
            "holdback_percent": self.holdback * 100.0,
            "overhead_percent": self.overhead,
            "budget": [b.to_dict() for b in self.budget],
            "site_fees": [sf.to_dict() for sf in self.site_fees],
            "effective_date": self.effective_date,
            "autopayer_system": self.autopayer_system,
            "net_days": self.net_days
        }

# Match Results

@dataclass
class UnpaidItem:
    ref_type: str
    ref_id: str
    amount_expected: float
    age_days: Optional[int]
    reason: str
    evidence: str
    confidence: str

    def to_dict(self):
        return {
            "ref_type": self.ref_type,
            "ref_id": self.ref_id,
            "amount_expected": self.amount_expected,
            "age_days": self.age_days,
            "reason": self.reason,
            "evidence": self.evidence,
            "confidence": self.confidence,
        }

@dataclass
class InvoicePaymentMatch:
    invoice_id: str
    payment_ids: list[str]
    invoice_amount: float
    amount_settled: float
    status: str
    notes: str

    def to_dict(self):
        return {
            "invoice_id": self.invoice_id,
            "payment_ids": self.payment_ids,
            "invoice_amount": self.invoice_amount,
            "amount_settled": self.amount_settled,
            "status": self.status,
            "notes": self.notes,
        }

@dataclass
class MatchedDeposit:
    transaction_id: str
    study_key: str
    amount_cents: int
    date: str
    remittance_ref: Optional[str]
    remittance_id: Optional[str]
    remittance_lines: list[RemittanceLineItem]

@dataclass
class InvoiceMatchResult:
    billed_total_cents: int
    outstanding_ar_cents: int
    holdback_withheld_cents: int
    unpaid: list[UnpaidItem]
    invoice_to_payment: list[InvoicePaymentMatch]
    payment_day_pairs: list[tuple[str, str]]

@dataclass
class AutopayMatchResult:
    billed_total_cents: int
    unpaid: list[UnpaidItem]
    exceptions_count: int
    matched_deposits: list[str]

@dataclass
class UnbilledResult:
    unbilled: list[dict]
    unbilled_estimate: float

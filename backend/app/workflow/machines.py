"""All workflow state machines and their allowed transitions, in one place (spec section 8)."""

from app.workflow.engine import Machine


class PR:
    DRAFT = "DRAFT"
    PENDING = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ORDERED = "ORDERED"
    CANCELLED = "CANCELLED"
    OPEN = (DRAFT, PENDING, APPROVED)


class PO:
    CREATED = "CREATED"
    SENT = "SENT"
    CONFIRMED = "CONFIRMED"
    DISPATCHED = "DISPATCHED"
    PARTIAL = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    INVOICED = "INVOICED"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED_BY_SUPPLIER"
    CANCELLED = "CANCELLED"
    OPEN = (CREATED, SENT, CONFIRMED, DISPATCHED, PARTIAL)  # goods still expected
    RECEIVABLE = (SENT, CONFIRMED, DISPATCHED, PARTIAL)


class TR:
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DISPATCHED = "DISPATCHED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class RET:
    DRAFT = "DRAFT"
    PENDING = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DISPATCHED = "DISPATCHED"
    CREDIT = "CREDIT_RECEIVED"
    CANCELLED = "CANCELLED"


class RFQ:
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    AWARDED = "AWARDED"
    CANCELLED = "CANCELLED"


purchase_request = Machine(
    "purchase_request",
    {
        PR.DRAFT: {PR.PENDING, PR.CANCELLED},
        PR.PENDING: {PR.APPROVED, PR.REJECTED, PR.CANCELLED},
        PR.APPROVED: {PR.ORDERED, PR.CANCELLED},
    },
    terminal={PR.REJECTED, PR.ORDERED, PR.CANCELLED},
)

purchase_order = Machine(
    "purchase_order",
    {
        PO.CREATED: {PO.SENT, PO.CANCELLED},
        PO.SENT: {PO.CONFIRMED, PO.REJECTED, PO.PARTIAL, PO.RECEIVED, PO.CANCELLED},
        PO.CONFIRMED: {PO.DISPATCHED, PO.PARTIAL, PO.RECEIVED, PO.CANCELLED},
        PO.DISPATCHED: {PO.PARTIAL, PO.RECEIVED},
        PO.PARTIAL: {PO.RECEIVED},
        PO.RECEIVED: {PO.INVOICED},
        PO.INVOICED: {PO.CLOSED},
        PO.REJECTED: {PO.CANCELLED},
    },
    terminal={PO.CLOSED, PO.CANCELLED},
)

stock_transfer = Machine(
    "stock_transfer",
    {
        TR.REQUESTED: {TR.APPROVED, TR.CANCELLED},
        TR.APPROVED: {TR.DISPATCHED, TR.CANCELLED},
        TR.DISPATCHED: {TR.RECEIVED},
    },
    terminal={TR.RECEIVED, TR.CANCELLED},
)

supplier_return = Machine(
    "supplier_return",
    {
        RET.DRAFT: {RET.PENDING, RET.CANCELLED},
        RET.PENDING: {RET.APPROVED, RET.REJECTED},
        RET.APPROVED: {RET.DISPATCHED, RET.CANCELLED},
        RET.DISPATCHED: {RET.CREDIT},
    },
    terminal={RET.REJECTED, RET.CREDIT, RET.CANCELLED},
)

rfq = Machine(
    "rfq",
    {RFQ.OPEN: {RFQ.CLOSED, RFQ.AWARDED, RFQ.CANCELLED}, RFQ.CLOSED: {RFQ.AWARDED}},
    terminal={RFQ.AWARDED, RFQ.CANCELLED},
)

ALL_MACHINES = [purchase_request, purchase_order, stock_transfer, supplier_return, rfq]

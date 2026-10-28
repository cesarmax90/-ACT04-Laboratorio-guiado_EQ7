"""Dominio TechStore U4: Value Objects, Aggregate Root, máquina de estados y eventos."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

MAX_UNITS = 20
CENT = Decimal("0.01")


# ---------- Excepciones de dominio ----------
class DomainException(Exception):
    pass


class InvalidOrderData(DomainException):
    """Dato inválido (monto, artículo, guía, motivo, pedido vacío, cliente inactivo)."""


class InvalidOrderTransition(DomainException):
    """Operación no permitida desde el estado actual."""


class OrderItemLimitExceeded(DomainException):
    """La suma de unidades del pedido superaría el máximo."""


# ---------- Value Objects ----------
@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str = "MXN"

    def __post_init__(self):
        if not isinstance(self.amount, Decimal):
            raise InvalidOrderData("El monto debe ser Decimal, no float ni int")
        if not self.amount.is_finite() or self.amount < 0:
            raise InvalidOrderData("Monto inválido")

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise InvalidOrderData("Monedas distintas")
        return Money(self.amount + other.amount, self.currency)

    def rounded(self) -> "Money":
        """Devuelve un Money nuevo redondeado a centavos."""
        return Money(self.amount.quantize(CENT, rounding=ROUND_HALF_UP), self.currency)


@dataclass(frozen=True)
class Customer:
    id: str
    is_vip: bool = False
    active: bool = True


@dataclass(frozen=True)
class OrderItem:
    sku: str
    quantity: int
    unit_price: Money

    def __post_init__(self):
        if not self.sku.strip():
            raise InvalidOrderData("Artículo inválido: SKU vacío")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int) or self.quantity <= 0:
            raise InvalidOrderData("Artículo inválido: la cantidad debe ser un entero > 0")

    @property
    def subtotal(self) -> Money:
        return Money(self.unit_price.amount * self.quantity, self.unit_price.currency)


# ---------- Estados y eventos ----------
class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    RETURNED = "RETURNED"


@dataclass(frozen=True)
class DomainEvent:
    name: str
    order_id: str
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    detail: str = ""


# ---------- Aggregate Root ----------
@dataclass
class Order:
    customer: Customer
    id: str
    has_promotion: bool = False
    status: OrderStatus = OrderStatus.DRAFT
    items: list[OrderItem] = field(default_factory=list)
    events: list[DomainEvent] = field(default_factory=list)
    tracking_number: str | None = None
    cancel_reason: str | None = None

    # --- consultas ---
    @property
    def units(self) -> int:
        """Suma de unidades (no cuenta renglones)."""
        return sum(item.quantity for item in self.items)

    @property
    def total(self) -> Money:
        amount = sum((x.subtotal.amount for x in self.items), Decimal("0"))
        return Money(amount.quantize(CENT, rounding=ROUND_HALF_UP))

    # --- comandos ---
    def add_item(self, item: OrderItem) -> None:
        if self.status != OrderStatus.DRAFT:
            raise InvalidOrderTransition("Solo DRAFT admite artículos")
        if self.units + item.quantity > MAX_UNITS:
            raise OrderItemLimitExceeded(f"Máximo {MAX_UNITS} unidades")
        if item.unit_price.currency != "MXN":
            raise InvalidOrderData("Solo MXN")
        self.items.append(item)

    def _require_status(self, expected: OrderStatus, message: str) -> None:
        if self.status != expected:
            raise InvalidOrderTransition(message)

    def _record(self, name: str, detail: str = "") -> None:
        self.events.append(DomainEvent(name, self.id, detail=detail))

    # Regla común: validar primero, cambiar status después, registrar evento al final.
    def confirm(self) -> None:
        self._require_status(OrderStatus.DRAFT, "Solo DRAFT puede confirmarse")
        if not self.items or not self.customer.active:
            raise InvalidOrderData("Requiere artículos y cliente activo")
        self.status = OrderStatus.CONFIRMED
        self._record("OrderConfirmed")

    def ship(self, tracking_number: str) -> None:
        self._require_status(OrderStatus.CONFIRMED, "Solo CONFIRMED puede enviarse")
        if not isinstance(tracking_number, str) or not tracking_number.strip():
            raise InvalidOrderData("El envío requiere número de guía")
        self.status = OrderStatus.SHIPPED
        self.tracking_number = tracking_number.strip()
        self._record("OrderShipped", self.tracking_number)

    def cancel(self, reason: str) -> None:
        self._require_status(OrderStatus.CONFIRMED, "Solo CONFIRMED puede cancelarse")
        if not isinstance(reason, str) or not reason.strip():
            raise InvalidOrderData("La cancelación requiere motivo")
        self.status = OrderStatus.CANCELLED
        self.cancel_reason = reason.strip()
        self._record("OrderCancelled", self.cancel_reason)

    def deliver(self) -> None:
        self._require_status(OrderStatus.SHIPPED, "Solo SHIPPED puede entregarse")
        self.status = OrderStatus.DELIVERED
        self._record("OrderDelivered")

    def return_order(self) -> None:
        self._require_status(OrderStatus.SHIPPED, "Solo SHIPPED puede devolverse")
        self.status = OrderStatus.RETURNED
        self._record("OrderReturned")

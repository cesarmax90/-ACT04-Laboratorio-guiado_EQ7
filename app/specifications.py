"""Specification Pattern: reglas booleanas combinables con & (AND), | (OR) y ~ (NOT).

Una Specification solo responde True/False; nunca modifica el pedido.
"""
from decimal import Decimal

from app.domain import Money, Order


class Specification:
    def is_satisfied_by(self, order: Order) -> bool:
        raise NotImplementedError

    def __and__(self, other: "Specification") -> "Specification":
        return AndSpec(self, other)

    def __or__(self, other: "Specification") -> "Specification":
        return OrSpec(self, other)

    def __invert__(self) -> "Specification":
        return NotSpec(self)


class AndSpec(Specification):
    def __init__(self, left: Specification, right: Specification):
        self.left, self.right = left, right

    def is_satisfied_by(self, order: Order) -> bool:
        return self.left.is_satisfied_by(order) and self.right.is_satisfied_by(order)


class OrSpec(Specification):
    def __init__(self, left: Specification, right: Specification):
        self.left, self.right = left, right

    def is_satisfied_by(self, order: Order) -> bool:
        return self.left.is_satisfied_by(order) or self.right.is_satisfied_by(order)


class NotSpec(Specification):
    def __init__(self, inner: Specification):
        self.inner = inner

    def is_satisfied_by(self, order: Order) -> bool:
        return not self.inner.is_satisfied_by(order)


# ---------- Specifications concretas ----------
class MinimumAmountSpec(Specification):
    """Total ESTRICTAMENTE mayor al umbral (>, no >=)."""

    def __init__(self, threshold: Decimal):
        self.threshold = threshold

    def is_satisfied_by(self, order: Order) -> bool:
        return order.total.amount > self.threshold


class VIPCustomerSpec(Specification):
    def is_satisfied_by(self, order: Order) -> bool:
        return order.customer.is_vip


class MinimumUnitsSpec(Specification):
    """Al menos N unidades (>=)."""

    def __init__(self, minimum: int):
        self.minimum = minimum

    def is_satisfied_by(self, order: Order) -> bool:
        return order.units >= self.minimum


class ActivePromotionSpec(Specification):
    def is_satisfied_by(self, order: Order) -> bool:
        return order.has_promotion


class ActiveCustomerSpec(Specification):
    """Quinta Specification: el cliente puede confirmar pedidos."""

    def is_satisfied_by(self, order: Order) -> bool:
        return order.customer.active


# ---------- Reglas de descuento ----------
TEN_PERCENT = Decimal("0.10")
FIVE_PERCENT = Decimal("0.05")

ten_percent = (
    MinimumAmountSpec(Decimal("500"))
    & VIPCustomerSpec()
    & MinimumUnitsSpec(4)
    & ~ActivePromotionSpec()
)
five_percent = MinimumAmountSpec(Decimal("5000")) & ~ActivePromotionSpec()
any_discount = ten_percent | five_percent


def discount_rate(order: Order) -> Decimal:
    """10 % tiene prioridad sobre 5 % cuando ambas reglas se cumplen."""
    if ten_percent.is_satisfied_by(order):
        return TEN_PERCENT
    if five_percent.is_satisfied_by(order):
        return FIVE_PERCENT
    return Decimal("0")


def discount_amount(order: Order) -> Money:
    return Money(order.total.amount * discount_rate(order)).rounded()


def net_total(order: Order) -> Money:
    """Total del pedido menos el descuento aplicable."""
    return Money(order.total.amount - discount_amount(order).amount)

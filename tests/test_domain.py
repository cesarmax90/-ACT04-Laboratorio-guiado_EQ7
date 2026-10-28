from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from app.domain import (
    Customer,
    InvalidOrderData,
    InvalidOrderTransition,
    Money,
    Order,
    OrderItem,
    OrderItemLimitExceeded,
    OrderStatus,
)
from app.specifications import (
    ActivePromotionSpec,
    MinimumAmountSpec,
    MinimumUnitsSpec,
    VIPCustomerSpec,
    discount_rate,
    net_total,
)
from cargar_csv import load_fixture


def item(qty=1, price="100.00", sku="SKU001"):
    return OrderItem(sku, qty, Money(Decimal(price)))


def order(vip=False, active=True, promo=False):
    return Order(customer=Customer("CX", vip, active), id="OX", has_promotion=promo)


# ---------- Money ----------
def test_money_negativo():
    with pytest.raises(InvalidOrderData):
        Money(Decimal("-1"))


def test_money_rechaza_float_y_no_finitos():
    with pytest.raises(InvalidOrderData):
        Money(600.0)
    with pytest.raises(InvalidOrderData):
        Money(Decimal("NaN"))
    with pytest.raises(InvalidOrderData):
        Money(Decimal("Infinity"))


def test_money_inmutable():
    m = Money(Decimal("10.00"))
    with pytest.raises(FrozenInstanceError):
        m.amount = Decimal("1")


def test_money_add_devuelve_objeto_nuevo():
    a, b = Money(Decimal("10.50")), Money(Decimal("2.25"))
    c = a.add(b)
    assert c.amount == Decimal("12.75") and c is not a and a.amount == Decimal("10.50")


def test_money_add_monedas_distintas():
    with pytest.raises(InvalidOrderData):
        Money(Decimal("1")).add(Money(Decimal("1"), "USD"))


def test_decimal_evita_error_de_float():
    assert Decimal("0.10") + Decimal("0.20") == Decimal("0.30")
    assert 0.1 + 0.2 != 0.3


# ---------- OrderItem ----------
@pytest.mark.parametrize("qty", [0, -1])
def test_item_cantidad_invalida(qty):
    with pytest.raises(InvalidOrderData):
        OrderItem("SKU001", qty, Money(Decimal("1")))


def test_item_sku_vacio():
    with pytest.raises(InvalidOrderData):
        OrderItem("  ", 1, Money(Decimal("1")))


def test_item_subtotal_calculado():
    assert item(2, "600.00").subtotal.amount == Decimal("1200.00")


# ---------- Carga ----------
def test_pedido_o001_inicia_draft():
    orders = load_fixture()
    assert orders["O001"].status.value == "DRAFT"
    assert orders["O001"].units == 4
    assert orders["O001"].total.amount == Decimal("2100.00")


def test_carga_16_pedidos_todos_draft():
    orders = load_fixture()
    assert len(orders) == 16
    assert all(o.status is OrderStatus.DRAFT for o in orders.values())
    assert sum(len(o.items) for o in orders.values()) == 21


# ---------- Límite de 20 unidades ----------
def test_20_unidades_exactas_permitidas():
    assert load_fixture()["O008"].units == 20


def test_21_unidades_rechazadas_sin_modificar_items():
    o = load_fixture()["O009"]
    with pytest.raises(OrderItemLimitExceeded):
        o.add_item(item(2, "120.00", "SKU003"))
    assert o.units == 19 and len(o.items) == 1


def test_limite_cuenta_unidades_no_renglones():
    o = order()
    for _ in range(10):
        o.add_item(item(2))  # 10 renglones, 20 unidades
    assert len(o.items) == 10 and o.units == 20
    with pytest.raises(OrderItemLimitExceeded):
        o.add_item(item(1))


def test_agregar_item_solo_en_draft():
    o = order()
    o.add_item(item())
    o.confirm()
    with pytest.raises(InvalidOrderTransition):
        o.add_item(item())


def test_agregar_item_moneda_distinta():
    o = order()
    with pytest.raises(InvalidOrderData):
        o.add_item(OrderItem("SKU001", 1, Money(Decimal("1"), "USD")))


# ---------- Confirmación ----------
def test_cliente_inactivo_no_confirma():
    o = load_fixture()["O003"]
    with pytest.raises(InvalidOrderData):
        o.confirm()
    assert o.status is OrderStatus.DRAFT and o.events == []


def test_pedido_vacio_no_confirma():
    o = load_fixture()["O007"]
    with pytest.raises(InvalidOrderData):
        o.confirm()
    assert o.status is OrderStatus.DRAFT and o.events == []


def test_confirmacion_doble_no_agrega_evento():
    o = load_fixture()["O013"]
    o.confirm()
    assert o.status is OrderStatus.CONFIRMED and len(o.events) == 1
    with pytest.raises(InvalidOrderTransition):
        o.confirm()
    assert len(o.events) == 1


# ---------- Envío, cancelación, entrega, devolución ----------
@pytest.mark.parametrize("guia", ["", "   "])
def test_envio_sin_guia(guia):
    o = load_fixture()["O012"]
    o.confirm()
    with pytest.raises(InvalidOrderData):
        o.ship(guia)
    assert o.status is OrderStatus.CONFIRMED
    assert [e.name for e in o.events] == ["OrderConfirmed"]


def test_envio_desde_draft_rechazado():
    o = load_fixture()["O012"]
    with pytest.raises(InvalidOrderTransition):
        o.ship("TRK-1")


def test_cancelar_desde_confirmed():
    o = load_fixture()["O014"]
    o.confirm()
    o.cancel("Cliente cambió de opinión")
    assert o.status is OrderStatus.CANCELLED
    assert [e.name for e in o.events] == ["OrderConfirmed", "OrderCancelled"]


def test_cancelar_sin_motivo():
    o = load_fixture()["O014"]
    o.confirm()
    with pytest.raises(InvalidOrderData):
        o.cancel("  ")
    assert o.status is OrderStatus.CONFIRMED


def test_cancelacion_desde_shipped_rechazada():
    o = load_fixture()["O014"]
    o.confirm()
    o.ship("TRK-14")
    with pytest.raises(InvalidOrderTransition):
        o.cancel("Ya salió")
    assert o.status is OrderStatus.SHIPPED
    assert [e.name for e in o.events] == ["OrderConfirmed", "OrderShipped"]


def test_entrega_y_devolucion_exigen_shipped():
    o = load_fixture()["O016"]
    o.confirm()
    with pytest.raises(InvalidOrderTransition):
        o.deliver()
    with pytest.raises(InvalidOrderTransition):
        o.return_order()
    assert len(o.events) == 1


def test_estados_terminales_no_aceptan_mas_operaciones():
    o = load_fixture()["O016"]
    o.confirm()
    o.ship("TRK-16")
    o.deliver()
    for op in (o.confirm, o.deliver, o.return_order, lambda: o.ship("X"), lambda: o.cancel("x")):
        with pytest.raises(InvalidOrderTransition):
            op()
    assert o.status is OrderStatus.DELIVERED and len(o.events) == 3


# ---------- Specifications ----------
def test_specs_individuales():
    o = order(vip=True, promo=True)
    o.add_item(item(4, "125.01"))  # 500.04
    assert MinimumAmountSpec(Decimal("500")).is_satisfied_by(o)
    assert VIPCustomerSpec().is_satisfied_by(o)
    assert MinimumUnitsSpec(4).is_satisfied_by(o)
    assert ActivePromotionSpec().is_satisfied_by(o)


def test_composicion_and_or_not():
    o = order(vip=True)
    o.add_item(item(1, "100"))
    vip, promo = VIPCustomerSpec(), ActivePromotionSpec()
    assert (vip & ~promo).is_satisfied_by(o)
    assert (vip | promo).is_satisfied_by(o)
    assert not (vip & promo).is_satisfied_by(o)
    assert not (~vip).is_satisfied_by(o)
    assert (~(promo | ~vip)).is_satisfied_by(o)


def test_specification_no_modifica_el_pedido():
    o = load_fixture()["O001"]
    antes = (o.status, o.units, o.total, len(o.events))
    discount_rate(o)
    assert antes == (o.status, o.units, o.total, len(o.events))


def test_frontera_monto_estricto_con_vip_y_4_unidades():
    o = order(vip=True)
    o.add_item(item(4, "125.00"))  # exactamente 500.00
    assert discount_rate(o) == Decimal("0")
    o2 = order(vip=True)
    o2.add_item(item(4, "125.01"))  # 500.04
    assert discount_rate(o2) == Decimal("0.10")


def test_frontera_unidades_con_vip():
    o3, o4 = order(vip=True), order(vip=True)
    o3.add_item(item(3, "200"))
    o4.add_item(item(4, "200"))
    assert discount_rate(o3) == Decimal("0")
    assert discount_rate(o4) == Decimal("0.10")


def test_frontera_5000_estricta():
    o = order()
    o.add_item(item(1, "5000.00"))
    assert discount_rate(o) == Decimal("0")
    o2 = order()
    o2.add_item(item(1, "5000.01"))
    assert discount_rate(o2) == Decimal("0.05")


def test_prioridad_10_sobre_5():
    o = order(vip=True)
    o.add_item(item(4, "1500"))  # 6000, VIP, 4 uds, sin promo: cumple ambas
    assert discount_rate(o) == Decimal("0.10")
    assert net_total(o).amount == Decimal("5400.00")


def test_promocion_bloquea_ambos_descuentos():
    o = order(vip=True, promo=True)
    o.add_item(item(4, "1500"))
    assert discount_rate(o) == Decimal("0")

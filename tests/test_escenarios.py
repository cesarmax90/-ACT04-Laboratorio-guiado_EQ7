"""Una prueba por escenario de datos/escenarios.csv. Cada prueba carga fixtures nuevos."""
import csv
from decimal import Decimal

import pytest

from app.domain import (
    InvalidOrderData,
    InvalidOrderTransition,
    Money,
    OrderItem,
    OrderItemLimitExceeded,
    OrderStatus,
)
from app.specifications import discount_amount, discount_rate, net_total
from cargar_csv import BASE, load_fixture


def nombres(order):
    return [e.name for e in order.events]


def test_el_csv_define_15_escenarios():
    with (BASE / "escenarios.csv").open(encoding="utf-8-sig", newline="") as f:
        ids = [r["caso_id"] for r in csv.DictReader(f)]
    assert ids == [f"E{n:02d}" for n in range(1, 16)]


# ---------- E01–E05, E09, E10: evaluar descuento ----------
@pytest.mark.parametrize(
    "pedido, tasa, descuento, neto",
    [
        ("O001", "0.10", "210.00", "1890.00"),     # E01 VIP + >500 + 4 uds + sin promo
        ("O002", "0", "0.00", "1050.00"),          # E02 no VIP, total < 5000
        ("O005", "0", "0.00", "2100.00"),          # E04 promoción activa
        ("O006", "0.05", "900.00", "17100.00"),    # E05 total > 5000 sin promo
        ("O010", "0", "0.00", "500.00"),           # E09 total exactamente 500
        ("O011", "0", "0.00", "1500.00"),          # E10 solo 3 unidades
    ],
    ids=["e01", "e02", "e04", "e05", "e09", "e10"],
)
def test_descuentos_de_escenarios(pedido, tasa, descuento, neto):
    o = load_fixture()[pedido]
    assert discount_rate(o) == Decimal(tasa)
    assert discount_amount(o).amount == Decimal(descuento)
    assert net_total(o).amount == Decimal(neto)
    assert o.status is OrderStatus.DRAFT and o.events == []  # evaluar no cambia nada


def test_e01_descuento_vip_10():
    o = load_fixture()["O001"]
    assert (o.customer.is_vip, o.units, o.total.amount, o.has_promotion) == (True, 4, Decimal("2100.00"), False)
    assert discount_rate(o) == Decimal("0.10")


def test_e02_no_vip_sin_descuento():
    assert discount_rate(load_fixture()["O002"]) == Decimal("0")


def test_e04_promocion_activa_bloquea_descuento():
    o = load_fixture()["O005"]
    assert o.customer.is_vip and o.units >= 4 and o.total.amount > 500 and o.has_promotion
    assert discount_rate(o) == Decimal("0")


def test_e05_descuento_alternativo_5():
    assert discount_rate(load_fixture()["O006"]) == Decimal("0.05")


def test_e09_umbral_estricto_500():
    o = load_fixture()["O010"]
    assert o.total.amount == Decimal("500.00")
    assert discount_rate(o) == Decimal("0")


def test_e10_vip_con_3_unidades_sin_descuento():
    o = load_fixture()["O011"]
    assert o.customer.is_vip and o.units == 3 and o.total.amount > 500
    assert discount_rate(o) == Decimal("0")


# ---------- E03, E06, E07: confirmar ----------
def test_e03_cliente_inactivo_rechaza_confirmacion():
    o = load_fixture()["O003"]
    with pytest.raises(InvalidOrderData):
        o.confirm()
    assert o.status is OrderStatus.DRAFT and o.events == []


def test_e06_pedido_vacio_rechaza_confirmacion():
    o = load_fixture()["O007"]
    assert o.units == 0
    with pytest.raises(InvalidOrderData):
        o.confirm()
    assert o.status is OrderStatus.DRAFT and o.events == []


def test_e07_20_unidades_permitidas_y_confirma():
    o = load_fixture()["O008"]
    assert o.units == 20
    o.confirm()
    assert o.status is OrderStatus.CONFIRMED and nombres(o) == ["OrderConfirmed"]


# ---------- E08: límite ----------
def test_e08_21_unidades_exceden_limite():
    o = load_fixture()["O009"]
    with pytest.raises(OrderItemLimitExceeded):
        o.add_item(OrderItem("SKU003", 2, Money(Decimal("120.00"))))
    assert o.units == 19 and len(o.items) == 1 and o.total.amount == Decimal("2280.00")


# ---------- E11–E15: máquina de estados ----------
def test_e11_envio_sin_guia_rechazado():
    o = load_fixture()["O012"]
    o.confirm()
    with pytest.raises(InvalidOrderData):
        o.ship("")
    assert o.status is OrderStatus.CONFIRMED and nombres(o) == ["OrderConfirmed"]


def test_e12_segunda_confirmacion_rechazada():
    o = load_fixture()["O013"]
    o.confirm()
    with pytest.raises(InvalidOrderTransition):
        o.confirm()
    assert o.status is OrderStatus.CONFIRMED and nombres(o) == ["OrderConfirmed"]


def test_e13_cancelacion_desde_shipped_rechazada():
    o = load_fixture()["O014"]
    o.confirm()
    o.ship("TRK-O014")
    with pytest.raises(InvalidOrderTransition):
        o.cancel("Cliente ya no lo quiere")
    assert o.status is OrderStatus.SHIPPED and nombres(o) == ["OrderConfirmed", "OrderShipped"]


def test_e14_devolucion_termina_returned():
    o = load_fixture()["O015"]
    o.confirm()
    o.ship("TRK-O015")
    o.return_order()
    assert o.status is OrderStatus.RETURNED
    assert nombres(o) == ["OrderConfirmed", "OrderShipped", "OrderReturned"]


def test_e15_entrega_termina_delivered():
    o = load_fixture()["O016"]
    o.confirm()
    o.ship("TRK-O016")
    o.deliver()
    assert o.status is OrderStatus.DELIVERED
    assert nombres(o) == ["OrderConfirmed", "OrderShipped", "OrderDelivered"]

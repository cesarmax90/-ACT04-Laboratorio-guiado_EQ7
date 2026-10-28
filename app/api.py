"""API REST TechStore U4.

Los controladores solo buscan el pedido, llaman al método de Order y responden.
Las reglas de negocio viven en app/domain.py y app/specifications.py.
"""
from decimal import Decimal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.domain import (
    InvalidOrderData,
    InvalidOrderTransition,
    Money,
    Order,
    OrderItem,
    OrderItemLimitExceeded,
)
from app.specifications import discount_amount, discount_rate, net_total
from cargar_csv import load_fixture, rows

app = FastAPI(title="TechStore U4", description="Núcleo de negocio de pedidos (en memoria)")

orders: dict[str, Order] = load_fixture()
prices: dict[str, Decimal] = {x["sku"]: Decimal(x["precio_mxn"]) for x in rows("productos.csv")}


def reset_fixtures() -> None:
    """Vuelve a cargar los CSV (útil entre pruebas)."""
    orders.clear()
    orders.update(load_fixture())


# ---------- Excepciones de dominio -> HTTP ----------
def _error(status: int, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": str(exc)})


@app.exception_handler(InvalidOrderTransition)
def _transition_error(_: Request, exc: InvalidOrderTransition):
    return _error(409, exc)  # conflicto con el estado actual


@app.exception_handler(InvalidOrderData)
def _data_error(_: Request, exc: InvalidOrderData):
    return _error(422, exc)  # dato o regla de negocio inválidos


@app.exception_handler(OrderItemLimitExceeded)
def _limit_error(_: Request, exc: OrderItemLimitExceeded):
    return _error(422, exc)


# ---------- Esquemas de entrada ----------
class ItemIn(BaseModel):
    sku: str
    quantity: int


class ShipIn(BaseModel):
    tracking_number: str


class CancelIn(BaseModel):
    reason: str


# ---------- Helpers ----------
def _get(order_id: str) -> Order:
    order = orders.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="No existe")
    return order


def _money(m: Money) -> str:
    return f"{m.amount:.2f}"


def _view(order: Order) -> dict:
    return {
        "id": order.id,
        "customer_id": order.customer.id,
        "status": order.status.value,
        "has_promotion": order.has_promotion,
        "units": order.units,
        "total": _money(order.total),
        "items": [
            {"sku": i.sku, "quantity": i.quantity,
             "unit_price": _money(i.unit_price), "subtotal": _money(i.subtotal)}
            for i in order.items
        ],
        "tracking_number": order.tracking_number,
        "cancel_reason": order.cancel_reason,
        "events": [
            {"name": e.name, "occurred_at": e.occurred_at.isoformat(), "detail": e.detail}
            for e in order.events
        ],
    }


def _state(order: Order) -> dict:
    return {"id": order.id, "status": order.status.value}


# ---------- Consultas ----------
@app.get("/orders")
def list_orders():
    return [{"id": o.id, "status": o.status.value, "units": o.units, "total": _money(o.total)}
            for o in orders.values()]


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    return _view(_get(order_id))


@app.get("/orders/{order_id}/discount")
def get_discount(order_id: str):
    order = _get(order_id)
    return {
        "id": order.id,
        "total": _money(order.total),
        "discount_rate": str(discount_rate(order)),
        "discount_amount": _money(discount_amount(order)),
        "net_total": _money(net_total(order)),
    }


# ---------- Comandos ----------
@app.post("/orders/{order_id}/items", status_code=201)
def add_item(order_id: str, body: ItemIn):
    order = _get(order_id)
    price = prices.get(body.sku)
    if price is None:
        raise HTTPException(status_code=404, detail="SKU no existe")
    order.add_item(OrderItem(body.sku, body.quantity, Money(price)))
    return _view(order)


@app.post("/orders/{order_id}/confirm")
def confirm_order(order_id: str):
    order = _get(order_id)
    order.confirm()
    return _state(order)


@app.post("/orders/{order_id}/ship")
def ship_order(order_id: str, body: ShipIn):
    order = _get(order_id)
    order.ship(body.tracking_number)
    return _state(order)


@app.post("/orders/{order_id}/cancel")
def cancel_order(order_id: str, body: CancelIn):
    order = _get(order_id)
    order.cancel(body.reason)
    return _state(order)


@app.post("/orders/{order_id}/deliver")
def deliver_order(order_id: str):
    order = _get(order_id)
    order.deliver()
    return _state(order)


@app.post("/orders/{order_id}/return")
def return_order(order_id: str):
    order = _get(order_id)
    order.return_order()
    return _state(order)

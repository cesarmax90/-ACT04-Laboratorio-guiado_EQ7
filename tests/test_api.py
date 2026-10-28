import pytest
from fastapi.testclient import TestClient

from app import api

client = TestClient(api.app)


@pytest.fixture(autouse=True)
def fixtures_limpios():
    api.reset_fixtures()
    yield


def test_get_pedido_existente():
    r = client.get("/orders/O001")
    assert r.status_code == 200
    body = r.json()
    assert (body["status"], body["units"], body["total"]) == ("DRAFT", 4, "2100.00")


def test_listar_16_pedidos():
    assert len(client.get("/orders").json()) == 16


def test_confirmar_id_inexistente_404():
    assert client.post("/orders/NOEXISTE/confirm").status_code == 404
    assert client.get("/orders/NOEXISTE").status_code == 404


def test_confirmar_ok_200():
    r = client.post("/orders/O013/confirm")
    assert r.status_code == 200 and r.json() == {"id": "O013", "status": "CONFIRMED"}


def test_confirmar_dos_veces_409_sin_evento_extra():
    assert client.post("/orders/O013/confirm").status_code == 200
    r = client.post("/orders/O013/confirm")
    assert r.status_code == 409
    eventos = client.get("/orders/O013").json()["events"]
    assert [e["name"] for e in eventos] == ["OrderConfirmed"]


def test_confirmar_pedido_vacio_422():
    r = client.post("/orders/O007/confirm")
    assert r.status_code == 422
    assert client.get("/orders/O007").json()["status"] == "DRAFT"


def test_confirmar_cliente_inactivo_422():
    assert client.post("/orders/O003/confirm").status_code == 422


def test_enviar_sin_guia_422_y_con_guia_200():
    client.post("/orders/O012/confirm")
    assert client.post("/orders/O012/ship", json={"tracking_number": ""}).status_code == 422
    assert client.post("/orders/O012/ship", json={}).status_code == 422  # falta el campo
    r = client.post("/orders/O012/ship", json={"tracking_number": "TRK-12"})
    assert r.status_code == 200 and r.json()["status"] == "SHIPPED"


def test_cancelar_desde_shipped_409():
    client.post("/orders/O014/confirm")
    client.post("/orders/O014/ship", json={"tracking_number": "TRK-14"})
    r = client.post("/orders/O014/cancel", json={"reason": "tarde"})
    assert r.status_code == 409
    assert client.get("/orders/O014").json()["status"] == "SHIPPED"


def test_cancelar_desde_confirmed_200():
    client.post("/orders/O014/confirm")
    r = client.post("/orders/O014/cancel", json={"reason": "Cliente lo pidió"})
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"


def test_flujo_entrega_y_devolucion():
    for oid, final, accion in (("O016", "DELIVERED", "deliver"), ("O015", "RETURNED", "return")):
        client.post(f"/orders/{oid}/confirm")
        client.post(f"/orders/{oid}/ship", json={"tracking_number": f"TRK-{oid}"})
        r = client.post(f"/orders/{oid}/{accion}")
        assert r.status_code == 200 and r.json()["status"] == final


def test_agregar_item_excede_20_unidades_422():
    r = client.post("/orders/O009/items", json={"sku": "SKU003", "quantity": 2})
    assert r.status_code == 422
    assert client.get("/orders/O009").json()["units"] == 19


def test_agregar_item_valido_y_sku_inexistente():
    r = client.post("/orders/O009/items", json={"sku": "SKU003", "quantity": 1})
    assert r.status_code == 201 and r.json()["units"] == 20
    assert client.post("/orders/O001/items", json={"sku": "NOPE", "quantity": 1}).status_code == 404


def test_agregar_item_a_pedido_confirmado_409():
    client.post("/orders/O013/confirm")
    r = client.post("/orders/O013/items", json={"sku": "SKU001", "quantity": 1})
    assert r.status_code == 409


def test_agregar_item_cantidad_cero_422():
    assert client.post("/orders/O013/items", json={"sku": "SKU001", "quantity": 0}).status_code == 422


@pytest.mark.parametrize("oid, tasa, neto", [("O001", "0.10", "1890.00"), ("O006", "0.05", "17100.00"),
                                              ("O005", "0", "2100.00")])
def test_endpoint_descuento(oid, tasa, neto):
    body = client.get(f"/orders/{oid}/discount").json()
    assert body["discount_rate"] == tasa and body["net_total"] == neto


def test_docs_y_openapi_disponibles():
    assert client.get("/docs").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert "/orders/{order_id}/confirm" in paths

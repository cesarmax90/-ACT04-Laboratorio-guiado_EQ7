"""Ejecuta los escenarios E01–E15 de datos/escenarios.csv y genera la bitácora.

Uso:
    python ejecutar_escenarios.py                      # imprime la bitácora en consola
    python ejecutar_escenarios.py --md docs/BITACORA.md  # además escribe el archivo Markdown

Cada escenario parte de fixtures recién cargados; no se editan los pedidos.
"""
import csv
import subprocess
import sys
from decimal import Decimal

from fastapi.testclient import TestClient

from app import api
from app.domain import DomainException
from app.specifications import discount_amount, discount_rate, net_total
from cargar_csv import BASE, load_fixture

T = "tests/test_escenarios.py::"
PRUEBA = {
    "E01": "test_e01_descuento_vip_10", "E02": "test_e02_no_vip_sin_descuento",
    "E03": "test_e03_cliente_inactivo_rechaza_confirmacion", "E04": "test_e04_promocion_activa_bloquea_descuento",
    "E05": "test_e05_descuento_alternativo_5", "E06": "test_e06_pedido_vacio_rechaza_confirmacion",
    "E07": "test_e07_20_unidades_permitidas_y_confirma", "E08": "test_e08_21_unidades_exceden_limite",
    "E09": "test_e09_umbral_estricto_500", "E10": "test_e10_vip_con_3_unidades_sin_descuento",
    "E11": "test_e11_envio_sin_guia_rechazado", "E12": "test_e12_segunda_confirmacion_rechazada",
    "E13": "test_e13_cancelacion_desde_shipped_rechazada", "E14": "test_e14_devolucion_termina_returned",
    "E15": "test_e15_entrega_termina_delivered",
}
EXPLICACION = {
    "E01": "Cumple las 4 condiciones del 10 %: VIP, 2100.00 > 500, 4 ≥ 4 unidades y sin promoción.",
    "E02": "C002 no es VIP (falla la regla de 10 %) y 1050.00 no supera 5000 (falla la de 5 %).",
    "E03": "C003 es VIP pero está inactivo: confirm() valida antes de cambiar el estado y no emite evento.",
    "E04": "C005 es VIP, 4 unidades y 2100.00, pero la promoción activa bloquea ambos descuentos (~ActivePromotionSpec).",
    "E05": "18000.00 > 5000 y sin promoción cumple el 5 %; C006 no es VIP, por eso no alcanza el 10 %.",
    "E06": "Sin renglones, confirm() lanza InvalidOrderData; el pedido sigue DRAFT y no hay evento.",
    "E07": "20 unidades es el máximo permitido (solo > 20 se rechaza); el pedido se confirma.",
    "E08": "19 + 2 = 21 > 20: add_item() detiene la operación antes de modificar items. Se suman unidades, no renglones.",
    "E09": "El total 500.00 no supera 500 (umbral estricto >). Nota: C010 no es VIP y tiene 2 unidades, así que "
           "este pedido solo no aísla la frontera; la frontera se prueba con VIP y 4 unidades en "
           "test_frontera_monto_estricto_con_vip_y_4_unidades.",
    "E10": "C011 es VIP y 1500.00 > 500, pero 3 unidades < 4: falla MinimumUnitsSpec(4).",
    "E11": "La confirmación es válida; ship('') lanza InvalidOrderData. Sigue CONFIRMED y no se emite OrderShipped.",
    "E12": "La segunda confirmación lanza InvalidOrderTransition (solo DRAFT confirma) y no agrega un segundo evento.",
    "E13": "cancel() exige CONFIRMED; desde SHIPPED lanza InvalidOrderTransition y no emite OrderCancelled.",
    "E14": "SHIPPED permite return_order(): estado final RETURNED y tres eventos en orden.",
    "E15": "SHIPPED permite deliver(): estado final DELIVERED y tres eventos en orden.",
}
# Operaciones HTTP equivalentes (método, ruta, cuerpo)
HTTP = {
    "E01": [("GET", "/orders/O001/discount", None)], "E02": [("GET", "/orders/O002/discount", None)],
    "E03": [("POST", "/orders/O003/confirm", None)], "E04": [("GET", "/orders/O005/discount", None)],
    "E05": [("GET", "/orders/O006/discount", None)], "E06": [("POST", "/orders/O007/confirm", None)],
    "E07": [("POST", "/orders/O008/confirm", None)],
    "E08": [("POST", "/orders/O009/items", {"sku": "SKU003", "quantity": 2})],
    "E09": [("GET", "/orders/O010/discount", None)], "E10": [("GET", "/orders/O011/discount", None)],
    "E11": [("POST", "/orders/O012/confirm", None), ("POST", "/orders/O012/ship", {"tracking_number": ""})],
    "E12": [("POST", "/orders/O013/confirm", None), ("POST", "/orders/O013/confirm", None)],
    "E13": [("POST", "/orders/O014/confirm", None), ("POST", "/orders/O014/ship", {"tracking_number": "TRK-O014"}),
            ("POST", "/orders/O014/cancel", {"reason": "Cliente ya no lo quiere"})],
    "E14": [("POST", "/orders/O015/confirm", None), ("POST", "/orders/O015/ship", {"tracking_number": "TRK-O015"}),
            ("POST", "/orders/O015/return", None)],
    "E15": [("POST", "/orders/O016/confirm", None), ("POST", "/orders/O016/ship", {"tracking_number": "TRK-O016"}),
            ("POST", "/orders/O016/deliver", None)],
}


def describe(o):
    c = o.customer
    return (f"{o.status.value}; cliente {c.id} ({'VIP' if c.is_vip else 'no VIP'}, "
            f"{'activo' if c.active else 'inactivo'}); {o.units} uds; total {o.total.amount} MXN; "
            f"promoción {'sí' if o.has_promotion else 'no'}")


def step(label, fn):
    """Ejecuta una operación; devuelve (texto, éxito)."""
    try:
        fn()
        return f"{label} → OK", True
    except DomainException as exc:
        return f"{label} → {type(exc).__name__}: {exc}", False


def descuento(o):
    return (f"tasa {discount_rate(o):.0%}, descuento {discount_amount(o).amount}, "
            f"neto {net_total(o).amount}; estado {o.status.value}")


def operar(caso, o):
    """Devuelve (operación, resultado, éxito_esperado_coincide)."""
    cid = caso["caso_id"]
    obj = caso["objetivo"]
    if caso["accion"] == "evaluar_descuento":
        res = descuento(o)
        return "discount_rate(order) / discount_amount(order)", res, res.startswith(f"tasa {obj}")
    if cid == "E08":
        from app.domain import Money, OrderItem
        txt, _ = step("add_item(SKU003 × 2)", lambda: o.add_item(OrderItem("SKU003", 2, Money(Decimal("120.00")))))
        return "add_item(OrderItem('SKU003', 2, 120.00))", f"{txt}; uds={o.units}", "OrderItemLimitExceeded" in txt
    pasos = {
        "E03": [("confirm()", o.confirm)],
        "E06": [("confirm()", o.confirm)],
        "E07": [("confirm()", o.confirm)],
        "E11": [("confirm()", o.confirm), ("ship('')", lambda: o.ship(""))],
        "E12": [("confirm()", o.confirm), ("confirm() 2.ª vez", o.confirm)],
        "E13": [("confirm()", o.confirm), ("ship('TRK-O014')", lambda: o.ship("TRK-O014")),
                ("cancel('Cliente ya no lo quiere')", lambda: o.cancel("Cliente ya no lo quiere"))],
        "E14": [("confirm()", o.confirm), ("ship('TRK-O015')", lambda: o.ship("TRK-O015")),
                ("return_order()", o.return_order)],
        "E15": [("confirm()", o.confirm), ("ship('TRK-O016')", lambda: o.ship("TRK-O016")),
                ("deliver()", o.deliver)],
    }[cid]
    textos, oks = zip(*(step(lbl, fn) for lbl, fn in pasos))
    final_ok = oks[-1]
    coincide = final_ok if obj == "exito" else not final_ok
    return " → ".join(lbl for lbl, _ in pasos), " | ".join(textos) + f" | estado final {o.status.value}", coincide


def http_evidencia(cid, client):
    api.reset_fixtures()
    partes = []
    for metodo, ruta, cuerpo in HTTP[cid]:
        r = client.request(metodo, ruta, json=cuerpo)
        extra = f" tasa {r.json()['discount_rate']}" if ruta.endswith("/discount") else ""
        partes.append(f"{metodo} {ruta} → {r.status_code}{extra}")
    return " ; ".join(partes)


def ejecutar():
    with (BASE / "escenarios.csv").open(encoding="utf-8-sig", newline="") as f:
        casos = list(csv.DictReader(f))
    client = TestClient(api.app)
    resultados = []
    for caso in casos:
        o = load_fixture()[caso["pedido_id"]]  # fixtures nuevos por escenario
        pre = describe(o)
        operacion, resultado, coincide = operar(caso, o)
        eventos = [e.name for e in o.events]
        if caso["accion"] == "evaluar_descuento":
            evento = "Ninguno (consulta: no cambia el estado)"
        elif eventos:
            evento = ", ".join(eventos)
        else:
            evento = "Ninguno (operación rechazada)"
        resultados.append({**caso, "pre": pre, "operacion": operacion, "resultado": resultado,
                           "evento": evento, "coincide": coincide, "http": http_evidencia(caso["caso_id"], client)})
    return resultados


def captura_carga():
    return "\n".join(f"{i} {o.status.value} {o.units} {o.total.amount}" for i, o in load_fixture().items())


def captura_pytest():
    out = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:warnings"],
                         capture_output=True, text=True).stdout.strip()
    return out


def evidencia_http_general():
    client, filas = TestClient(api.app), []
    api.reset_fixtures()
    casos = [
        ("Éxito", "POST", "/orders/O013/confirm", None),
        ("Rechazo: estado", "POST", "/orders/O013/confirm", None),
        ("Rechazo: no existe", "POST", "/orders/NOEXISTE/confirm", None),
        ("Rechazo: sin artículos", "POST", "/orders/O007/confirm", None),
    ]
    for etiqueta, m, ruta, cuerpo in casos:
        r = client.request(m, ruta, json=cuerpo)
        filas.append((etiqueta, f"{m} {ruta}", r.status_code, r.json()))
    return filas


def markdown(res):
    L = []
    ok = sum(r["coincide"] for r in res)
    L += ["# Bitácora TechStore U4 — Escenarios E01–E15", "",
          "Resultados reales generados con `python ejecutar_escenarios.py --md docs/BITACORA.md`. "
          "Cada escenario parte de fixtures recién cargados; no se editaron pedidos ni reglas.", "",
          f"**Resumen:** {ok}/15 escenarios coinciden con el objetivo de `escenarios.csv`.", "",
          "## 1. Carga de datos (`python cargar_csv.py`)", "", "```text", captura_carga(), "```", "",
          "> Captura pendiente: pantallazo de la terminal con estos 16 pedidos en DRAFT.", "",
          "## 2. Actividad corta (cálculo manual)", "",
          "| Pedido | Cliente | Unidades | Total manual |", "| --- | --- | --- | --- |",
          "| O001 | C001 (VIP) | 4 (2×SKU001 + 2×SKU002) | 2×600 + 2×450 = **2100.00** |",
          "| O006 | C006 | 1 (1×SKU008) | **18000.00** |",
          "| O010 | C010 | 2 (SKU003 + SKU009) | 120 + 380 = **500.00** |", "",
          "## 3. Resumen de escenarios", "",
          "| Caso | Pedido | Acción | Esperado | ¿Coincide? |", "| --- | --- | --- | --- | --- |"]
    for r in res:
        L.append(f"| {r['caso_id']} | {r['pedido_id']} | {r['accion']} | {r['objetivo']} | "
                 f"{'✅' if r['coincide'] else '❌'} |")
    L += ["", "## 4. Bitácora detallada", ""]
    for r in res:
        cid = r["caso_id"]
        L += [f"### {cid} — {r['pedido_id']} · {r['accion']} → {r['objetivo']}", "",
              f"- **Precondiciones (estado inicial):** {r['pre']}",
              f"- **Operación:** `{r['operacion']}`",
              f"- **Resultado real:** {r['resultado']}",
              f"- **Evento:** {r['evento']}",
              f"- **Explicación:** {EXPLICACION[cid]}",
              f"- **API equivalente:** {r['http']}",
              f"- **Prueba:** `{T}{PRUEBA[cid]}`", ""]
    L += ["## 5. Máquina de estados", "", "```mermaid", "stateDiagram-v2",
          "    [*] --> DRAFT",
          "    DRAFT --> CONFIRMED: confirm() / OrderConfirmed",
          "    CONFIRMED --> SHIPPED: ship(guía) / OrderShipped",
          "    CONFIRMED --> CANCELLED: cancel(motivo) / OrderCancelled",
          "    SHIPPED --> DELIVERED: deliver() / OrderDelivered",
          "    SHIPPED --> RETURNED: return_order() / OrderReturned",
          "    DELIVERED --> [*]", "    CANCELLED --> [*]", "    RETURNED --> [*]", "```", "",
          "| Método | Estado requerido | Validación adicional | Evento | Estado nuevo |",
          "| --- | --- | --- | --- | --- |",
          "| `confirm()` | DRAFT | ≥ 1 artículo y cliente activo | OrderConfirmed | CONFIRMED |",
          "| `ship(guía)` | CONFIRMED | guía no vacía | OrderShipped | SHIPPED |",
          "| `cancel(motivo)` | CONFIRMED | motivo no vacío | OrderCancelled | CANCELLED |",
          "| `deliver()` | SHIPPED | — | OrderDelivered | DELIVERED |",
          "| `return_order()` | SHIPPED | — | OrderReturned | RETURNED |", "",
          "**Domain Events.** Un evento es un hecho ya ocurrido en el dominio (`DomainEvent`: nombre, "
          "`order_id`, fecha UTC y detalle). Cada método sigue el orden *validar → cambiar estado → registrar evento*, "
          "así que un evento solo existe si la transición fue válida: una operación rechazada no deja rastro "
          "(E03, E06, E11, E12, E13). La lista `order.events` queda como historial auditable y es el punto "
          "donde después se podría notificar a otros componentes.", "",
          "## 6. Evidencia de la API (`/docs`)", "",
          "| Caso | Petición | HTTP | Respuesta |", "| --- | --- | --- | --- |"]
    for etiqueta, req, code, body in evidencia_http_general():
        L.append(f"| {etiqueta} | `{req}` | {code} | `{body}` |")
    L += ["", "Mapeo de errores: `InvalidOrderTransition` → 409; `InvalidOrderData` y "
          "`OrderItemLimitExceeded` → 422; pedido o SKU inexistente → 404.", "",
          "> Capturas pendientes en Swagger (`uvicorn app.api:app --reload` → `/docs`): una operación exitosa "
          "(`POST /orders/O013/confirm` → 200) y una rechazada (repetirla → 409).", "",
          "## 7. Resultado de pytest (`python -m pytest -q`)", "", "```text", captura_pytest(), "```", ""]
    return "\n".join(L)


if __name__ == "__main__":
    res = ejecutar()
    for r in res:
        print(f"{r['caso_id']} {r['pedido_id']} [{'OK' if r['coincide'] else 'FALLA'}] "
              f"{r['operacion']}\n    {r['resultado']}\n    evento: {r['evento']}")
    print(f"\n{sum(r['coincide'] for r in res)}/15 escenarios coinciden con el objetivo")
    if "--md" in sys.argv:
        ruta = sys.argv[sys.argv.index("--md") + 1]
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(markdown(res))
        print(f"Bitácora escrita en {ruta}")

# TechStore U4 — Núcleo de negocio de pedidos

Práctica guiada de la Actividad 4 (Componentes de Lógica de Negocio, FIME · UANL).
Lee clientes, productos y pedidos desde CSV, los convierte en objetos, aplica descuentos con
Specifications, controla el estado del pedido y expone una API REST (FastAPI). Todo en memoria.

## Instalación

```bash
python --version                  # 3.11 o superior
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1   |   macOS / Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Ejecución

```bash
python cargar_csv.py                                   # carga los 16 pedidos (todos DRAFT)
python ejecutar_escenarios.py --md docs/BITACORA.md    # ejecuta E01–E15 y genera la bitácora
python -m pytest -q                                    # pruebas
uvicorn app.api:app --reload                           # API → http://127.0.0.1:8000/docs
```

## Reglas de negocio

- `Money` es inmutable, usa `Decimal` (no `float`) y no admite importes negativos.
- Máximo **20 unidades** por pedido (suma de cantidades, no de renglones).
- Descuento **10 %**: cliente VIP, total **> 500** MXN, **≥ 4** unidades y sin promoción.
- Descuento **5 %**: total **> 5000** MXN y sin promoción. Si ambas reglas aplican, gana el 10 %.
- Todos los pedidos inician en `DRAFT`. El stock del catálogo es solo contexto (sin control de inventario).
- Los cambios no persisten entre ejecuciones.

## Estados y eventos

`DRAFT → CONFIRMED → SHIPPED → DELIVERED`, con `CANCELLED` (desde CONFIRMED) y `RETURNED` (desde SHIPPED).
Eventos: `OrderConfirmed`, `OrderShipped`, `OrderCancelled`, `OrderDelivered`, `OrderReturned`.
Detalle en [docs/BITACORA.md](docs/BITACORA.md).

## Endpoints

| Método | Ruta | Descripción | Códigos |
| --- | --- | --- | --- |
| GET | `/orders` | Lista los pedidos | 200 |
| GET | `/orders/{id}` | Detalle, artículos y eventos | 200, 404 |
| GET | `/orders/{id}/discount` | Tasa, descuento y total neto | 200, 404 |
| POST | `/orders/{id}/items` | Agrega `{sku, quantity}` | 201, 404, 409, 422 |
| POST | `/orders/{id}/confirm` | DRAFT → CONFIRMED | 200, 404, 409, 422 |
| POST | `/orders/{id}/ship` | Cuerpo `{tracking_number}` | 200, 404, 409, 422 |
| POST | `/orders/{id}/cancel` | Cuerpo `{reason}` | 200, 404, 409, 422 |
| POST | `/orders/{id}/deliver` | SHIPPED → DELIVERED | 200, 404, 409 |
| POST | `/orders/{id}/return` | SHIPPED → RETURNED | 200, 404, 409 |

Errores: `InvalidOrderTransition` → **409**; `InvalidOrderData` y `OrderItemLimitExceeded` → **422**;
pedido o SKU inexistente → **404**.

## Estructura

```text
datos/                CSV del paquete (no se editan)
cargar_csv.py         cargador del paquete
ejecutar_escenarios.py  ejecuta E01–E15 y genera docs/BITACORA.md
app/domain.py         Money, Customer, OrderItem, Order, DomainEvent
app/specifications.py Specification, And/Or/Not y reglas de descuento
app/api.py            API FastAPI
tests/                test_domain.py, test_escenarios.py, test_api.py
docs/                 BITACORA.md, REPORTE.md
```

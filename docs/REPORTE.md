# Reporte — TechStore U4

## Preguntas del reporte

**1. ¿Por qué `Decimal` y no `float` para precios?**
`float` es binario y no representa exactamente valores como 0.10 (`0.1 + 0.2 != 0.3`). Esos errores se
acumulan en subtotales y descuentos. `Decimal` trabaja en base 10 y los centavos salen exactos.

**2. ¿Diferencia entre contar renglones y sumar unidades?**
O009 tiene un solo renglón con 19 unidades; O008, un renglón con 20. El límite es de 20 unidades en
total: 10 renglones de 2 unidades son válidos y un renglón de 21 no. Contar renglones permitiría
pedidos enormes con pocos renglones.

**3. ¿Qué ventaja tiene encapsular una regla en una Specification?**
La regla tiene nombre, se prueba sola, se reutiliza y se combina con `&`, `|` y `~` sin tocar el
pedido. Cambiar un umbral implica editar un solo lugar.

**4. ¿Por qué los eventos se registran solo tras una transición válida?**
Un evento afirma que algo ya ocurrió. Si se registrara antes de validar, quedaría un `OrderShipped`
de un envío que nunca sucedió (E11, E12, E13). Por eso el orden es validar, cambiar estado y registrar.

**5. ¿Qué código se reutiliza si se reemplaza FastAPI?**
Todo `app/domain.py`, `app/specifications.py`, `cargar_csv.py` y las pruebas de dominio. Solo
`app/api.py` (rutas, esquemas y mapeo a HTTP) se sustituye por la nueva interfaz.

## Reflexión (borrador: ajústala a tu experiencia)

1. **E09 no probaba la frontera por sí solo.** Cambié `>` por `>=` en `MinimumAmountSpec` y E09 seguía
   pasando, porque O010 no es VIP y tiene 2 unidades. Agregué pruebas con VIP, 4 unidades y totales de
   500.00 y 500.04 (y de 5000.00 y 5000.01). Aprendí que un escenario puede dar el resultado esperado
   por otra razón.
2. **`Money(600.0)` fallaba con un error ajeno al dominio.** `float` no tiene `is_finite`, así que el
   constructor sugerido lanzaría `AttributeError`. Agregué una validación de tipo que lanza
   `InvalidOrderData` y una prueba. Aprendí a validar también el tipo, no solo el valor.
3. **Un evento registrado antes de validar pasaba desapercibido.** Al moverlo a propósito antes de
   comprobar la guía, 8 pruebas fallaron. Las pruebas de "sin evento tras un rechazo" son las que
   protegen el orden validar → cambiar → registrar.

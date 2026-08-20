# Contrato de la base de datos

El esquema completo está en [`database/schema_lubriexpress.sql`](../database/schema_lubriexpress.sql).
Este documento explica las reglas que el esquema hace cumplir y por qué existen.

## La regla principal

> El stock **nunca** se modifica con un `UPDATE` sobre `productos`.
> Se inserta un movimiento en `kardex_movimientos` y los triggers hacen el resto.

El sistema anterior de Lubri-Express descuadraba el stock y permitía alterar el
historial. Todo el diseño de esta base apunta a que eso sea imposible, no solo
desaconsejado: si la aplicación pudiera tocar `stock_actual` directamente, existiría
un camino para mover inventario sin dejar rastro, y el Kardex dejaría de servir como
registro auditable.

La lógica vive en la base de datos y no en Python a propósito. Así vale igual si el
movimiento entra por la aplicación, por un script de migración o por alguien con una
consola de psql abierta.

## Tablas

| Tabla | Rol |
|---|---|
| `usuarios` | Operadores del sistema. Roles: `ADMINISTRADOR`, `SUPERVISOR`, `USUARIO_NORMAL` |
| `clientes` | Personas y empresas. RUT único |
| `vehiculos` | Cuelgan de un cliente. Patente única |
| `ubicaciones` | Dónde está guardado físicamente un producto |
| `productos` | Inventario. `stock_actual` lo manejan los triggers |
| `ordenes` / `detalle_ordenes` | Órdenes de trabajo del taller |
| `ventas` / `detalle_ventas` | Ventas de mostrador |
| `kardex_movimientos` | Historial de inventario. Solo se agrega, nunca se edita |

## Triggers

| Trigger | Cuándo | Qué hace |
|---|---|---|
| `trg_detalle_ordenes_descuento` | `INSERT` en `detalle_ordenes` | Descuenta stock y escribe `SALIDA_ORDEN` en el Kardex |
| `trg_detalle_ventas_descuento` | `INSERT` en `detalle_ventas` | Descuenta stock y escribe `SALIDA_VENTA` en el Kardex |
| `trg_kardex_movimiento_manual` | `INSERT` en `kardex_movimientos` de tipo `ENTRADA` o `AJUSTE_MANUAL` | Mueve el stock y calcula `stock_resultante` |
| `trg_*_updated_at` | `UPDATE` en `usuarios`, `clientes`, `vehiculos`, `productos` | Refresca `updated_at` |

Los dos primeros van en sentido aplicación → Kardex: se registra la venta y el
movimiento aparece solo. El tercero va al revés: se registra el movimiento y el stock
se mueve solo. Las dos direcciones terminan en lo mismo — no hay forma de cambiar el
stock sin una fila de Kardex que lo explique.

### Convención de signos

`cantidad_movida` es **con signo**: positiva suma, negativa resta. Las salidas por
venta u orden se guardan negativas (`-3` por vender 3 unidades). Un movimiento de
cero se rechaza porque no significa nada.

### Registrar una entrada de mercadería

```sql
INSERT INTO kardex_movimientos (producto_id, usuario_id, tipo_movimiento, cantidad_movida)
VALUES (:producto, :usuario, 'ENTRADA', 12);
```

No se pasa `stock_resultante` ni se toca `productos`: el trigger completa ambas cosas.

## Invariantes protegidas por la base

| Restricción | Qué impide |
|---|---|
| `productos.stock_actual >= 0` | Vender o consumir más de lo que hay. La transacción completa se revierte |
| `descuento_exclusivo_orden` | Aplicar porcentaje y monto fijo de descuento a la vez |
| `origen_movimiento_valido` | Un movimiento de Kardex que no calce con su origen (una `SALIDA_VENTA` sin venta, o con orden) |
| `cantidad_movida <> 0` | Movimientos vacíos |
| `UNIQUE` en `clientes.rut`, `vehiculos.patente`, `numero_boleta` | Duplicados |

El CHECK de stock no negativo es el que hace el trabajo pesado: al ser el trigger
parte de la misma transacción que el `INSERT` del detalle, un intento de sobreventa
revierte el detalle, el descuento y el movimiento de Kardex de una sola vez. No queda
media venta registrada.

Los RUT se guardan siempre formateados (`12.345.678-5`) por [`src/rut.py`](../src/rut.py).
Sin normalizar, `123456785` y `12.345.678-5` entrarían como dos clientes distintos y el
`UNIQUE` no serviría de nada.

## Vistas

`vw_stock_critico` lista los productos activos con `stock_actual <= stock_minimo`. La
aplicación la consulta en vez de repetir el criterio: si mañana el umbral cambia, se
cambia en un solo lugar.

## Lo que no se debe hacer

- `UPDATE productos SET stock_actual = ...` — rompe la trazabilidad. Usa un movimiento de Kardex.
- `UPDATE` o `DELETE` sobre `kardex_movimientos` — el historial es solo de agregado.
- Guardar un RUT sin pasarlo por `src.rut.formatear()`.
- Borrar un cliente con vehículos: la FK lo impide, y está bien que lo impida.

## Pendiente de endurecer

Las reglas de arriba hoy se sostienen por convención y por los triggers. Faltan los
permisos que las harían imposibles de saltar, una vez que exista un rol de aplicación
separado de `postgres`:

```sql
REVOKE UPDATE, DELETE ON kardex_movimientos FROM rol_aplicacion;
REVOKE UPDATE ("stock_actual") ON productos FROM rol_aplicacion;
```

## Cambios de esquema

No hay migraciones todavía. Un cambio hoy significa editar el `.sql` y recrear la base:

```bash
docker rm -f lubriexpress-db && docker volume rm lubriexpress-pgdata
# volver a crear el contenedor y cargar el esquema (ver README)
```

Sirve mientras no haya datos reales. Antes de la puesta en producción hay que
incorporar Alembic, o cada ajuste posterior obligará a migrar el inventario a mano.

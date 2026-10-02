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
| `clientes` | Personas y empresas. RUT único, y opcional salvo para empresas |
| `vehiculos` | Cuelgan de un cliente. Patente única |
| `ubicaciones` | Dónde está guardado físicamente un producto |
| `productos` | Inventario. `stock_actual` lo manejan los triggers |
| `servicios` | Mano de obra (cambio de aceite, scanner). Se cobra en una orden; no tiene stock ni Kardex |
| `ordenes` / `detalle_ordenes` | Órdenes de trabajo del taller. Cada línea del detalle es un producto o un servicio. `estado` dice si el auto sigue adentro |
| `pagos_orden` | Abonos de una orden. Solo se agrega: lo pagado es la suma, y el estado de la orden sale de ahí |
| `ventas` / `detalle_ventas` | Ventas de mostrador |
| `kardex_movimientos` | Historial de inventario. Solo se agrega, nunca se edita |
| `movimientos_caja` | Caja chica del día: el efectivo del cajón que no pasa por una venta. Solo se agrega |
| `cuentas_por_cobrar` / `pagos_cobro` | Facturas por cobrar, casi siempre a organismos de Mercado Público. Las abre el trigger desde una orden con folio, o se ingresan a mano. Los abonos solo se agregan |
| `proveedores` / `facturas_proveedor` / `pagos_proveedor` | Cuentas por pagar: la factura de cada proveedor con su vencimiento, y sus abonos, que solo se agregan |

## Triggers

| Trigger | Cuándo | Qué hace |
|---|---|---|
| `trg_detalle_ordenes_descuento` | `INSERT` en `detalle_ordenes` con `producto_id` | Descuenta stock y escribe `SALIDA_ORDEN` en el Kardex. Las líneas de servicio no lo disparan (`WHEN`) |
| `trg_detalle_ventas_descuento` | `INSERT` en `detalle_ventas` | Descuenta stock y escribe `SALIDA_VENTA` en el Kardex |
| `trg_kardex_movimiento_manual` | `INSERT` en `kardex_movimientos` de tipo `ENTRADA` o `AJUSTE_MANUAL` | Mueve el stock y calcula `stock_resultante` |
| `trg_detalle_ordenes_devolucion` | `DELETE` en `detalle_ordenes` con `producto_id` | Devuelve el stock y escribe `DEVOLUCION_ORDEN` en el Kardex |
| `trg_pagos_orden_estado` | `INSERT` en `pagos_orden` | Recalcula `ordenes.estado_pago` con la suma de los abonos |
| `trg_ordenes_estado_pago` | `UPDATE` de `ordenes.total_final` | Recalcula `estado_pago`: si el total creció, lo abonado ya no alcanza. Una orden cuya cuenta por cobrar está `PAGADA` sigue pagada |
| `trg_detalle_ordenes_costo` / `trg_detalle_ventas_costo` | `INSERT` en `detalle_ordenes` / `detalle_ventas` | Copia `productos.precio_costo` a `costo_unitario` de la línea, si no trae uno. Los servicios quedan en `NULL` |
| `trg_ordenes_cliente` | `INSERT` en `ordenes` | Copia el dueño del vehículo a `cliente_id`. Si el auto se traspasa después, la orden sigue a nombre de quien lo trajo |
| `trg_ordenes_alta_cuenta_cobrar` | `INSERT` en `ordenes`, o `UPDATE` de `folio_mercado_publico`, con folio | Abre la cuenta por cobrar de la orden en `PENDIENTE_FACTURA`; antes de facturar, la sigue si el folio cambia, y la revive si estaba anulada por falta de folio |
| `trg_ordenes_anula_cuenta_cobrar` | `UPDATE` de `ordenes.estado` a `ANULADA` | Anula la cuenta si aún no tiene factura |
| `trg_ordenes_quita_folio_cuenta_cobrar` | `UPDATE` de `folio_mercado_publico` a vacío | Igual: anula la cuenta si aún no tiene factura |
| `trg_cuentas_por_cobrar_paga_orden` | `UPDATE` de `cuentas_por_cobrar.estado` a `PAGADA`, con orden | Pasa `ordenes.estado_pago` a `TRUE` |
| `trg_pagos_orden_sin_cuenta` | `INSERT` en `pagos_orden` | Lo rechaza si la orden tiene una cuenta por cobrar no anulada: ese pago se registra en Finanzas |
| `trg_pagos_cobro_abono` | `INSERT` en `pagos_cobro` | Rechaza el pago si la cuenta no está `POR_COBRAR`; si los abonos completan el monto, la pasa a `PAGADA` |
| `trg_detalle_ordenes_servicio_publico` | `INSERT` en `detalle_ordenes` de un servicio con `precio_variable` | Lo rechaza si la orden no tiene folio de Mercado Público, si la cantidad no es 1 o si la orden ya lo tiene |
| `trg_ordenes_folio_servicio_publico` | `UPDATE` de `folio_mercado_publico` a vacío | Lo rechaza si la orden lleva el servicio de precio variable: primero se quita la línea |
| `trg_pagos_proveedor_abono` | `INSERT` en `pagos_proveedor` | Igual, para `facturas_proveedor` (`PENDIENTE` → `PAGADA`) |
| `trg_*_updated_at` | `UPDATE` en `usuarios`, `clientes`, `vehiculos`, `productos`, `cuentas_por_cobrar`, `facturas_proveedor` | Refresca `updated_at` |

`trg_pagos_orden_estado` sigue la misma idea que los de stock: la pantalla registra
el hecho (un abono) y la base mantiene el saldo derivado. `estado_pago` no se escribe
a mano en una orden ya guardada; si lo hiciera la pantalla, la insignia del historial
y la caja podrían decir cosas distintas. Las órdenes migradas son la excepción: vienen
marcadas como pagadas sin abonos detrás, porque el sistema antiguo no los guardaba.

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
| `detalle_orden_un_item` | Una línea de orden sin producto ni servicio, o con ambos |
| `origen_movimiento_valido` | Un movimiento de Kardex que no calce con su origen (una `SALIDA_VENTA` sin venta, o con orden) |
| `cantidad_movida <> 0` | Movimientos vacíos |
| `UNIQUE` en `clientes.rut`, `vehiculos.patente`, `numero_boleta` | Duplicados |
| `empresa_con_rut` | Una empresa o servicio público sin RUT, a quien después no se le puede facturar |
| `rut_no_vacio` | Guardar `''` en vez de `NULL`, que rompería el `UNIQUE` al segundo cliente sin RUT |
| `flyer_con_folio` | Un descuento de flyer sin folio, o un folio sin flyer |
| `flyer_de_un_solo_uso` (índice único parcial) | Usar el mismo flyer en dos órdenes no anuladas |
| `cuenta_cobrar_estado_coherente` | Una cuenta `POR_COBRAR` o `PAGADA` sin factura, neto o IVA; o `PENDIENTE_FACTURA` con factura |
| `cuenta_cobrar_con_origen` | Una cuenta sin orden que no sea una factura completa con su cliente |
| `factura_proveedor_unica` | La misma factura de un proveedor dos veces (entre proveedores distintos el número sí puede repetirse) |
| `vencimiento_posterior_a_la_compra` | Una factura de proveedor que vence antes de haberse comprado |
| `CHECK` de `medio_pago` | Un medio que no sea `EFECTIVO`, `TARJETA` o `TRANSFERENCIA`: la caja cuenta el efectivo por este valor |

El CHECK de stock no negativo es el que hace el trabajo pesado: al ser el trigger
parte de la misma transacción que el `INSERT` del detalle, un intento de sobreventa
revierte el detalle, el descuento y el movimiento de Kardex de una sola vez. No queda
media venta registrada.

Los RUT se guardan siempre formateados (`12.345.678-5`) por [`src/rut.py`](../src/rut.py).
Sin normalizar, `123456785` y `12.345.678-5` entrarían como dos clientes distintos y el
`UNIQUE` no serviría de nada.

### El RUT es opcional

A las personas no se les pide RUT: en el mesón no lo dan y frenaba la atención. Solo
las empresas y los servicios públicos lo necesitan, y ahí lo exige `empresa_con_rut`.
Un cliente sin RUT guarda `NULL`, **nunca** cadena vacía: `NULL` no choca contra el
`UNIQUE`, pero dos cadenas vacías sí. Bases creadas antes de este cambio se ponen al
día con:

```sql
ALTER TABLE "clientes" ALTER COLUMN "rut" DROP NOT NULL;
ALTER TABLE "clientes" ADD CONSTRAINT "rut_no_vacio" CHECK ("rut" <> '');
ALTER TABLE "clientes" ADD CONSTRAINT "empresa_con_rut"
  CHECK ("tipo_cliente" <> 'EMPRESA' OR "rut" IS NOT NULL);
```

## Precios e IVA

Los precios del catálogo (`productos.precio_venta`, `servicios.precio_venta`)
son **netos**. El IVA se calcula al cobrar con [`src/precios.py`](../src/precios.py)
y queda guardado en el documento: `ordenes.impuesto` y `ventas.impuesto`. Así
el historial no depende de la tasa vigente y una factura puede desglosarse sin
recalcular nada.

- `ordenes`: `total_final = subtotal − descuento + impuesto + ajuste_redondeo`, con `subtotal` neto.
- `ventas`: `total_final = neto + impuesto + ajuste_redondeo`; el neto se obtiene restando.

`ajuste_redondeo` es la ley de redondeo a la decena (de −5 a +4). Se aplica a
todo pago, no solo al efectivo: decisión del taller.

Los descuentos por convenio (flyer 10 %, gremio/sindicato 15 %) guardan sus pesos
en `descuento_monto` y cuál fue en `convenio` y `folio_flyer`. Qué categorías
entran está en [`src/convenios.py`](../src/convenios.py).

Es la misma convención del sistema antiguo, cuyos datos migrados traen las
tres cifras por separado.

## Una orden abierta es un auto que sigue en el taller

`ordenes.estado` vale `ABIERTA`, `ENTREGADA` o `ANULADA`. Varios autos pueden
estar adentro a la vez: la orden se guarda abierta, se retoma y se entrega
cuando el trabajo termina. El `DEFAULT 'ENTREGADA'` cierra todo lo que existía
antes de la columna, que es lo que es.

**Una orden abierta ya descontó su stock.** El trigger de descuento corre al
insertar la línea, y eso es lo correcto: el mecánico sacó el aceite de la
repisa cuando lo usó, no cuando el cliente pagó. De ahí sale la simetría que
faltaba: quitar una línea —o anular la orden entera— la borra, y
`trg_detalle_ordenes_devolucion` devuelve el stock con su `DEVOLUCION_ORDEN` en
el Kardex, apuntando a la orden de la que volvió. Retomar una orden no reinserta
sus líneas: las que ya están guardadas viajan marcadas con su id.

Una orden anulada **no se borra**: el auto entró al taller y eso pasó. Queda en
el historial, y los reportes de ingresos y de productos la excluyen, porque el
trabajo no se hizo.

## La caja chica no tiene tabla de cajas

El día de una caja es su fecha. No hay fila de "caja", ni estado abierta/cerrada,
ni nada que alguien pueda dejar abierto un viernes: la caja del día abre y cierra
sola porque el calendario avanza.

`movimientos_caja` guarda **solo lo que no está en otra parte**: la plata contada
en la mañana (`APERTURA`, una vigente por día), lo que se agrega (`INGRESO`) y lo
que se saca (`EGRESO`). Lo que entra por una venta o por el pago de una orden **no
se copia**: se suma de `ventas` y `pagos_orden`, que ya lo tienen, y solo si
`medio_pago = 'EFECTIVO'`.

```
DEBE HABER EN CAJA = apertura + (efectivo cobrado + agregado) − salidas
```

Dos registros del mismo dinero es la forma más segura de terminar con dos cifras
que no cuadran, y es exactamente el problema que el sistema anterior tenía con el
stock. `monto` siempre es positivo; el signo lo dice `tipo`. Una fila mal tecleada
no se borra: se anula insertando su inversa con `anula_id` apuntando a ella, igual
que un `AJUSTE_MANUAL` corrige un stock.

Lo cobrado con tarjeta o transferencia se informa aparte y no entra a la cuenta.
Las órdenes migradas no traen pagos detrás, porque el sistema viejo no los
guardaba: un día de 2024 se ve con entradas en $0.

## Cuentas por cobrar y por pagar

**El costo se congela en la línea.** `detalle_ordenes.costo_unitario` (y el de
`detalle_ventas`) lo copia el trigger desde `productos.precio_costo` al insertar,
y no vuelve a moverse: si el costo del producto cambia mañana, el margen de lo ya
vendido sigue siendo el de ese día. `NULL` significa *sin dato* (los servicios y
todo lo guardado antes de la columna), y un margen sin dato no se muestra como
cero. Como el trigger escribe por fuera del objeto, hay que hacer `db.refresh()`
para verlo, igual que con el stock.

**La cuenta por cobrar nace sola y se completa a mano.** Toda orden con folio de
Mercado Público abre su cuenta en `PENDIENTE_FACTURA`: el auto se atiende un día y
se factura otro. Una persona ingresa el N° y la fecha de la factura
(`finanzas.registrar_factura`), y ahí pasan a `POR_COBRAR` y se **congelan** el
neto, el IVA y el costo: desde ese momento la cuenta no lee la orden, y editarla
no mueve lo facturado. Solo cuenta lo que pasa desde que existe el trigger; las
órdenes anteriores no generan cuenta, y lo pendiente de antes se ingresa a mano
(`finanzas.crear_cuenta_manual`), con un costo opcional.

- **Monto facturado** = `venta_neto + iva`, exacto. No lleva el `ajuste_redondeo` de
  la orden: la ley de redondeo es de la caja, y la factura al organismo va al peso.
  El neto sale de `total_final − impuesto − ajuste_redondeo`, que es lo que la
  orden ya calculó con su descuento.
- **Margen** = `venta_neto − costo`; en porcentaje, sobre la venta neto.
- **Una factura que cubre dos órdenes** repite su número en cada cuenta; no hay
  tabla de facturas que las agrupe.
- **Anular la orden** anula la cuenta solo si aún no tiene factura. Con factura
  emitida, deshacerla es una nota de crédito y lo decide una persona. Quitarle el
  folio hace lo mismo, y ponérselo de nuevo la revive.
- **La orden se paga en Finanzas.** Una orden con cuenta por cobrar no admite
  abonos en `pagos_orden`: entrarían a la caja del día y la cuenta seguiría por
  cobrar. Cuando la cuenta queda `PAGADA`, la orden pasa a pagada.
- **El listado muestra la cuenta al entregar la orden.** Mientras la orden sigue
  `ABIERTA` su cuenta existe, pero `finanzas.cuentas_por_cobrar` no la devuelve:
  todavía no hay nada que facturar.

**Los abonos deciden el estado**, como en las órdenes: `pagos_cobro` y
`pagos_proveedor` solo se agregan, y el trigger pasa la cuenta a `PAGADA` cuando lo
abonado alcanza el monto. Un pago sobre una cuenta que no está por cobrar se
rechaza. Un pago *de más* no: los organismos a veces pagan distinto por
retenciones, y ese caso lo resuelve una persona.

**Las cuentas por pagar se ingresan a mano.** La entrada de mercadería del Kardex
no las genera. `fecha_vencimiento` se guarda en vez de calcularse, porque cada
proveedor da su plazo y es contra él que se mide la mora; `proveedores.plazo_credito_dias`
solo sugiere el valor al ingresar la factura.

**El Servicio Público es un servicio de precio libre.** `servicios.precio_variable`
marca al único servicio (índice único parcial) cuyo precio se escribe en cada
orden en vez de salir del catálogo; el catálogo de la pantalla no lo ofrece, se
agrega con su propio botón y solo en órdenes con folio de Mercado Público. Sirve
para que el total de la orden cuadre con el presupuesto, que se arma fuera del
sistema. No tiene costo (`costo_unitario` queda en `NULL`, como todo servicio),
así que en la cuenta por cobrar es margen puro. `detalle_ordenes.descripcion`
guarda el texto libre de la línea. La cuenta por cobrar sale por
`venta_neto + iva` exactos, sin el redondeo de caja, así que la factura coincide
con el presupuesto aunque el efectivo difiera hasta $5.

## Vistas

`vw_stock_critico` lista los productos activos con `stock_actual <= stock_minimo`. La
aplicación la consulta en vez de repetir el criterio: si mañana el umbral cambia, se
cambia en un solo lugar.

## Cambios de esquema

Hay datos reales en producción: recrear la base dejó de ser una opción. Un cambio
de esquema son **tres cosas que van juntas**, y hay pruebas que lo verifican:

1. La tabla o columna en `database/schema_lubriexpress.sql` — sigue siendo la verdad.
2. Su modelo en `src/models.py` — `tests/test_models.py` falla si no calzan.
3. Un paso en `scripts/actualizar.py` — `tests/test_actualizar.py` falla si lo que
   crea el paso no es lo que declara el esquema.

Sin el tercero, una instalación nueva y una actualizada quedan distintas, y la
diferencia no la mira ninguna prueba hasta que algo se rompe en el taller.

El actualizador corre así, junto al ejecutable en el PC del taller:

```
actualizar.exe --simular    # dice qué haría, sin escribir nada
actualizar.exe              # respalda, aplica y verifica los conteos
```

Cada paso mira la base antes de actuar, así que correrlo dos veces no hace daño.
El respaldo va primero y su fallo aborta todo. Si la verificación no cuadra, el
camino de vuelta es `restaurar.py` con el archivo que el propio actualizador dejó.

Está probado contra una base con los datos reales migrados: la estructura resultante
es idéntica a la de una instalación limpia desde el `.sql`. (Un `pg_dump` re-escribe
los `CHECK ... = ANY (ARRAY[...])` con otra sintaxis equivalente, así que una base
restaurada muestra esa diferencia cosmética contra una cargada directo del `.sql`.)

Sigue pendiente Alembic: la lista de pasos va a mano y solo hacia adelante. Mientras
sean unos pocos cambios aditivos alcanza; el día que haya que revertir uno, toca.

Bases creadas antes de servicios, IVA y las columnas extra del vehículo se
ponen al día con:

```sql
ALTER TABLE "vehiculos"
  ADD COLUMN "tipo" VARCHAR(30),
  ADD COLUMN "version" VARCHAR(50),
  ADD COLUMN "vin" VARCHAR(20),
  ADD COLUMN "numero_motor" VARCHAR(30);
CREATE TABLE "servicios" (
  "id" SERIAL PRIMARY KEY,
  "nombre" VARCHAR(100) NOT NULL,
  "categoria" VARCHAR(50),
  "precio_venta" DECIMAL(10,2) NOT NULL CHECK ("precio_venta" >= 0),
  "activo" BOOLEAN NOT NULL DEFAULT TRUE
);
ALTER TABLE "ordenes" ADD COLUMN "impuesto" DECIMAL(10,2) NOT NULL DEFAULT 0 CHECK ("impuesto" >= 0);
ALTER TABLE "ventas" ADD COLUMN "impuesto" DECIMAL(10,2) NOT NULL DEFAULT 0 CHECK ("impuesto" >= 0);
ALTER TABLE "detalle_ordenes"
  ALTER COLUMN "producto_id" DROP NOT NULL,
  ADD COLUMN "servicio_id" INT REFERENCES "servicios"("id"),
  ADD CONSTRAINT "detalle_orden_un_item" CHECK (("producto_id" IS NULL) <> ("servicio_id" IS NULL));
CREATE INDEX idx_detalle_ordenes_servicio ON "detalle_ordenes"("servicio_id");
ALTER TABLE "ordenes" ALTER COLUMN "kilometraje_ingreso" DROP NOT NULL;
DROP TRIGGER trg_detalle_ordenes_descuento ON "detalle_ordenes";
CREATE TRIGGER trg_detalle_ordenes_descuento
  AFTER INSERT ON "detalle_ordenes"
  FOR EACH ROW
  WHEN (NEW."producto_id" IS NOT NULL)
  EXECUTE FUNCTION fn_descontar_stock_orden();
```

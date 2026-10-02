-- =====================================================================
-- Sistema de Gestión de Taller, Inventario y Ventas — Lubri-Express
-- Esquema de Base de Datos (PostgreSQL)
-- =====================================================================

-- ---------------------------------------------------------------------
-- Tabla de Usuarios
-- ---------------------------------------------------------------------
CREATE TABLE "usuarios" (
  "id" SERIAL PRIMARY KEY,
  "nombre" VARCHAR(100) NOT NULL,
  "username" VARCHAR(50) UNIQUE NOT NULL,
  "password_hash" VARCHAR(255) NOT NULL,
  "rol" VARCHAR(20) NOT NULL
      CHECK ("rol" IN ('ADMINISTRADOR', 'SUPERVISOR', 'USUARIO_NORMAL')),
  "activo" BOOLEAN NOT NULL DEFAULT TRUE,
  "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updated_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------
-- Tabla de Clientes
-- ---------------------------------------------------------------------
CREATE TABLE "clientes" (
  "id" SERIAL PRIMARY KEY,
  -- A las personas no se les pide el RUT: en el mesón no lo dan y frenaba la
  -- atención. Las empresas y los servicios públicos sí lo necesitan, porque sin
  -- RUT no se les puede facturar.
  "rut" VARCHAR(12) UNIQUE,
  "nombre_completo" VARCHAR(150) NOT NULL,
  "tipo_cliente" VARCHAR(20) NOT NULL DEFAULT 'PERSONA'
      CHECK ("tipo_cliente" IN ('PERSONA', 'EMPRESA')),
  "telefono" VARCHAR(15),
  "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updated_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  -- Sin RUT se guarda NULL, nunca ''. NULL no choca contra el UNIQUE, dos
  -- cadenas vacías sí, y el segundo cliente sin RUT sería imposible de crear.
  CONSTRAINT "rut_no_vacio" CHECK ("rut" <> ''),
  CONSTRAINT "empresa_con_rut" CHECK ("tipo_cliente" <> 'EMPRESA' OR "rut" IS NOT NULL)
);

-- ---------------------------------------------------------------------
-- Tabla de Vehículos
-- ---------------------------------------------------------------------
CREATE TABLE "vehiculos" (
  "id" SERIAL PRIMARY KEY,
  "cliente_id" INT NOT NULL REFERENCES "clientes"("id"),
  "patente" VARCHAR(10) UNIQUE NOT NULL,
  "marca" VARCHAR(50),
  "modelo" VARCHAR(50),
  "anio_fabricacion" INT,
  "color" VARCHAR(30),
  "transmision" VARCHAR(20),
  "cilindrada" VARCHAR(20),
  "traccion" VARCHAR(20),
  "combustible" VARCHAR(20),
  -- Vienen del sistema antiguo y se guardan tal cual: "version" trae lo que
  -- cada operador anotó ("1.6", "DIESEL", "LX"), no se interpreta.
  "tipo" VARCHAR(30),
  "version" VARCHAR(50),
  "vin" VARCHAR(20),
  "numero_motor" VARCHAR(30),
  "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updated_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------
-- Tabla de Ubicaciones
-- ---------------------------------------------------------------------
CREATE TABLE "ubicaciones" (
  "id" SERIAL PRIMARY KEY,
  "descripcion" VARCHAR(100) NOT NULL
);

-- ---------------------------------------------------------------------
-- Tabla de Productos (Inventario)
-- ---------------------------------------------------------------------
CREATE TABLE "productos" (
  "id" SERIAL PRIMARY KEY,
  "ubicacion_id" INT REFERENCES "ubicaciones"("id"),
  "nombre" VARCHAR(100) NOT NULL,
  "marca" VARCHAR(50),
  "categoria" VARCHAR(50),
  "descripcion" TEXT,
  "precio_costo" DECIMAL(10,2) NOT NULL CHECK ("precio_costo" >= 0),
  -- Neto, sin IVA. El IVA (19 %) se calcula al cobrar y queda guardado en el
  -- documento (ordenes.impuesto / ventas.impuesto), no en el catálogo.
  "precio_venta" DECIMAL(10,2) NOT NULL CHECK ("precio_venta" >= 0),
  "stock_actual" INT NOT NULL DEFAULT 0 CHECK ("stock_actual" >= 0),
  "stock_minimo" INT NOT NULL DEFAULT 0 CHECK ("stock_minimo" >= 0),
  "activo" BOOLEAN NOT NULL DEFAULT TRUE,
  "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updated_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------
-- Tabla de Servicios (mano de obra: cambio de aceite, scanner, revisión)
-- ---------------------------------------------------------------------
-- Se cobran en una orden igual que un producto, pero no tienen stock ni
-- pasan por el Kardex. Por eso son una tabla aparte y no un producto con un
-- flag: así el trigger de descuento no tiene que aprender a no disparar.
CREATE TABLE "servicios" (
  "id" SERIAL PRIMARY KEY,
  "nombre" VARCHAR(100) NOT NULL,
  "categoria" VARCHAR(50),
  "precio_venta" DECIMAL(10,2) NOT NULL CHECK ("precio_venta" >= 0),
  "activo" BOOLEAN NOT NULL DEFAULT TRUE,
  -- El precio se escribe en cada orden en vez de salir del catálogo. Hoy solo
  -- lo usa el Servicio Público de Mercado Público, que existe una vez (índice
  -- de abajo) y sirve para cuadrar la orden con el presupuesto.
  "precio_variable" BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE UNIQUE INDEX servicio_de_precio_variable_unico ON "servicios"("precio_variable")
  WHERE "precio_variable";
INSERT INTO "servicios" ("nombre", "categoria", "precio_venta", "activo", "precio_variable")
  SELECT 'Servicio Público', 'Mercado Público', 0, TRUE, TRUE
  WHERE NOT EXISTS (SELECT 1 FROM "servicios" WHERE "precio_variable");

-- ---------------------------------------------------------------------
-- Tabla de Mecánicos
-- ---------------------------------------------------------------------
-- Quien trabajó el auto, que no siempre es quien registró la orden: hay
-- mecánicos sin cuenta en el sistema. Sin login, solo el nombre que sale en la
-- orden y su PDF. Se desactivan en vez de borrarse, porque tienen órdenes.
CREATE TABLE "mecanicos" (
  "id" SERIAL PRIMARY KEY,
  "nombre" VARCHAR(100) NOT NULL UNIQUE,
  "activo" BOOLEAN NOT NULL DEFAULT TRUE
);

-- ---------------------------------------------------------------------
-- Tabla de Órdenes de Trabajo
-- ---------------------------------------------------------------------
CREATE TABLE "ordenes" (
  "id" SERIAL PRIMARY KEY,
  "vehiculo_id" INT NOT NULL REFERENCES "vehiculos"("id"),
  "usuario_id" INT NOT NULL REFERENCES "usuarios"("id"),
  "folio_mercado_publico" VARCHAR(50),
  "fecha_creacion" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  -- La pantalla lo exige (es con lo que se calcula el próximo servicio);
  -- admite NULL solo por el historial migrado, que no siempre lo traía.
  "kilometraje_ingreso" INT CHECK ("kilometraje_ingreso" >= 0),
  "descuento_porcentaje" DECIMAL(5,2) NOT NULL DEFAULT 0 CHECK ("descuento_porcentaje" >= 0),
  "descuento_monto" DECIMAL(10,2) NOT NULL DEFAULT 0 CHECK ("descuento_monto" >= 0),
  -- subtotal es neto; total_final = subtotal - descuento + impuesto + ajuste.
  "subtotal" DECIMAL(10,2) NOT NULL DEFAULT 0,
  "impuesto" DECIMAL(10,2) NOT NULL DEFAULT 0 CHECK ("impuesto" >= 0),
  "total_final" DECIMAL(10,2) NOT NULL DEFAULT 0,
  "numero_boleta" VARCHAR(50) UNIQUE,
  "estado_pago" BOOLEAN NOT NULL DEFAULT FALSE,
  "notas" TEXT,
  -- En qué va el trabajo, que no es lo mismo que el pago. Una orden ABIERTA es
  -- un auto que sigue en el taller: se le pueden agregar líneas y se entrega
  -- después. El default cierra todo lo que ya existía, que es lo que es. Va al
  -- final porque ALTER TABLE solo sabe agregar ahí: así una base actualizada y
  -- una recién instalada quedan iguales hasta en el orden de las columnas.
  "estado" VARCHAR(20) NOT NULL DEFAULT 'ENTREGADA'
      CHECK ("estado" IN ('ABIERTA', 'ENTREGADA', 'ANULADA')),
  "ajuste_redondeo" DECIMAL(10,2) NOT NULL DEFAULT 0,
  -- Descuento por convenio (src/convenios.py). Los pesos van en
  -- descuento_monto; acá queda cuál fue y el folio del flyer.
  "convenio" VARCHAR(20) CHECK ("convenio" IN ('FLYER', 'GREMIO')),
  "folio_flyer" INT CHECK ("folio_flyer" BETWEEN 1 AND 1000),
  -- La pantalla lo exige; NULL en las órdenes guardadas antes de que existiera.
  "mecanico_id" INT REFERENCES "mecanicos"("id"),
  -- A quién se le hizo. Lo copia fn_congelar_cliente del dueño del vehículo y
  -- no se mueve más: un auto vendido cambia de dueño, sus órdenes no. El NOT
  -- NULL va al final para que el paso de actualizar.py lo reproduzca tal cual.
  "cliente_id" INT REFERENCES "clientes"("id") NOT NULL,
  CONSTRAINT descuento_exclusivo_orden
      CHECK (NOT ("descuento_porcentaje" > 0 AND "descuento_monto" > 0)),
  CONSTRAINT flyer_con_folio
      CHECK (("folio_flyer" IS NOT NULL) = ("convenio" IS NOT DISTINCT FROM 'FLYER'))
);

-- ---------------------------------------------------------------------
-- Tabla Detalle de Órdenes (Productos y Servicios por Orden)
-- ---------------------------------------------------------------------
-- Cada línea es un producto o un servicio, nunca ambos ni ninguno. Solo las
-- líneas de producto descuentan stock (ver el WHEN del trigger).
CREATE TABLE "detalle_ordenes" (
  "id" SERIAL PRIMARY KEY,
  "orden_id" INT NOT NULL REFERENCES "ordenes"("id"),
  "producto_id" INT REFERENCES "productos"("id"),
  "servicio_id" INT REFERENCES "servicios"("id"),
  "cantidad" INT NOT NULL CHECK ("cantidad" > 0),
  "precio_unitario_cobrado" DECIMAL(10,2) NOT NULL CHECK ("precio_unitario_cobrado" >= 0),
  -- Lo que costaba el producto al momento de la orden. Lo copia el trigger
  -- fn_congelar_costo desde productos.precio_costo, y no vuelve a moverse: si
  -- el costo cambia mañana, el margen de esta orden sigue siendo el de hoy.
  -- NULL en las líneas de servicio (la mano de obra no tiene costo de bodega)
  -- y en todo lo guardado antes de que existiera esta columna: ahí el margen
  -- es "sin dato", no cero.
  "costo_unitario" DECIMAL(10,2) CHECK ("costo_unitario" >= 0),
  -- Texto libre de la línea. Lo usa el Servicio Público para decir qué se hizo
  -- (el presupuesto vive fuera del sistema); en el resto queda vacío.
  "descripcion" VARCHAR(150) CHECK ("descripcion" <> ''),
  CONSTRAINT "detalle_orden_un_item"
      CHECK (("producto_id" IS NULL) <> ("servicio_id" IS NULL))
);

-- ---------------------------------------------------------------------
-- Tabla de Pagos de una Orden (abonos) — append-only
-- ---------------------------------------------------------------------
-- Una orden se paga por partes: un abono al dejar el auto y el saldo al
-- retirarlo. Cada abono es una fila y nadie las edita; lo pagado es la suma.
-- "ordenes.estado_pago" no se escribe a mano desde la pantalla: lo recalcula
-- el trigger de más abajo, igual que el stock lo mueven los suyos.
CREATE TABLE "pagos_orden" (
  "id" SERIAL PRIMARY KEY,
  "orden_id" INT NOT NULL REFERENCES "ordenes"("id"),
  "usuario_id" INT NOT NULL REFERENCES "usuarios"("id"),
  "monto" DECIMAL(10,2) NOT NULL CHECK ("monto" > 0),
  "fecha_pago" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "medio_pago" VARCHAR(20) NOT NULL DEFAULT 'EFECTIVO'
      CHECK ("medio_pago" IN ('EFECTIVO', 'TARJETA', 'TRANSFERENCIA'))
);

-- ---------------------------------------------------------------------
-- Tabla de Ventas (Mostrador)
-- ---------------------------------------------------------------------
CREATE TABLE "ventas" (
  "id" SERIAL PRIMARY KEY,
  "usuario_id" INT NOT NULL REFERENCES "usuarios"("id"),
  "cliente_id" INT REFERENCES "clientes"("id"),
  "fecha_venta" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "numero_boleta" VARCHAR(50) UNIQUE,
  -- total_final = neto + impuesto + ajuste; el neto se obtiene restando.
  "impuesto" DECIMAL(10,2) NOT NULL DEFAULT 0 CHECK ("impuesto" >= 0),
  "total_final" DECIMAL(10,2) NOT NULL CHECK ("total_final" >= 0),
  "ajuste_redondeo" DECIMAL(10,2) NOT NULL DEFAULT 0,
  "medio_pago" VARCHAR(20) NOT NULL DEFAULT 'EFECTIVO'
      CHECK ("medio_pago" IN ('EFECTIVO', 'TARJETA', 'TRANSFERENCIA'))
);

-- ---------------------------------------------------------------------
-- Tabla Detalle de Ventas (Productos por Venta)
-- ---------------------------------------------------------------------
CREATE TABLE "detalle_ventas" (
  "id" SERIAL PRIMARY KEY,
  "venta_id" INT NOT NULL REFERENCES "ventas"("id"),
  "producto_id" INT NOT NULL REFERENCES "productos"("id"),
  "cantidad" INT NOT NULL CHECK ("cantidad" > 0),
  "precio_unitario_cobrado" DECIMAL(10,2) NOT NULL CHECK ("precio_unitario_cobrado" >= 0),
  -- Igual que en detalle_ordenes: el costo del momento, copiado por el trigger.
  "costo_unitario" DECIMAL(10,2) CHECK ("costo_unitario" >= 0)
);

-- ---------------------------------------------------------------------
-- Tabla del Kardex (Historial de Movimientos) — append-only
-- ---------------------------------------------------------------------
CREATE TABLE "kardex_movimientos" (
  "id" SERIAL PRIMARY KEY,
  "producto_id" INT NOT NULL REFERENCES "productos"("id"),
  "usuario_id" INT NOT NULL REFERENCES "usuarios"("id"),
  "tipo_movimiento" VARCHAR(20) NOT NULL
      CHECK ("tipo_movimiento" IN ('ENTRADA', 'SALIDA_VENTA', 'SALIDA_ORDEN',
                                   'AJUSTE_MANUAL', 'DEVOLUCION_ORDEN')),
  "cantidad_movida" INT NOT NULL CHECK ("cantidad_movida" <> 0),
  "stock_resultante" INT NOT NULL CHECK ("stock_resultante" >= 0),
  "orden_id" INT REFERENCES "ordenes"("id"),
  "venta_id" INT REFERENCES "ventas"("id"),
  "fecha_movimiento" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  -- Lo que costó esa compra, para el histórico de precios del proveedor.
  -- Nullable: las salidas por venta u orden, los ajustes por recuento y todo
  -- lo registrado antes de que existiera esta columna no traen costo.
  "costo_unitario" DECIMAL(10,2) CHECK ("costo_unitario" >= 0),
  CONSTRAINT origen_movimiento_valido
      CHECK (
        ("tipo_movimiento" IN ('SALIDA_ORDEN', 'DEVOLUCION_ORDEN') AND "orden_id" IS NOT NULL AND "venta_id" IS NULL) OR
        ("tipo_movimiento" = 'SALIDA_VENTA' AND "venta_id" IS NOT NULL AND "orden_id" IS NULL) OR
        ("tipo_movimiento" IN ('ENTRADA', 'AJUSTE_MANUAL') AND "orden_id" IS NULL AND "venta_id" IS NULL)
      )
);

-- ---------------------------------------------------------------------
-- Tabla de Movimientos de Caja (caja chica del día) — append-only
-- ---------------------------------------------------------------------
-- El efectivo que entra y sale del cajón de la oficina sin pasar por una
-- venta: la plata que se deja en la mañana para dar vuelto y los gastos del
-- día. Lo que sí viene de una venta o de un abono no se copia acá; se suma
-- de "ventas" y "pagos_orden", que ya lo tienen. Dos registros del mismo
-- dinero es la forma más segura de terminar con dos cifras distintas.
--
-- No hay tabla de cajas ni estado abierta/cerrada: el día de una caja es su
-- fecha, así que abre y cierra sola. Una fila mal tecleada no se borra: se
-- anula con su inversa, igual que en "kardex_movimientos" y "pagos_orden".
CREATE TABLE "movimientos_caja" (
  "id" SERIAL PRIMARY KEY,
  "usuario_id" INT NOT NULL REFERENCES "usuarios"("id"),
  -- APERTURA es la plata con que parte el día, contada en la mañana; INGRESO
  -- y EGRESO, lo que se agrega o se saca después.
  "tipo" VARCHAR(10) NOT NULL CHECK ("tipo" IN ('APERTURA', 'INGRESO', 'EGRESO')),
  -- El signo lo dice "tipo"; el monto siempre es positivo.
  "monto" DECIMAL(10,2) NOT NULL CHECK ("monto" > 0),
  "motivo" VARCHAR(200) NOT NULL,
  "fecha" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  -- El movimiento que esta fila anula. UNIQUE: nadie anula dos veces el mismo.
  "anula_id" INT UNIQUE REFERENCES "movimientos_caja"("id")
);

-- ---------------------------------------------------------------------
-- Historial de Precios de Venta — append-only
-- ---------------------------------------------------------------------
-- El costo de cada compra queda en su entrada del Kardex; el precio de venta
-- no pasa por ahí. Cada cambio deja una fila: de cuánto a cuánto y quién. Lo
-- escribe la aplicación (Producto.fijar_precio_venta), que es la que sabe qué
-- usuario tiene la sesión.
CREATE TABLE "cambios_precio" (
  "id" SERIAL PRIMARY KEY,
  "producto_id" INT NOT NULL REFERENCES "productos"("id"),
  "usuario_id" INT NOT NULL REFERENCES "usuarios"("id"),
  "precio_anterior" DECIMAL(10,2) NOT NULL CHECK ("precio_anterior" >= 0),
  "precio_nuevo" DECIMAL(10,2) NOT NULL CHECK ("precio_nuevo" >= 0),
  "fecha" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------
-- Tabla de Cuentas por Cobrar (facturas de Mercado Público y afines)
-- ---------------------------------------------------------------------
-- Toda orden con folio de Mercado Público abre su cuenta sola (trigger de más
-- abajo), en PENDIENTE_FACTURA: el auto se atiende un día y se factura otro, y
-- el N° y la fecha de la factura los ingresa una persona cuando la emite en el
-- SII. Al registrarlos pasa a POR_COBRAR y se congelan neto, IVA y costo, para
-- que lo que se cobra no dependa de lo que se edite después en la orden.
-- Sin orden_id es una cuenta ingresada a mano (deudas anteriores al módulo):
-- nace ya facturada y su costo, si lo hay, se escribe.
--
-- venta_neto - costo = margen; venta_neto + iva = lo que se factura, exacto,
-- sin el redondeo a la decena de la ley de redondeo (que es de la caja).
-- Varias cuentas pueden llevar el mismo N° de factura: una factura que cubre
-- dos órdenes se repite en cada una, no se agrupa.
CREATE TABLE "cuentas_por_cobrar" (
  "id" SERIAL PRIMARY KEY,
  "orden_id" INT UNIQUE REFERENCES "ordenes"("id"),
  "usuario_id" INT REFERENCES "usuarios"("id"),
  "cliente_nombre" VARCHAR(150),
  "numero_oc" VARCHAR(50),
  "numero_factura" VARCHAR(50),
  "fecha_factura" DATE,
  "venta_neto" DECIMAL(10,2) CHECK ("venta_neto" >= 0),
  "iva" DECIMAL(10,2) CHECK ("iva" >= 0),
  -- NULL es "sin dato" (margen desconocido); 0 es un servicio sin costo.
  "costo" DECIMAL(10,2) CHECK ("costo" >= 0),
  "estado" VARCHAR(20) NOT NULL DEFAULT 'PENDIENTE_FACTURA'
      CHECK ("estado" IN ('PENDIENTE_FACTURA', 'POR_COBRAR', 'PAGADA', 'ANULADA')),
  "observaciones" TEXT,
  "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updated_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT "cuenta_cobrar_con_origen"
      CHECK ("orden_id" IS NOT NULL OR ("cliente_nombre" IS NOT NULL
             AND "numero_factura" IS NOT NULL AND "venta_neto" IS NOT NULL AND "iva" IS NOT NULL)),
  CONSTRAINT "cuenta_cobrar_estado_coherente"
      CHECK (("estado" = 'PENDIENTE_FACTURA' AND "numero_factura" IS NULL AND "fecha_factura" IS NULL)
             OR ("estado" IN ('POR_COBRAR', 'PAGADA') AND "numero_factura" IS NOT NULL
                 AND "fecha_factura" IS NOT NULL AND "venta_neto" IS NOT NULL AND "iva" IS NOT NULL)
             OR "estado" = 'ANULADA'),
  CONSTRAINT "cuenta_cobrar_sin_vacios"
      CHECK ("cliente_nombre" <> '' AND "numero_oc" <> '' AND "numero_factura" <> '')
);

-- ---------------------------------------------------------------------
-- Tabla de Pagos de una Cuenta por Cobrar (abonos) — append-only
-- ---------------------------------------------------------------------
-- Igual que pagos_orden: cada pago es una fila, nadie las edita, y lo pagado
-- es la suma. El trigger de más abajo pasa la cuenta a PAGADA al completarla.
CREATE TABLE "pagos_cobro" (
  "id" SERIAL PRIMARY KEY,
  "cuenta_id" INT NOT NULL REFERENCES "cuentas_por_cobrar"("id"),
  "usuario_id" INT NOT NULL REFERENCES "usuarios"("id"),
  "monto" DECIMAL(10,2) NOT NULL CHECK ("monto" > 0),
  "fecha_pago" DATE NOT NULL DEFAULT CURRENT_DATE
);

-- ---------------------------------------------------------------------
-- Tabla de Proveedores
-- ---------------------------------------------------------------------
-- Se desactivan en vez de borrarse, porque tienen facturas.
CREATE TABLE "proveedores" (
  "id" SERIAL PRIMARY KEY,
  "nombre" VARCHAR(150) UNIQUE NOT NULL,
  "rut" VARCHAR(12) UNIQUE,
  -- El crédito que suele dar: sugiere el vencimiento al ingresar una factura.
  "plazo_credito_dias" INT NOT NULL DEFAULT 30 CHECK ("plazo_credito_dias" >= 0),
  "activo" BOOLEAN NOT NULL DEFAULT TRUE,
  CONSTRAINT "proveedor_rut_no_vacio" CHECK ("rut" <> '')
);

-- ---------------------------------------------------------------------
-- Tabla de Facturas de Proveedor (cuentas por pagar)
-- ---------------------------------------------------------------------
-- Se ingresan a mano: la entrada de mercadería del Kardex no las genera.
-- "monto" es el total de la factura, con IVA. El vencimiento se guarda y no se
-- calcula: cada proveedor da su plazo, y es contra él que se mide la mora.
CREATE TABLE "facturas_proveedor" (
  "id" SERIAL PRIMARY KEY,
  "proveedor_id" INT NOT NULL REFERENCES "proveedores"("id"),
  "usuario_id" INT NOT NULL REFERENCES "usuarios"("id"),
  "numero_factura" VARCHAR(50) NOT NULL,
  "fecha_compra" DATE NOT NULL,
  "fecha_vencimiento" DATE NOT NULL,
  "monto" DECIMAL(10,2) NOT NULL CHECK ("monto" > 0),
  "estado" VARCHAR(20) NOT NULL DEFAULT 'PENDIENTE'
      CHECK ("estado" IN ('PENDIENTE', 'PAGADA', 'ANULADA')),
  "observaciones" TEXT,
  "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updated_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT "factura_proveedor_unica" UNIQUE ("proveedor_id", "numero_factura"),
  CONSTRAINT "vencimiento_posterior_a_la_compra"
      CHECK ("fecha_vencimiento" >= "fecha_compra"),
  CONSTRAINT "factura_proveedor_sin_vacios" CHECK ("numero_factura" <> '')
);

-- ---------------------------------------------------------------------
-- Tabla de Pagos a Proveedores (abonos) — append-only
-- ---------------------------------------------------------------------
CREATE TABLE "pagos_proveedor" (
  "id" SERIAL PRIMARY KEY,
  "factura_id" INT NOT NULL REFERENCES "facturas_proveedor"("id"),
  "usuario_id" INT NOT NULL REFERENCES "usuarios"("id"),
  "monto" DECIMAL(10,2) NOT NULL CHECK ("monto" > 0),
  "fecha_pago" DATE NOT NULL DEFAULT CURRENT_DATE
);

-- =====================================================================
-- Índices (Postgres no indexa automáticamente las FK)
-- =====================================================================
CREATE INDEX idx_vehiculos_cliente ON "vehiculos"("cliente_id");
CREATE INDEX idx_productos_ubicacion ON "productos"("ubicacion_id");
CREATE INDEX idx_ordenes_vehiculo ON "ordenes"("vehiculo_id");
CREATE INDEX idx_ordenes_cliente ON "ordenes"("cliente_id");
CREATE INDEX idx_ordenes_usuario ON "ordenes"("usuario_id");
CREATE INDEX idx_ordenes_fecha ON "ordenes"("fecha_creacion");
CREATE INDEX idx_detalle_ordenes_orden ON "detalle_ordenes"("orden_id");
CREATE INDEX idx_detalle_ordenes_producto ON "detalle_ordenes"("producto_id");
CREATE INDEX idx_detalle_ordenes_servicio ON "detalle_ordenes"("servicio_id");
CREATE INDEX idx_ventas_usuario ON "ventas"("usuario_id");
CREATE INDEX idx_ventas_fecha ON "ventas"("fecha_venta");
CREATE INDEX idx_detalle_ventas_venta ON "detalle_ventas"("venta_id");
CREATE INDEX idx_detalle_ventas_producto ON "detalle_ventas"("producto_id");
CREATE INDEX idx_pagos_orden_orden ON "pagos_orden"("orden_id");
CREATE INDEX idx_kardex_producto ON "kardex_movimientos"("producto_id");
CREATE INDEX idx_kardex_fecha ON "kardex_movimientos"("fecha_movimiento");
CREATE INDEX idx_movimientos_caja_fecha ON "movimientos_caja"("fecha");
CREATE INDEX idx_cambios_precio_producto ON "cambios_precio"("producto_id");
CREATE INDEX idx_cuentas_por_cobrar_estado ON "cuentas_por_cobrar"("estado");
CREATE INDEX idx_pagos_cobro_cuenta ON "pagos_cobro"("cuenta_id");
CREATE INDEX idx_facturas_proveedor_proveedor ON "facturas_proveedor"("proveedor_id");
CREATE INDEX idx_facturas_proveedor_estado ON "facturas_proveedor"("estado");
CREATE INDEX idx_pagos_proveedor_factura ON "pagos_proveedor"("factura_id");
-- Un flyer se usa una vez. Anular la orden lo libera: el cliente no lo gastó.
CREATE UNIQUE INDEX flyer_de_un_solo_uso ON "ordenes"("folio_flyer")
  WHERE "estado" <> 'ANULADA';

-- =====================================================================
-- Triggers: updated_at automático
-- =====================================================================
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN
  NEW."updated_at" = CURRENT_TIMESTAMP;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_usuarios_updated_at
  BEFORE UPDATE ON "usuarios"
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_clientes_updated_at
  BEFORE UPDATE ON "clientes"
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_vehiculos_updated_at
  BEFORE UPDATE ON "vehiculos"
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_productos_updated_at
  BEFORE UPDATE ON "productos"
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_cuentas_por_cobrar_updated_at
  BEFORE UPDATE ON "cuentas_por_cobrar"
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_facturas_proveedor_updated_at
  BEFORE UPDATE ON "facturas_proveedor"
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =====================================================================
-- Triggers: descuento automático de stock + registro en kardex
-- =====================================================================

-- --- Salida de stock por Orden de Trabajo ---
CREATE OR REPLACE FUNCTION fn_descontar_stock_orden() RETURNS TRIGGER AS $$
DECLARE
  v_usuario_id INT;
  v_stock_nuevo INT;
BEGIN
  SELECT "usuario_id" INTO v_usuario_id FROM "ordenes" WHERE "id" = NEW."orden_id";

  UPDATE "productos"
     SET "stock_actual" = "stock_actual" - NEW."cantidad"
   WHERE "id" = NEW."producto_id"
   RETURNING "stock_actual" INTO v_stock_nuevo;

  INSERT INTO "kardex_movimientos"
      ("producto_id", "usuario_id", "tipo_movimiento", "cantidad_movida",
       "stock_resultante", "orden_id")
  VALUES
      (NEW."producto_id", v_usuario_id, 'SALIDA_ORDEN', -NEW."cantidad",
       v_stock_nuevo, NEW."orden_id");

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_detalle_ordenes_descuento
  AFTER INSERT ON "detalle_ordenes"
  FOR EACH ROW
  WHEN (NEW."producto_id" IS NOT NULL)  -- las líneas de servicio no mueven stock
  EXECUTE FUNCTION fn_descontar_stock_orden();

-- --- Devolución de stock al quitar una línea de una orden ---
-- Una orden abierta ya descontó: el mecánico sacó el aceite de la repisa. Si
-- después se quita la línea —se cargó de más, o se anula la orden entera— el
-- stock vuelve y queda dicho por qué. Firma el dueño de la orden, igual que la
-- salida: lo que el Kardex responde es de qué orden salió y a cuál volvió.
CREATE OR REPLACE FUNCTION fn_devolver_stock_orden() RETURNS TRIGGER AS $$
DECLARE
  v_usuario_id INT;
  v_stock_nuevo INT;
BEGIN
  SELECT "usuario_id" INTO v_usuario_id FROM "ordenes" WHERE "id" = OLD."orden_id";

  UPDATE "productos"
     SET "stock_actual" = "stock_actual" + OLD."cantidad"
   WHERE "id" = OLD."producto_id"
   RETURNING "stock_actual" INTO v_stock_nuevo;

  INSERT INTO "kardex_movimientos"
      ("producto_id", "usuario_id", "tipo_movimiento", "cantidad_movida",
       "stock_resultante", "orden_id")
  VALUES
      (OLD."producto_id", v_usuario_id, 'DEVOLUCION_ORDEN', OLD."cantidad",
       v_stock_nuevo, OLD."orden_id");

  RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_detalle_ordenes_devolucion
  AFTER DELETE ON "detalle_ordenes"
  FOR EACH ROW
  WHEN (OLD."producto_id" IS NOT NULL)
  EXECUTE FUNCTION fn_devolver_stock_orden();

-- --- Salida de stock por Venta de Mostrador ---
CREATE OR REPLACE FUNCTION fn_descontar_stock_venta() RETURNS TRIGGER AS $$
DECLARE
  v_usuario_id INT;
  v_stock_nuevo INT;
BEGIN
  SELECT "usuario_id" INTO v_usuario_id FROM "ventas" WHERE "id" = NEW."venta_id";

  UPDATE "productos"
     SET "stock_actual" = "stock_actual" - NEW."cantidad"
   WHERE "id" = NEW."producto_id"
   RETURNING "stock_actual" INTO v_stock_nuevo;

  INSERT INTO "kardex_movimientos"
      ("producto_id", "usuario_id", "tipo_movimiento", "cantidad_movida",
       "stock_resultante", "venta_id")
  VALUES
      (NEW."producto_id", v_usuario_id, 'SALIDA_VENTA', -NEW."cantidad",
       v_stock_nuevo, NEW."venta_id");

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_detalle_ventas_descuento
  AFTER INSERT ON "detalle_ventas"
  FOR EACH ROW EXECUTE FUNCTION fn_descontar_stock_venta();

-- Nota: gracias al CHECK ("stock_actual" >= 0) en "productos", cualquier
-- intento de descontar más stock del disponible revierte toda la
-- transacción automáticamente (INSERT en detalle + UPDATE de stock +
-- INSERT en kardex quedan sin aplicar).

-- --- Entradas de mercadería y ajustes manuales ---
-- La aplicación NUNCA debe hacer UPDATE de "stock_actual" directamente: inserta
-- el movimiento en el kardex y este trigger mueve el stock y calcula el saldo.
-- Así no existe forma de alterar el inventario sin dejar rastro auditable.
-- Convención de signo: "cantidad_movida" positiva suma, negativa resta.
CREATE OR REPLACE FUNCTION fn_aplicar_movimiento_manual() RETURNS TRIGGER AS $$
DECLARE
  v_stock_nuevo INT;
BEGIN
  UPDATE "productos"
     SET "stock_actual" = "stock_actual" + NEW."cantidad_movida"
   WHERE "id" = NEW."producto_id"
   RETURNING "stock_actual" INTO v_stock_nuevo;

  NEW."stock_resultante" = v_stock_nuevo;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_kardex_movimiento_manual
  BEFORE INSERT ON "kardex_movimientos"
  FOR EACH ROW
  WHEN (NEW."tipo_movimiento" IN ('ENTRADA', 'AJUSTE_MANUAL'))
  EXECUTE FUNCTION fn_aplicar_movimiento_manual();

-- =====================================================================
-- Trigger: el estado de pago de una orden lo deciden sus abonos
-- =====================================================================
-- Un solo lugar decide si una orden está pagada. Sin esto habría dos —la
-- pantalla y la suma de los abonos— y tarde o temprano la insignia del
-- historial diría una cosa y la caja otra.
--
-- ponytail: solo AFTER INSERT, porque los abonos no se borran ni se editan.
-- Si algún día se anula un pago, el trigger va también en DELETE y UPDATE.
CREATE OR REPLACE FUNCTION fn_actualizar_estado_pago() RETURNS TRIGGER AS $$
BEGIN
  UPDATE "ordenes" o
     SET "estado_pago" = (
           SELECT COALESCE(SUM(p."monto"), 0) >= o."total_final"
             FROM "pagos_orden" p
            WHERE p."orden_id" = o."id"
         )
   WHERE o."id" = NEW."orden_id";
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_pagos_orden_estado
  AFTER INSERT ON "pagos_orden"
  FOR EACH ROW EXECUTE FUNCTION fn_actualizar_estado_pago();

-- Y al revés: si cambia el total de una orden —se le agregó una línea antes de
-- entregarla— lo abonado ya no alcanza, y el estado tiene que decirlo. Sin
-- esto, una orden abierta que se pagó al dejar el auto seguiría marcada como
-- pagada después de cargarle un repuesto más.
-- Una orden de Mercado Público no tiene abonos: la paga su cuenta por cobrar
-- (trigger de las cuentas por cobrar), y eso tampoco lo deshace el total.
CREATE OR REPLACE FUNCTION fn_estado_pago_al_cambiar_total() RETURNS TRIGGER AS $$
BEGIN
  NEW."estado_pago" := (
    SELECT COALESCE(SUM(p."monto"), 0) >= NEW."total_final"
      FROM "pagos_orden" p
     WHERE p."orden_id" = NEW."id"
  ) OR EXISTS (SELECT 1 FROM "cuentas_por_cobrar" c
                WHERE c."orden_id" = NEW."id" AND c."estado" = 'PAGADA');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_ordenes_estado_pago
  BEFORE UPDATE OF "total_final" ON "ordenes"
  FOR EACH ROW
  WHEN (NEW."total_final" IS DISTINCT FROM OLD."total_final")
  EXECUTE FUNCTION fn_estado_pago_al_cambiar_total();

-- =====================================================================
-- Trigger: el costo de una línea se congela al crearla
-- =====================================================================
-- Copia productos.precio_costo a la línea, salvo que ya venga con costo. Está
-- en la base y no en la pantalla por la misma razón que el stock: un solo
-- lugar, sin importar quién inserte la línea. Las de servicio no tienen
-- producto y quedan en NULL.
CREATE OR REPLACE FUNCTION fn_congelar_costo() RETURNS TRIGGER AS $$
BEGIN
  IF NEW."producto_id" IS NOT NULL AND NEW."costo_unitario" IS NULL THEN
    SELECT "precio_costo" INTO NEW."costo_unitario"
      FROM "productos" WHERE "id" = NEW."producto_id";
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_detalle_ordenes_costo
  BEFORE INSERT ON "detalle_ordenes"
  FOR EACH ROW EXECUTE FUNCTION fn_congelar_costo();

CREATE TRIGGER trg_detalle_ventas_costo
  BEFORE INSERT ON "detalle_ventas"
  FOR EACH ROW EXECUTE FUNCTION fn_congelar_costo();

-- =====================================================================
-- Trigger: el cliente de una orden se congela al crearla
-- =====================================================================
-- Es el dueño que tenía el vehículo ese día. Cuando el auto se traspasa, sus
-- órdenes anteriores (el PDF, lo que se debe) siguen siendo de quien lo trajo.
CREATE OR REPLACE FUNCTION fn_congelar_cliente() RETURNS TRIGGER AS $$
BEGIN
  SELECT "cliente_id" INTO NEW."cliente_id"
    FROM "vehiculos" WHERE "id" = NEW."vehiculo_id";
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_ordenes_cliente
  BEFORE INSERT ON "ordenes"
  FOR EACH ROW EXECUTE FUNCTION fn_congelar_cliente();

-- =====================================================================
-- Triggers: servicio de precio variable (Servicio Público)
-- =====================================================================
-- Es plata a cobrar sin producto detrás, y por eso lleva reglas propias que
-- viven acá y no en la pantalla: solo en órdenes con folio de Mercado Público,
-- una vez por orden y de cantidad 1. Y a la inversa, una orden que lo tiene no
-- puede perder su folio, porque quedaría cobrando un presupuesto que no existe.
CREATE OR REPLACE FUNCTION fn_validar_servicio_publico() RETURNS TRIGGER AS $$
DECLARE
  v_folio VARCHAR(50);
BEGIN
  IF NEW."servicio_id" IS NULL
     OR NOT EXISTS (SELECT 1 FROM "servicios" WHERE "id" = NEW."servicio_id" AND "precio_variable") THEN
    RETURN NEW;
  END IF;

  SELECT "folio_mercado_publico" INTO v_folio FROM "ordenes" WHERE "id" = NEW."orden_id";
  IF v_folio IS NULL OR v_folio = '' THEN
    RAISE EXCEPTION USING ERRCODE = 'check_violation',
      MESSAGE = 'El servicio de precio variable solo va en órdenes de Mercado Público (con folio).';
  END IF;
  IF NEW."cantidad" <> 1 THEN
    RAISE EXCEPTION USING ERRCODE = 'check_violation',
      MESSAGE = 'El servicio de precio variable se cobra una sola vez por orden (cantidad 1).';
  END IF;
  IF EXISTS (SELECT 1 FROM "detalle_ordenes"
              WHERE "orden_id" = NEW."orden_id" AND "servicio_id" = NEW."servicio_id") THEN
    RAISE EXCEPTION USING ERRCODE = 'check_violation',
      MESSAGE = 'La orden ya tiene el servicio de precio variable.';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_detalle_ordenes_servicio_publico
  BEFORE INSERT ON "detalle_ordenes"
  FOR EACH ROW EXECUTE FUNCTION fn_validar_servicio_publico();

CREATE OR REPLACE FUNCTION fn_folio_con_servicio_publico() RETURNS TRIGGER AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM "detalle_ordenes" d
               JOIN "servicios" s ON s."id" = d."servicio_id"
              WHERE d."orden_id" = NEW."id" AND s."precio_variable") THEN
    RAISE EXCEPTION USING ERRCODE = 'check_violation',
      MESSAGE = 'La orden tiene el servicio de precio variable: quítalo antes de sacarle el folio de Mercado Público.';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_ordenes_folio_servicio_publico
  BEFORE UPDATE OF "folio_mercado_publico" ON "ordenes"
  FOR EACH ROW
  WHEN (NEW."folio_mercado_publico" IS NULL OR NEW."folio_mercado_publico" = '')
  EXECUTE FUNCTION fn_folio_con_servicio_publico();

-- =====================================================================
-- Triggers: cuentas por cobrar
-- =====================================================================
-- Una orden con folio de Mercado Público abre su cuenta por cobrar sola. Solo
-- mira lo que pasa desde ahora: las órdenes que ya existían no generan cuenta,
-- porque cuáles siguen pendientes lo decide el taller, ingresándolas a mano.
-- Si el folio cambia antes de facturar, la cuenta lo sigue; ya facturada, no.
-- Una cuenta anulada porque le quitaron el folio vuelve si se lo ponen de
-- nuevo (la de una orden anulada no: el WHEN no deja pasar esas órdenes).
CREATE OR REPLACE FUNCTION fn_alta_cuenta_cobrar() RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO "cuentas_por_cobrar" ("orden_id", "numero_oc")
  VALUES (NEW."id", NEW."folio_mercado_publico")
  ON CONFLICT ("orden_id") DO UPDATE
     SET "numero_oc" = EXCLUDED."numero_oc", "estado" = 'PENDIENTE_FACTURA'
   WHERE "cuentas_por_cobrar"."estado" IN ('PENDIENTE_FACTURA', 'ANULADA');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_ordenes_alta_cuenta_cobrar
  AFTER INSERT OR UPDATE OF "folio_mercado_publico" ON "ordenes"
  FOR EACH ROW
  WHEN (NEW."folio_mercado_publico" IS NOT NULL AND NEW."folio_mercado_publico" <> ''
        AND NEW."estado" <> 'ANULADA')
  EXECUTE FUNCTION fn_alta_cuenta_cobrar();

-- Anular la orden anula su cuenta mientras no haya factura. Con factura emitida
-- no se toca: deshacerla es una nota de crédito y lo decide una persona.
CREATE OR REPLACE FUNCTION fn_anular_cuenta_cobrar() RETURNS TRIGGER AS $$
BEGIN
  UPDATE "cuentas_por_cobrar"
     SET "estado" = 'ANULADA'
   WHERE "orden_id" = NEW."id" AND "estado" = 'PENDIENTE_FACTURA';
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_ordenes_anula_cuenta_cobrar
  AFTER UPDATE OF "estado" ON "ordenes"
  FOR EACH ROW
  WHEN (NEW."estado" = 'ANULADA' AND OLD."estado" IS DISTINCT FROM 'ANULADA')
  EXECUTE FUNCTION fn_anular_cuenta_cobrar();

-- Lo mismo si le quitan el folio: ya no es de Mercado Público, y la cuenta
-- quedaría esperando una factura que nadie va a emitir.
CREATE TRIGGER trg_ordenes_quita_folio_cuenta_cobrar
  AFTER UPDATE OF "folio_mercado_publico" ON "ordenes"
  FOR EACH ROW
  WHEN (NEW."folio_mercado_publico" IS NULL OR NEW."folio_mercado_publico" = '')
  EXECUTE FUNCTION fn_anular_cuenta_cobrar();

-- El pago de una orden de Mercado Público se registra en Finanzas: cuando su
-- cuenta queda pagada, la orden también. En Órdenes no se le registran abonos
-- (trigger de abajo), porque entrarían a la caja del día y la cuenta seguiría
-- figurando por cobrar.
CREATE OR REPLACE FUNCTION fn_orden_pagada_por_cuenta() RETURNS TRIGGER AS $$
BEGIN
  UPDATE "ordenes" SET "estado_pago" = TRUE WHERE "id" = NEW."orden_id";
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_cuentas_por_cobrar_paga_orden
  AFTER UPDATE OF "estado" ON "cuentas_por_cobrar"
  FOR EACH ROW
  WHEN (NEW."estado" = 'PAGADA' AND NEW."orden_id" IS NOT NULL)
  EXECUTE FUNCTION fn_orden_pagada_por_cuenta();

CREATE OR REPLACE FUNCTION fn_pago_orden_sin_cuenta() RETURNS TRIGGER AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM "cuentas_por_cobrar"
              WHERE "orden_id" = NEW."orden_id" AND "estado" <> 'ANULADA') THEN
    RAISE EXCEPTION USING ERRCODE = 'check_violation',
      MESSAGE = 'La orden ' || NEW."orden_id" || ' es de Mercado Público: su pago se registra en Finanzas.';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_pagos_orden_sin_cuenta
  BEFORE INSERT ON "pagos_orden"
  FOR EACH ROW EXECUTE FUNCTION fn_pago_orden_sin_cuenta();

-- Solo se abona una cuenta facturada y sin saldar; el pago que la completa la
-- pasa a PAGADA. Un pago de más no se rechaza: los organismos a veces pagan
-- distinto por retenciones, y ese caso lo resuelve una persona.
CREATE OR REPLACE FUNCTION fn_abonar_cuenta_cobrar() RETURNS TRIGGER AS $$
DECLARE
  v_estado VARCHAR(20);
  v_total DECIMAL(10,2);
BEGIN
  SELECT "estado", "venta_neto" + "iva" INTO v_estado, v_total
    FROM "cuentas_por_cobrar" WHERE "id" = NEW."cuenta_id" FOR UPDATE;

  IF v_estado <> 'POR_COBRAR' THEN
    RAISE EXCEPTION USING ERRCODE = 'check_violation',
      MESSAGE = 'La cuenta ' || NEW."cuenta_id" || ' no admite pagos: está ' || v_estado || '.';
  END IF;

  IF (SELECT SUM(p."monto") FROM "pagos_cobro" p WHERE p."cuenta_id" = NEW."cuenta_id") >= v_total THEN
    UPDATE "cuentas_por_cobrar" SET "estado" = 'PAGADA' WHERE "id" = NEW."cuenta_id";
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_pagos_cobro_abono
  AFTER INSERT ON "pagos_cobro"
  FOR EACH ROW EXECUTE FUNCTION fn_abonar_cuenta_cobrar();

-- =====================================================================
-- Trigger: cuentas por pagar
-- =====================================================================
-- Lo mismo para las facturas de proveedor: se abona una pendiente, y el pago
-- que completa el monto la pasa a PAGADA.
CREATE OR REPLACE FUNCTION fn_abonar_factura_proveedor() RETURNS TRIGGER AS $$
DECLARE
  v_estado VARCHAR(20);
  v_monto DECIMAL(10,2);
BEGIN
  SELECT "estado", "monto" INTO v_estado, v_monto
    FROM "facturas_proveedor" WHERE "id" = NEW."factura_id" FOR UPDATE;

  IF v_estado <> 'PENDIENTE' THEN
    RAISE EXCEPTION USING ERRCODE = 'check_violation',
      MESSAGE = 'La factura ' || NEW."factura_id" || ' no admite pagos: está ' || v_estado || '.';
  END IF;

  IF (SELECT SUM(p."monto") FROM "pagos_proveedor" p WHERE p."factura_id" = NEW."factura_id") >= v_monto THEN
    UPDATE "facturas_proveedor" SET "estado" = 'PAGADA' WHERE "id" = NEW."factura_id";
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_pagos_proveedor_abono
  AFTER INSERT ON "pagos_proveedor"
  FOR EACH ROW EXECUTE FUNCTION fn_abonar_factura_proveedor();

-- =====================================================================
-- Vista de alerta de stock crítico (para el módulo de reportería)
-- =====================================================================
CREATE VIEW "vw_stock_critico" AS
SELECT "id", "nombre", "marca", "categoria", "stock_actual", "stock_minimo"
  FROM "productos"
 WHERE "activo" = TRUE
   AND "stock_actual" <= "stock_minimo";

-- =====================================================================
-- Nota sobre seguridad a nivel de base de datos (recomendado)
-- =====================================================================
-- Restringir la tabla kardex_movimientos a append-only revocando UPDATE
-- y DELETE al rol de aplicación, una vez creado dicho rol:
--
-- REVOKE UPDATE, DELETE ON "kardex_movimientos" FROM rol_aplicacion;
--
-- Y por el mismo motivo, impedir que la aplicación mueva el stock por fuera
-- del kardex:
--
-- REVOKE UPDATE ("stock_actual") ON "productos" FROM rol_aplicacion;

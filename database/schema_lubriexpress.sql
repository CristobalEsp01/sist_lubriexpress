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
  "ajuste_redondeo" DECIMAL(10,2) NOT NULL DEFAULT 0,
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
  CONSTRAINT descuento_exclusivo_orden
      CHECK (NOT ("descuento_porcentaje" > 0 AND "descuento_monto" > 0))
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
  "medio_pago" VARCHAR(20) NOT NULL DEFAULT 'EFECTIVO',
  "fecha_pago" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
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
  "ajuste_redondeo" DECIMAL(10,2) NOT NULL DEFAULT 0,
  "total_final" DECIMAL(10,2) NOT NULL CHECK ("total_final" >= 0)
  "medio_pago" VARCHAR(20) NOT NULL DEFAULT 'EFECTIVO'
);

-- ---------------------------------------------------------------------
-- Tabla Detalle de Ventas (Productos por Venta)
-- ---------------------------------------------------------------------
CREATE TABLE "detalle_ventas" (
  "id" SERIAL PRIMARY KEY,
  "venta_id" INT NOT NULL REFERENCES "ventas"("id"),
  "producto_id" INT NOT NULL REFERENCES "productos"("id"),
  "cantidad" INT NOT NULL CHECK ("cantidad" > 0),
  "precio_unitario_cobrado" DECIMAL(10,2) NOT NULL CHECK ("precio_unitario_cobrado" >= 0)
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
  "tipo" VARCHAR(10) NOT NULL CHECK ("tipo" IN ('INGRESO', 'EGRESO')),
  -- El signo lo dice "tipo"; el monto siempre es positivo.
  "monto" DECIMAL(10,2) NOT NULL CHECK ("monto" > 0),
  "motivo" VARCHAR(200) NOT NULL,
  "fecha" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  -- El movimiento que esta fila anula. UNIQUE: nadie anula dos veces el mismo.
  "anula_id" INT UNIQUE REFERENCES "movimientos_caja"("id")
);

-- =====================================================================
-- Índices (Postgres no indexa automáticamente las FK)
-- =====================================================================
CREATE INDEX idx_vehiculos_cliente ON "vehiculos"("cliente_id");
CREATE INDEX idx_productos_ubicacion ON "productos"("ubicacion_id");
CREATE INDEX idx_ordenes_vehiculo ON "ordenes"("vehiculo_id");
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
CREATE OR REPLACE FUNCTION fn_estado_pago_al_cambiar_total() RETURNS TRIGGER AS $$
BEGIN
  NEW."estado_pago" := (
    SELECT COALESCE(SUM(p."monto"), 0) >= NEW."total_final"
      FROM "pagos_orden" p
     WHERE p."orden_id" = NEW."id"
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_ordenes_estado_pago
  BEFORE UPDATE OF "total_final" ON "ordenes"
  FOR EACH ROW
  WHEN (NEW."total_final" IS DISTINCT FROM OLD."total_final")
  EXECUTE FUNCTION fn_estado_pago_al_cambiar_total();

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

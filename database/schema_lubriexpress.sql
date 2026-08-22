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
  "precio_venta" DECIMAL(10,2) NOT NULL CHECK ("precio_venta" >= 0),
  "stock_actual" INT NOT NULL DEFAULT 0 CHECK ("stock_actual" >= 0),
  "stock_minimo" INT NOT NULL DEFAULT 0 CHECK ("stock_minimo" >= 0),
  "activo" BOOLEAN NOT NULL DEFAULT TRUE,
  "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updated_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
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
  "kilometraje_ingreso" INT NOT NULL CHECK ("kilometraje_ingreso" >= 0),
  "descuento_porcentaje" DECIMAL(5,2) NOT NULL DEFAULT 0 CHECK ("descuento_porcentaje" >= 0),
  "descuento_monto" DECIMAL(10,2) NOT NULL DEFAULT 0 CHECK ("descuento_monto" >= 0),
  "subtotal" DECIMAL(10,2) NOT NULL DEFAULT 0,
  "total_final" DECIMAL(10,2) NOT NULL DEFAULT 0,
  "numero_boleta" VARCHAR(50) UNIQUE,
  "estado_pago" BOOLEAN NOT NULL DEFAULT FALSE,
  "notas" TEXT,
  CONSTRAINT descuento_exclusivo_orden
      CHECK (NOT ("descuento_porcentaje" > 0 AND "descuento_monto" > 0))
);

-- ---------------------------------------------------------------------
-- Tabla Detalle de Órdenes (Productos por Orden)
-- ---------------------------------------------------------------------
CREATE TABLE "detalle_ordenes" (
  "id" SERIAL PRIMARY KEY,
  "orden_id" INT NOT NULL REFERENCES "ordenes"("id"),
  "producto_id" INT NOT NULL REFERENCES "productos"("id"),
  "cantidad" INT NOT NULL CHECK ("cantidad" > 0),
  "precio_unitario_cobrado" DECIMAL(10,2) NOT NULL CHECK ("precio_unitario_cobrado" >= 0)
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
  "total_final" DECIMAL(10,2) NOT NULL CHECK ("total_final" >= 0)
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
      CHECK ("tipo_movimiento" IN ('ENTRADA', 'SALIDA_VENTA', 'SALIDA_ORDEN', 'AJUSTE_MANUAL')),
  "cantidad_movida" INT NOT NULL CHECK ("cantidad_movida" <> 0),
  "stock_resultante" INT NOT NULL CHECK ("stock_resultante" >= 0),
  "orden_id" INT REFERENCES "ordenes"("id"),
  "venta_id" INT REFERENCES "ventas"("id"),
  "fecha_movimiento" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT origen_movimiento_valido
      CHECK (
        ("tipo_movimiento" = 'SALIDA_ORDEN' AND "orden_id" IS NOT NULL AND "venta_id" IS NULL) OR
        ("tipo_movimiento" = 'SALIDA_VENTA' AND "venta_id" IS NOT NULL AND "orden_id" IS NULL) OR
        ("tipo_movimiento" IN ('ENTRADA', 'AJUSTE_MANUAL') AND "orden_id" IS NULL AND "venta_id" IS NULL)
      )
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
CREATE INDEX idx_ventas_usuario ON "ventas"("usuario_id");
CREATE INDEX idx_ventas_fecha ON "ventas"("fecha_venta");
CREATE INDEX idx_detalle_ventas_venta ON "detalle_ventas"("venta_id");
CREATE INDEX idx_detalle_ventas_producto ON "detalle_ventas"("producto_id");
CREATE INDEX idx_kardex_producto ON "kardex_movimientos"("producto_id");
CREATE INDEX idx_kardex_fecha ON "kardex_movimientos"("fecha_movimiento");

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
  FOR EACH ROW EXECUTE FUNCTION fn_descontar_stock_orden();

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

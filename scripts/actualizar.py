"""Lleva una base con datos reales a la versión nueva del esquema, sin recrearla.

Uso, en el PC del taller (junto al ejecutable):

    actualizar.exe
    actualizar.exe --simular    # dice qué haría, sin escribir nada

Desde el repositorio:

    .venv/bin/python scripts/actualizar.py [--simular]

Cada paso mira la base antes de actuar y se salta lo que ya está, así que
correrlo dos veces no hace daño. El respaldo va primero: si falla, el esquema
no se toca. Lo que sí se aplica va en una sola transacción, así que un paso que
reviente no deja la base a medio camino.

`database/schema_lubriexpress.sql` sigue siendo la verdad: lo que crea un paso
de acá tiene que ser exactamente lo que declara el esquema, y
`tests/test_actualizar.py` falla si se separan.
"""
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, text  # noqa: E402

from scripts.respaldar import respaldar  # noqa: E402
from src.models import Producto, Ubicacion  # noqa: E402
from src.ubicaciones import detectar  # noqa: E402


@dataclass(frozen=True)
class Paso:
    """Un cambio de esquema.

    `declara` son los trozos de `database/schema_lubriexpress.sql` que este paso
    tiene que reproducir palabra por palabra; vacío significa "todo el `sql`".
    Una prueba verifica que aparezcan en el esquema y en el `sql` del paso, así
    que una base actualizada y una recién instalada no se pueden separar.
    """

    nombre: str
    comprobacion: str   # SELECT que devuelve true si el paso ya está aplicado
    sql: str
    declara: tuple[str, ...] = ()


# Funciones y triggers copiados del `.sql`; van en constantes porque son largos
# y porque la prueba de paridad los compara enteros contra el esquema.
DEVOLVER_STOCK = '''
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
'''

ESTADO_PAGO_AL_CAMBIAR_TOTAL = '''
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
'''

# ponytail: la lista de pasos se escribe a mano y solo va hacia adelante. Sirve
# mientras sean unos pocos cambios aditivos; el día que haya que revertir uno, o
# que la lista crezca, toca incorporar Alembic (anotado en docs/base-de-datos.md).
PASOS = [
    Paso(
        nombre="movimientos_caja",
        comprobacion="SELECT to_regclass('public.movimientos_caja') IS NOT NULL",
        sql='''
CREATE TABLE "movimientos_caja" (
  "id" SERIAL PRIMARY KEY,
  "usuario_id" INT NOT NULL REFERENCES "usuarios"("id"),
  "tipo" VARCHAR(10) NOT NULL CHECK ("tipo" IN ('INGRESO', 'EGRESO')),
  "monto" DECIMAL(10,2) NOT NULL CHECK ("monto" > 0),
  "motivo" VARCHAR(200) NOT NULL,
  "fecha" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "anula_id" INT UNIQUE REFERENCES "movimientos_caja"("id")
);
CREATE INDEX idx_movimientos_caja_fecha ON "movimientos_caja"("fecha");
''',
        declara=(
            'CREATE TABLE "movimientos_caja" (',
            'CREATE INDEX idx_movimientos_caja_fecha ON "movimientos_caja"("fecha");',
        ),
    ),
    Paso(
        nombre="kardex_movimientos.costo_unitario",
        comprobacion="""
            SELECT EXISTS (SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'kardex_movimientos'
                              AND column_name = 'costo_unitario')
        """,
        sql='''
ALTER TABLE "kardex_movimientos"
  ADD COLUMN "costo_unitario" DECIMAL(10,2) CHECK ("costo_unitario" >= 0);
''',
        declara=('"costo_unitario" DECIMAL(10,2) CHECK ("costo_unitario" >= 0)',),
    ),
    Paso(
        nombre="ordenes.estado",
        comprobacion="""
            SELECT EXISTS (SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'ordenes' AND column_name = 'estado')
        """,
        sql='''
ALTER TABLE "ordenes"
  ADD COLUMN "estado" VARCHAR(20) NOT NULL DEFAULT 'ENTREGADA'
      CHECK ("estado" IN ('ABIERTA', 'ENTREGADA', 'ANULADA'));
''',
        declara=('''"estado" VARCHAR(20) NOT NULL DEFAULT 'ENTREGADA'
      CHECK ("estado" IN ('ABIERTA', 'ENTREGADA', 'ANULADA'))''',),
    ),
    Paso(
        nombre="kardex_movimientos.devolucion",
        comprobacion="""
            SELECT EXISTS (SELECT 1 FROM pg_constraint
                            WHERE conname = 'origen_movimiento_valido'
                              AND pg_get_constraintdef(oid) LIKE '%DEVOLUCION_ORDEN%')
        """,
        sql='''
ALTER TABLE "kardex_movimientos"
  DROP CONSTRAINT "kardex_movimientos_tipo_movimiento_check",
  ADD CONSTRAINT "kardex_movimientos_tipo_movimiento_check"
      CHECK ("tipo_movimiento" IN ('ENTRADA', 'SALIDA_VENTA', 'SALIDA_ORDEN',
                                   'AJUSTE_MANUAL', 'DEVOLUCION_ORDEN')),
  DROP CONSTRAINT "origen_movimiento_valido",
  ADD CONSTRAINT "origen_movimiento_valido"
      CHECK (
        ("tipo_movimiento" IN ('SALIDA_ORDEN', 'DEVOLUCION_ORDEN') AND "orden_id" IS NOT NULL AND "venta_id" IS NULL) OR
        ("tipo_movimiento" = 'SALIDA_VENTA' AND "venta_id" IS NOT NULL AND "orden_id" IS NULL) OR
        ("tipo_movimiento" IN ('ENTRADA', 'AJUSTE_MANUAL') AND "orden_id" IS NULL AND "venta_id" IS NULL)
      );
''',
        declara=(
            '''CHECK ("tipo_movimiento" IN ('ENTRADA', 'SALIDA_VENTA', 'SALIDA_ORDEN',
                                   'AJUSTE_MANUAL', 'DEVOLUCION_ORDEN'))''',
            '''CHECK (
        ("tipo_movimiento" IN ('SALIDA_ORDEN', 'DEVOLUCION_ORDEN') AND "orden_id" IS NOT NULL AND "venta_id" IS NULL) OR
        ("tipo_movimiento" = 'SALIDA_VENTA' AND "venta_id" IS NOT NULL AND "orden_id" IS NULL) OR
        ("tipo_movimiento" IN ('ENTRADA', 'AJUSTE_MANUAL') AND "orden_id" IS NULL AND "venta_id" IS NULL)
      )''',
        ),
    ),
    Paso(
        nombre="detalle_ordenes.devolucion",
        comprobacion="""
            SELECT EXISTS (SELECT 1 FROM pg_trigger
                            WHERE tgname = 'trg_detalle_ordenes_devolucion')
        """,
        sql=DEVOLVER_STOCK,
        declara=(DEVOLVER_STOCK,),
    ),
    Paso(
        nombre="ordenes.estado_pago_derivado",
        comprobacion="""
            SELECT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_ordenes_estado_pago')
        """,
        sql=ESTADO_PAGO_AL_CAMBIAR_TOTAL,
        declara=(ESTADO_PAGO_AL_CAMBIAR_TOTAL,),
    ),
    Paso(
        nombre="ventas.ajuste_redondeo",
        comprobacion="""
            SELECT EXISTS (SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'ventas' AND column_name = 'ajuste_redondeo')
        """,
        sql='''
ALTER TABLE "ventas"
  ADD COLUMN "ajuste_redondeo" DECIMAL(10,2) NOT NULL DEFAULT 0;
''',
        declara=('"ajuste_redondeo" DECIMAL(10,2) NOT NULL DEFAULT 0',),
    ),
    Paso(
        nombre="ordenes.ajuste_redondeo",
        comprobacion="""
            SELECT EXISTS (SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'ordenes' AND column_name = 'ajuste_redondeo')
        """,
        sql='''
ALTER TABLE "ordenes"
  ADD COLUMN "ajuste_redondeo" DECIMAL(10,2) NOT NULL DEFAULT 0;
''',
        declara=('"ajuste_redondeo" DECIMAL(10,2) NOT NULL DEFAULT 0',),
    ),
]

# Lo que se cuenta antes y después. Un cambio de esquema no borra filas; si la
# cifra se movió, algo salió mal y hay que restaurar el respaldo.
TABLAS_VERIFICADAS = (
    "usuarios", "clientes", "vehiculos", "productos", "servicios",
    "ordenes", "detalle_ordenes", "pagos_orden", "ventas", "detalle_ventas",
    "kardex_movimientos",
)


def pendientes(conexion) -> list[Paso]:
    return [paso for paso in PASOS
            if not conexion.execute(text(paso.comprobacion)).scalar()]


def aplicar(conexion, paso: Paso) -> None:
    # exec_driver_sql y no text(): el SQL va crudo al driver, que es lo que
    # permite crear la tabla y su índice en una sola llamada.
    conexion.exec_driver_sql(paso.sql)


def rellenar_ubicaciones(db, aplicar: bool) -> tuple[int, set[str]]:
    """Copia a su columna la ubicación de bodega que el sistema viejo dejó
    escrita en la descripción del producto.

    Solo mira productos que no tengan ubicación, así que correrlo dos veces no
    cambia nada. Con `aplicar` en falso recorre y cuenta sin escribir, que es
    lo que hace falta para mirar la lista antes de aceptarla.
    """
    existentes = {u.descripcion: u for u in db.scalars(select(Ubicacion))}
    encontradas, tocados = set(), 0
    for producto in db.scalars(select(Producto).where(Producto.ubicacion_id.is_(None))):
        donde, descripcion = detectar(producto.descripcion)
        if donde is None:
            continue
        encontradas.add(donde)
        tocados += 1
        if not aplicar:
            continue
        if donde not in existentes:
            existentes[donde] = Ubicacion(descripcion=donde)
            db.add(existentes[donde])
            db.flush()
        producto.ubicacion = existentes[donde]
        producto.descripcion = descripcion
    return tocados, encontradas


def conteos(conexion) -> dict[str, int]:
    return {tabla: conexion.execute(text(f'SELECT count(*) FROM "{tabla}"')).scalar()
            for tabla in TABLAS_VERIFICADAS}


def main(argv: list[str]) -> int:
    from src.database import engine

    from src.database import SessionLocal

    simular = "--simular" in argv
    print("Lubri-Express — actualización de la base de datos\n")
    with engine.connect() as conexion:
        falta = pendientes(conexion)
        antes = conteos(conexion)

    with SessionLocal() as db:
        cuantos, donde = rellenar_ubicaciones(db, aplicar=False)

    if not falta and not cuantos:
        print("El esquema ya está al día y no hay ubicaciones por rellenar.")
        return 0

    print(f"{len(falta)} cambio(s) de esquema por aplicar:")
    for paso in falta:
        print(f"  - {paso.nombre}")
    if cuantos:
        print(f"Y {cuantos} producto(s) con la ubicación escrita en la descripción, "
              f"en {len(donde)} ubicaciones:")
        print("  " + ", ".join(sorted(donde)))

    if simular:
        print("\n--simular: no se escribió nada.")
        return 0

    print("\n1. Respaldo")
    archivo = respaldar()
    print(f"   {archivo}  ({archivo.stat().st_size / 1024:.0f} KB)")

    print("\n2. Esquema")
    with engine.begin() as conexion:
        for paso in falta:
            aplicar(conexion, paso)
            print(f"   + {paso.nombre}")
    if not falta:
        print("   ya estaba al día")

    if cuantos:
        print("\n3. Ubicaciones desde la descripción")
        if input(f"   ¿Copiar {cuantos} ubicación(es) a su columna? [s/N] ").strip().lower() == "s":
            with SessionLocal() as db:
                tocados, creadas = rellenar_ubicaciones(db, aplicar=True)
                db.commit()
            print(f"   + {tocados} producto(s) en {len(creadas)} ubicaciones")
        else:
            print("   Se dejó como estaba. Se puede correr después.")

    print("\n4. Verificación")
    with engine.connect() as conexion:
        despues, restantes = conteos(conexion), pendientes(conexion)
    for tabla, cuantas in antes.items():
        senal = "=" if despues[tabla] == cuantas else "≠"
        print(f"   {tabla}: {cuantas} {senal} {despues[tabla]}")

    if despues != antes or restantes:
        print(f"\nAlgo no cuadra. Restaura {archivo} y avisa antes de seguir.")
        return 1
    print("\nListo: la base quedó al día.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

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
    """Un cambio de esquema. `nombre` es la tabla, o "tabla.columna"."""

    nombre: str
    comprobacion: str   # SELECT que devuelve true si el paso ya está aplicado
    sql: str


# ponytail: la lista de pasos se escribe a mano y solo va hacia adelante. Sirve
# mientras sean unos pocos cambios aditivos; el día que haya que revertir uno, o
# que la lista crezca, toca incorporar Alembic (anotado en docs/base-de-datos.md).
# Las dos copias —esta y la del .sql— las mantiene calzadas una prueba.
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

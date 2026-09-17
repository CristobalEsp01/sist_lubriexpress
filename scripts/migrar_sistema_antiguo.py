"""Migra las cinco planillas del sistema antiguo a la base nueva.

Uso:
    .venv/bin/python scripts/migrar_sistema_antiguo.py <carpeta con los .xlsx> [--detalle]

La carpeta trae `tabla clientes.xlsx`, `tabla vehiculo.xlsx`,
`tabla productos.xlsx`, `tabla servicios.xlsx` y `tabla ordenes.xlsx`. Son
datos reales de clientes: viven fuera del repositorio y ahí se quedan.

Reglas, en orden de importancia:

- Todo entra en una sola transacción y el script se niega a correr dos veces:
  si ya existe el usuario `sistema_antiguo`, no hay nada que hacer. Así
  "correrlo de nuevo" nunca duplica.
- El stock inicial entra por Kardex (`ENTRADA`), nunca asignando
  `stock_actual`: el trigger mueve el stock y el inventario queda auditable
  desde el primer día.
- No se inventa nada para que quepa. Una orden sin patente válida o sin
  fecha se descarta y se cuenta; una sin kilometraje entra con el campo vacío
  (la pantalla lo exige, el historial no siempre lo traía); un producto sin
  costo no recibe un costo de $0. El informe final dice cuánto se descartó y por qué, por
  categoría; `--detalle` lista las filas de cada una.
- Las órdenes vienen sin líneas de detalle (la planilla solo trae Subtotal /
  Impuestos / Total / Descuento), así que se cargan como cabeceras: sus cifras
  quedan copiadas sin `detalle_ordenes` que las respalde y sin Kardex. La
  reportería por producto empieza con el sistema nuevo; la de ingresos por
  período sí cubre el historial.
- El cliente de una orden es texto libre (Nombre + Apellidos) y el sistema
  antiguo no tenía otra llave: los homónimos —comparados con `normalizar()`—
  se funden en un solo cliente. El dueño de cada vehículo es el nombre de su
  orden más reciente; los nombres que no están en la planilla de clientes se
  crean desde la orden.
- Las categorías vienen escritas de cualquier manera: 131 escrituras para
  poco más de sesenta categorías de verdad. Se unifica lo que es la misma
  palabra —mayúsculas, tildes, espacios, el "de" del medio y el plural— y se
  conserva la escritura más usada, sin inventar una nueva. Las erratas no se
  tocan: "Aceite moto" no es un "Aceite motor" mal escrito, y ninguna regla de
  parecido sabe la diferencia. Salen listadas en el informe para que las junte
  a mano quien conozca el mostrador.
- Los cinco técnicos pasan a ser usuarios reales, inactivos y sin contraseña
  utilizable hasta que un administrador se la ponga. Las órdenes sin técnico
  cuelgan de `sistema_antiguo`, también inactivo.
"""
import re
import secrets
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from src.auth import hash_password  # noqa: E402
from src.database import SessionLocal  # noqa: E402
from src.models import (  # noqa: E402
    Cliente, KardexMovimiento, Orden, Producto, Servicio, Usuario, Vehiculo,
)
from src.patente import PATENTE, normalizar_patente  # noqa: E402
from src.texto import normalizar, sin_tildes  # noqa: E402
from src.xlsx import leer_xlsx  # noqa: E402

PLANILLAS = {
    "clientes": "tabla clientes.xlsx",
    "vehiculos": "tabla vehiculo.xlsx",
    "productos": "tabla productos.xlsx",
    "servicios": "tabla servicios.xlsx",
    "ordenes": "tabla ordenes.xlsx",
}
USUARIO_MIGRACION = "sistema_antiguo"
MARCA_NOTAS = "Migrada del sistema antiguo"
ESTADOS_PAGADOS = {"Entregado", "Finalizado"}
PATENTE_ORDEN = "Vehiculos_presup_SEGUNPATENTE::patente"

def fecha_excel(serial) -> datetime | None:
    """Excel cuenta días desde el 30-12-1899; la fracción es la hora."""
    if serial in (None, ""):
        return None
    return datetime(1899, 12, 30) + timedelta(days=float(serial))


def numero(texto) -> Decimal | None:
    if texto in (None, ""):
        return None
    return Decimal(texto).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def limpio(texto) -> str | None:
    """Sin espacios alrededor; vacío es None (los NOT NULL y UNIQUE lo agradecen)."""
    texto = (texto or "").strip()
    return texto or None


# ---------------------------------------------------------------------------
# El informe: cuánto entró y cuánto se descartó, por motivo
# ---------------------------------------------------------------------------
class Informe:
    def __init__(self):
        self.cargados = Counter()
        self.descartes = Counter()
        self.detalle = defaultdict(list)
        self.stock_esperado = 0  # unidades que deben terminar en el Kardex

    def descartar(self, planilla: str, motivo: str, fila: str) -> None:
        self.descartes[(planilla, motivo)] += 1
        self.detalle[(planilla, motivo)].append(fila)

    def imprimir(self, con_detalle: bool = False) -> None:
        print("\nCargado:")
        for tabla, n in sorted(self.cargados.items()):
            print(f"  {tabla:<22} {n:>6}")
        print("\nDescartado o ajustado (planilla, motivo):")
        if not self.descartes:
            print("  nada")
        for (planilla, motivo), n in sorted(self.descartes.items()):
            print(f"  {planilla:<10} {n:>5}  {motivo}")
            if con_detalle:
                for fila in self.detalle[(planilla, motivo)]:
                    print(f"                   {fila}")


# El "de" no distingue una categoría de otra: "Filtro de aire" y "Filtro aire"
# son la misma repisa. Palabras con significado, en cambio, no se tocan.
CONECTORES = {"DE", "DEL"}
# Bajo esto dos categorías no se parecen en nada; sobre esto, o son la misma mal
# escrita o son dos cosas distintas que se escriben parecido. Ninguna de las dos
# se decide sola: el umbral solo elige de qué avisar.
PARECIDO = 0.85

# Equivalencias comprobadas para erratas evidentes, modelos/formatos incluidos
# en el nombre y sinónimos directos del sistema antiguo. Se mapean por clave
# canónica para no depender de comparaciones difusas que arriesgarían fusionar
# categorías legítimas distintas (como "Aceite moto" con "Aceite motor").
EQUIVALENCIAS_CATEGORIAS = {
    # Erratas tipográficas evidentes
    "AACEITE MOTOR": "ACEITE MOTOR",
    "HERRAMIETA": "HERRAMIENTA",
    "REPUSTO": "REPUESTO",
    "REPESTO": "REPUESTO",
    "REUESTO": "REPUESTO",
    "REOUESTO": "REPUESTO",
    "FILTR AIRE": "FILTRO AIRE",
    "FILTR O": "FILTRO AIRE",
    "FIILTRO": "FILTRO AIRE",
    # Modelos o descripciones físicas dentro de la categoría
    "FILTRO AIRE CIRCULAR TIPO PLATO": "FILTRO AIRE",
    "FILTRO AIRE RAV4 2021": "FILTRO AIRE",
    "FILTRO AIRE SUZUKI SWIFT 1 2 2021": "FILTRO AIRE",
    "FILTRO POLEN 2 CUERPO": "FILTRO POLEN",
    # Sinónimos y variantes léxicas directas
    "BEBIDA": "BEBESTIBLE",
    "CUIDADO VEHICULO": "CUIDADO AUTO",
    "ACEITE TRANSMISION": "ACEITE CAJA",
    "LUCE": "AMPOLLETA",
    "PASTILLA FRENO": "FRENO",
    "BORNE PARA BATERIA": "BATERIA",
    "ACCESORIO MOTOR": "BUJIA",
    "LIMPIADOR AC": "ADITIVO",
    # Casos especiales de contexto en productos
    "SIN SELLO": "ACEITE MOTOR",
}


def clave_de_categoria(texto: str) -> str:
    """'Filtro de Aires' -> 'FILTRO AIRE'. La misma clave para las escrituras
    que son la misma palabra: mayúsculas, tildes, puntuación, conectores y el
    plural. Lo que sobrevive a eso son categorías distintas de verdad."""
    return " ".join(
        p[:-1] if p.endswith("S") and len(p) > 3 else p
        for p in re.split(r"[^A-Z0-9]+", sin_tildes(texto or ""))
        if p and p not in CONECTORES
    )


def canonizar_categorias(valores, informe: Informe, planilla: str) -> dict[str, str]:
    """Mapa escritura -> categoría, con la escritura más usada como nombre.

    No inventa nombres: de las cuatro formas de escribir el filtro de aire gana
    la que el taller tecleó 295 veces, no un Title Case que nadie escribió. Y no
    corrige erratas a ciegas —eso pide saber qué se vende, no comparar letras—,
    sino que aplica equivalencias conocidas y avisa de parecidos dudosos.
    """
    cuenta = Counter(v for valor in valores if (v := limpio(valor)))
    grupos = defaultdict(list)
    for escritura in cuenta:
        clave = clave_de_categoria(escritura)
        clave = EQUIVALENCIAS_CATEGORIAS.get(clave, clave)
        grupos[clave].append(escritura)

    mapa, nombre, total = {}, {}, {}
    for clave, escrituras in grupos.items():
        canonica = min(escrituras, key=lambda e: (-cuenta[e], e))
        nombre[clave] = canonica
        total[clave] = sum(cuenta[e] for e in escrituras)
        for escritura in escrituras:
            mapa[escritura] = canonica
            if escritura != canonica:
                informe.descartar(
                    planilla, "categoría unificada (la misma, escrita distinto)",
                    f"{escritura} ({cuenta[escritura]}) -> {canonica}",
                )

    # Y lo que se parece sin ser lo mismo, o al revés. Cada categoría chica se
    # compara contra la más parecida de las que tienen más productos que ella:
    # una errata es una categoría de uno al lado de una de cuatrocientos. Esto
    # solo avisa —"Aceite moto" no es un "Aceite motor" mal escrito— y la línea
    # queda en el informe para que la resuelva quien conozca el mostrador.
    claves = sorted(grupos, key=lambda k: (-total[k], k))
    for i, chica in enumerate(claves[1:], 1):
        grande = max(claves[:i], key=lambda k: SequenceMatcher(None, chica, k).ratio())
        if SequenceMatcher(None, chica, grande).ratio() >= PARECIDO:
            informe.descartar(
                planilla, "categoría parecida a otra (juntarlas es decisión del taller)",
                f"{nombre[chica]} ({total[chica]}) ~ ¿{nombre[grande]} ({total[grande]})?",
            )
    return mapa


def recortar(informe: Informe, planilla: str, campo: str, valor, largo: int, fila: str):
    """Lo que no cabe en el VARCHAR se corta y se cuenta, no se pierde en silencio."""
    valor = limpio(valor)
    if valor and len(valor) > largo:
        informe.descartar(planilla, f"{campo} recortado a {largo} caracteres", fila)
        return valor[:largo]
    return valor


# ---------------------------------------------------------------------------
# La migración
# ---------------------------------------------------------------------------
def migrar(db, planillas: dict[str, list[dict]]) -> Informe | None:
    """Carga las cinco planillas (ya leídas) en la sesión `db`, sin commit.

    Devuelve el informe, o None si la base ya tiene la migración.
    """
    # ponytail: la idempotencia es un guardián global, no un upsert por fila.
    # Basta porque todo va en una transacción: o está todo o no hay nada. Si
    # algún día hay que re-migrar por partes, la salida es upsert por patente,
    # nombre normalizado y nombre de producto.
    if db.scalar(select(Usuario).where(Usuario.username == USUARIO_MIGRACION)):
        return None

    informe = Informe()
    usuarios = _usuarios(db, planillas["ordenes"], informe)
    clientes = _clientes(planillas["clientes"], informe)
    vehiculos = _vehiculos(planillas["vehiculos"], planillas["ordenes"], clientes, informe)
    _ordenes(planillas["ordenes"], vehiculos, usuarios, informe)
    db.add_all(clientes.values())
    db.add_all(vehiculos.values())
    _productos(db, planillas["productos"], usuarios[None], informe)
    _servicios(db, planillas["servicios"], informe)
    db.flush()
    return informe


def _username(nombre: str) -> str:
    """'Alex Núñez Uribe' -> 'alex.nunez'."""
    partes = sin_tildes(nombre).lower().split()
    return ".".join(partes[:2])


def _usuarios(db, ordenes: list[dict], informe: Informe) -> dict[str | None, Usuario]:
    """Los técnicos de las órdenes como usuarios reales, más `sistema_antiguo`
    para lo que no tiene técnico (clave None)."""
    def inutilizable() -> str:
        return hash_password(secrets.token_hex(16))

    usuarios = {None: Usuario(
        nombre="Sistema antiguo", username=USUARIO_MIGRACION,
        password_hash=inutilizable(), rol="USUARIO_NORMAL", activo=False,
    )}
    for tecnico in sorted({limpio(o.get("tecnico")) for o in ordenes} - {None}):
        existente = db.scalar(select(Usuario).where(Usuario.username == _username(tecnico)))
        if existente is None:
            existente = db.scalar(select(Usuario).where(Usuario.nombre == tecnico))
        if existente is not None:
            informe.descartar("ordenes", "técnico ya existía como usuario", tecnico)
            usuarios[tecnico] = existente
            continue
        usuarios[tecnico] = Usuario(
            nombre=tecnico, username=_username(tecnico), password_hash=inutilizable(),
            rol="USUARIO_NORMAL", activo=False,
        )
    db.add_all(usuarios.values())
    db.flush()
    informe.cargados["usuarios"] = len(usuarios)
    return usuarios


def _clientes(filas: list[dict], informe: Informe) -> dict[str, Cliente]:
    """Un cliente por nombre normalizado. Los homónimos se funden: el sistema
    antiguo identificaba al cliente solo por nombre (las órdenes no traen su
    ID), así que separarlos sería adivinar."""
    clientes: dict[str, Cliente] = {}
    for fila in filas:
        nombre = limpio(fila.get("Nombre del cliente"))
        if not nombre:
            informe.descartar("clientes", "sin nombre", str(fila))
            continue
        llave = normalizar(nombre)
        telefono = recortar(informe, "clientes", "teléfono", fila.get("Telefono"), 15, nombre)
        if llave in clientes:
            existente = clientes[llave]
            if telefono and telefono != existente.telefono:
                if existente.telefono is None:
                    existente.telefono = telefono
                else:
                    informe.descartar(
                        "clientes", "homónimo fundido con otro teléfono (se conservó el primero)",
                        f"{nombre}: {telefono} (quedó {existente.telefono})",
                    )
            else:
                informe.descartar("clientes", "homónimo fundido", nombre)
            continue
        clientes[llave] = Cliente(
            nombre_completo=recortar(informe, "clientes", "nombre", nombre, 150, nombre),
            tipo_cliente="PERSONA", telefono=telefono,
        )
    informe.cargados["clientes"] = len(clientes)
    return clientes


def _nombre_de_orden(orden: dict) -> str | None:
    return limpio(f"{orden.get('Nombre') or ''} {orden.get('Apellidos') or ''}")


def _duenos_segun_ordenes(ordenes: list[dict]) -> dict[str, str]:
    """patente -> nombre del cliente de su orden más reciente con nombre."""
    duenos: dict[str, tuple[float, str]] = {}
    for o in ordenes:
        patente = normalizar_patente(o.get(PATENTE_ORDEN))
        nombre = _nombre_de_orden(o)
        if not nombre or not PATENTE.match(patente):
            continue
        fecha = float(o.get("date_created") or 0)
        if patente not in duenos or fecha >= duenos[patente][0]:
            duenos[patente] = (fecha, nombre)
    return {patente: nombre for patente, (_, nombre) in duenos.items()}


def _anio(texto, informe: Informe, fila: str) -> int | None:
    texto = limpio(texto)
    if texto is None:
        return None
    if texto.isdigit() and 1900 <= int(texto) <= 2100:
        return int(texto)
    informe.descartar("vehiculos", "año no reconocible (queda vacío)", f"{fila}: {texto!r}")
    return None


def _vehiculos(filas, ordenes, clientes: dict[str, Cliente], informe) -> dict[str, Vehiculo]:
    duenos = _duenos_segun_ordenes(ordenes)
    vehiculos: dict[str, Vehiculo] = {}
    for fila in filas:
        patente = normalizar_patente(fila.get("patente"))
        if not PATENTE.match(patente):
            informe.descartar("vehiculos", "patente inválida", patente or "(vacía)")
            continue
        if patente in vehiculos:
            informe.descartar("vehiculos", "patente repetida (se conservó la primera)", patente)
            continue
        nombre_dueno = duenos.get(patente)
        if nombre_dueno is None:
            informe.descartar("vehiculos", "sin ninguna orden que diga de quién es", patente)
            continue
        llave = normalizar(nombre_dueno)
        if llave not in clientes:
            clientes[llave] = Cliente(nombre_completo=nombre_dueno[:150], tipo_cliente="PERSONA")
            informe.cargados["clientes"] += 1
            informe.descartar("clientes", "creado desde una orden (no estaba en la planilla)",
                              nombre_dueno)

        def campo(nombre: str, largo: int):
            return recortar(informe, "vehiculos", nombre, fila.get(nombre), largo, patente)

        vehiculos[patente] = Vehiculo(
            cliente=clientes[llave], patente=patente,
            marca=campo("marca", 50), modelo=campo("modelo", 50),
            anio_fabricacion=_anio(fila.get("año"), informe, patente),
            color=campo("color", 30), transmision=campo("transmision", 20),
            traccion=campo("traccion", 20), tipo=campo("tipo", 30),
            version=campo("version", 50), vin=campo("vin", 20),
            numero_motor=campo("num_motor", 30),
            # "motor" y "kms" vienen vacíos en toda la planilla; el último
            # kilometraje se lee de la orden más reciente del vehículo.
        )
    informe.cargados["vehiculos"] = len(vehiculos)
    return vehiculos


def _ordenes(filas, vehiculos: dict[str, Vehiculo], usuarios, informe: Informe) -> None:
    n = 0
    for fila in filas:
        ref = fila.get("id_gato") or "(sin id)"
        patente = normalizar_patente(fila.get(PATENTE_ORDEN))
        if not PATENTE.match(patente):
            informe.descartar("ordenes", "patente inválida", f"{ref} {patente!r}")
            continue
        if patente not in vehiculos:
            informe.descartar("ordenes", "su vehículo no se cargó", f"{ref} {patente}")
            continue
        estado = limpio(fila.get("Estado"))
        if estado == "Cancelado":
            informe.descartar("ordenes", "cancelada en el sistema antiguo", ref)
            continue
        fecha = fecha_excel(fila.get("date_created"))
        if fecha is None:
            informe.descartar("ordenes", "sin fecha", ref)
            continue
        kms = numero(fila.get("kms"))
        if kms is not None and kms < 0:
            informe.descartar("ordenes", "kilometraje negativo", ref)
            continue
        if kms is None:
            informe.descartar("ordenes", "sin kilometraje (queda vacío)", ref)
        subtotal, impuesto = numero(fila.get("Subtotal")), numero(fila.get("Impuestos"))
        total, descuento = numero(fila.get("Total general")), numero(fila.get("Descuento"))
        if total is None or subtotal is None:
            informe.descartar("ordenes", "sin montos", ref)
            continue
        if total < 0 or subtotal < 0 or (impuesto or 0) < 0 or (descuento or 0) < 0:
            informe.descartar("ordenes", "monto negativo", ref)
            continue

        notas = [f"{MARCA_NOTAS} ({ref}). Estado original: {estado or 'sin estado'}."]
        falla = limpio(fila.get("Falla"))
        if falla:
            notas.append(f"Falla: {falla}")
        Orden(
            vehiculo=vehiculos[patente],
            usuario=usuarios[limpio(fila.get("tecnico"))],
            fecha_creacion=fecha,
            kilometraje_ingreso=None if kms is None else int(kms),
            descuento_monto=descuento or 0,
            subtotal=subtotal, impuesto=impuesto or 0, total_final=total,
            estado_pago=estado in ESTADOS_PAGADOS,
            notas="\n".join(notas),
        )  # queda en vehiculo.ordenes por back_populates; entra a la sesión con él
        n += 1
    informe.cargados["ordenes"] = n


def _stock_inicial(texto, informe: Informe, nombre: str) -> int:
    """Solo un entero positivo entra por Kardex. Lo demás queda en 0 y se
    cuenta: un stock negativo o fraccionario no se puede inventariar."""
    valor = numero(texto)
    if valor is None:
        informe.descartar("productos", "sin stock informado (cargado en 0)", nombre)
        return 0
    if valor < 0:
        informe.descartar("productos", "stock negativo (cargado en 0, revisar)", f"{nombre}: {valor}")
        return 0
    if valor != valor.to_integral_value():
        informe.descartar("productos", "stock fraccionario (cargado en 0, revisar)", f"{nombre}: {valor}")
        return 0
    return int(valor)


def _productos(db, filas, usuario_migracion: Usuario, informe: Informe) -> None:
    nombres = Counter()
    productos = []
    categorias = canonizar_categorias(
        (fila.get("Categoría") for fila in filas), informe, "productos",
    )
    for fila in filas:
        nombre = limpio(fila.get("Nombre del producto"))
        if not nombre:
            informe.descartar("productos", "sin nombre", str(fila.get("ID del producto")))
            continue
        costo, neto = numero(fila.get("Costo")), numero(fila.get("Precio_neto"))
        if costo is None or costo < 0:
            informe.descartar("productos", "sin costo (precio_costo es obligatorio)", nombre)
            continue
        if neto is None or neto < 0:
            informe.descartar("productos", "sin precio neto", nombre)
            continue
        nombres[nombre] += 1
        if nombres[nombre] == 2:
            informe.descartar("productos", "nombre repetido (se cargan todas las filas)", nombre)
        producto = Producto(
            nombre=recortar(informe, "productos", "nombre", nombre, 100, nombre),
            marca=recortar(informe, "productos", "marca", fila.get("Fabricante"), 50, nombre),
            categoria=recortar(informe, "productos", "categoría",
                               categorias.get(limpio(fila.get("Categoría"))), 50, nombre),
            descripcion=limpio(fila.get("Descripción")),
            precio_costo=costo, precio_venta=neto,
        )
        productos.append(producto)
        stock = _stock_inicial(fila.get("stock_actual"), informe, nombre)
        if stock > 0:
            # El trigger suma el stock y calcula el saldo; acá no se toca
            # stock_actual.
            productos.append(KardexMovimiento(
                producto=producto, usuario=usuario_migracion,
                tipo_movimiento="ENTRADA", cantidad_movida=stock,
            ))
            informe.cargados["kardex (stock inicial)"] += 1
            informe.stock_esperado += stock
    db.add_all(productos)
    informe.cargados["productos"] = nombres.total()


def _servicios(db, filas, informe: Informe) -> None:
    servicios = []
    categorias = canonizar_categorias(
        (fila.get("Categoría del servicio") for fila in filas), informe, "servicios",
    )
    for fila in filas:
        nombre = limpio(fila.get("Nombre del servicio"))
        precio = numero(fila.get("Precio"))
        if not nombre or precio is None or precio < 0:
            informe.descartar("servicios", "sin nombre o sin precio", str(fila))
            continue
        servicios.append(Servicio(
            nombre=recortar(informe, "servicios", "nombre", nombre, 100, nombre),
            categoria=recortar(informe, "servicios", "categoría",
                               categorias.get(limpio(fila.get("Categoría del servicio"))), 50, nombre),
            precio_venta=precio,
        ))
    db.add_all(servicios)
    informe.cargados["servicios"] = len(servicios)


def main(argv: list[str]) -> int:
    if not argv or argv[0].startswith("-"):
        print(__doc__)
        return 2
    carpeta = Path(argv[0])
    planillas = {clave: leer_xlsx(carpeta / archivo) for clave, archivo in PLANILLAS.items()}
    for clave, filas in planillas.items():
        print(f"{PLANILLAS[clave]}: {len(filas)} filas")

    with SessionLocal() as db:
        informe = migrar(db, planillas)
        if informe is None:
            print(f"La base ya tiene la migración (existe el usuario '{USUARIO_MIGRACION}'). "
                  "Nada que hacer.")
            return 0
        informe.imprimir(con_detalle="--detalle" in argv)
        cuadre(db, informe.stock_esperado)
        db.commit()
    print("\nListo: todo quedó en una sola transacción.")
    return 0


def cuadre(db, esperado: int) -> None:
    """Las unidades aceptadas de la planilla tienen que estar, exactamente, en
    el Kardex y en `productos.stock_actual`: ni una más (el trigger no sumó dos
    veces) ni una menos. Si no cuadra, no se confirma nada."""
    migrados = (
        select(KardexMovimiento.producto_id)
        .join(Usuario).where(Usuario.username == USUARIO_MIGRACION)
    )
    en_kardex = db.scalar(
        select(func.coalesce(func.sum(KardexMovimiento.cantidad_movida), 0))
        .where(KardexMovimiento.producto_id.in_(migrados))
    )
    en_stock = db.scalar(
        select(func.coalesce(func.sum(Producto.stock_actual), 0))
        .where(Producto.id.in_(migrados))
    )
    cuadra = esperado == en_kardex == en_stock
    print(f"\nStock inicial: planilla {esperado}, Kardex {en_kardex}, "
          f"productos {en_stock} -> {'cuadra' if cuadra else 'NO CUADRA'}")
    if not cuadra:
        raise SystemExit("El stock no cuadra: no se confirma nada.")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""Carga masiva de inventario desde una plantilla Excel (Propuesta 3.5).

Distinta de la migración del sistema antiguo: esta la usa el taller después,
para cargar mercadería nueva sin picarla a mano. Sin dependencias de UI; el
diálogo de Inventario solo elige el archivo y muestra lo que sale de acá.

Todo o nada: si una fila no pasa la validación no se escribe ninguna. Una
carga parcial que después se repite corregida sumaría dos veces el stock de
las filas que sí habían entrado.
"""
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from .models import KardexMovimiento, Producto, Ubicacion
from .texto import normalizar
from .xlsx import escribir_xlsx

COLUMNAS = [
    "Nombre", "Marca", "Categoría", "Ubicación", "Descripción",
    "Precio costo", "Precio venta neto", "Stock", "Stock mínimo",
]
OBLIGATORIAS = ("Nombre", "Precio costo", "Precio venta neto", "Stock")
EJEMPLO = ["Aceite 5W30 Mobil 4L", "Mobil", "Aceite Motor", "Mueble 2 - Repisa B",
           "Sintético", 20000, 35000, 24, 5]


def guardar_plantilla(ruta) -> None:
    """La plantilla que se le entrega al taller: los encabezados y una fila de ejemplo."""
    escribir_xlsx(ruta, COLUMNAS, [EJEMPLO])


def _texto(valor) -> str | None:
    valor = (valor or "").strip() if isinstance(valor, str) else valor
    return valor or None


def _numero(valor, minimo=0) -> Decimal | None:
    try:
        n = Decimal(str(valor).strip().replace(",", "."))
    except (InvalidOperation, AttributeError):
        return None
    return n if n >= minimo else None


def _entero(valor) -> int | None:
    n = _numero(valor)
    return int(n) if n is not None and n == n.to_integral_value() else None


def validar(filas: list[dict]) -> tuple[list[dict], list[str]]:
    """Devuelve (filas limpias, motivos de rechazo). Con un solo rechazo no
    se carga nada; el operador corrige la planilla y la vuelve a subir."""
    if not filas:
        return [], ["La planilla no tiene filas."]
    faltantes = [c for c in OBLIGATORIAS if c not in filas[0]]
    if faltantes:
        return [], [f"Faltan columnas obligatorias: {', '.join(faltantes)}. "
                    "Usa la plantilla del sistema."]

    limpias, rechazos, vistos = [], [], set()
    for numero, fila in enumerate(filas, 2):  # la fila 1 es el encabezado
        nombre = _texto(fila.get("Nombre"))
        costo = _numero(fila.get("Precio costo"))
        venta = _numero(fila.get("Precio venta neto"))
        stock = _entero(fila.get("Stock"))
        minimo = _entero(fila.get("Stock mínimo") or 0)
        if not nombre:
            rechazos.append(f"Fila {numero}: sin nombre.")
            continue
        if normalizar(nombre) in vistos:
            rechazos.append(f"Fila {numero}: '{nombre}' está repetido en la planilla.")
            continue
        vistos.add(normalizar(nombre))
        if costo is None or venta is None:
            rechazos.append(f"Fila {numero}: '{nombre}' necesita precio costo y precio venta neto (números, sin $).")
            continue
        if stock is None or minimo is None:
            rechazos.append(f"Fila {numero}: '{nombre}' necesita stock y stock mínimo enteros, 0 o más.")
            continue
        limpias.append({
            "nombre": nombre, "marca": _texto(fila.get("Marca")),
            "categoria": _texto(fila.get("Categoría")), "ubicacion": _texto(fila.get("Ubicación")),
            "descripcion": _texto(fila.get("Descripción")),
            "precio_costo": costo, "precio_venta": venta, "stock": stock, "stock_minimo": minimo,
        })
    return limpias, rechazos


def clasificar(db, limpias: list[dict]) -> None:
    """Marca cada fila como 'nuevo' o 'existente' (mismo nombre, sin tildes ni
    mayúsculas). A un existente solo se le suma el stock: sus precios y datos
    no se pisan desde una planilla."""
    existentes = {normalizar(nombre): pid for pid, nombre in db.execute(select(Producto.id, Producto.nombre))}
    for fila in limpias:
        fila["producto_id"] = existentes.get(normalizar(fila["nombre"]))
        fila["situacion"] = "existente" if fila["producto_id"] else "nuevo"


def cargar(db, limpias: list[dict], usuario_id: int) -> dict:
    """Escribe las filas ya validadas y clasificadas. El stock entra por Kardex
    ENTRADA: el trigger mueve `stock_actual` y calcula el saldo."""
    cuenta = {"nuevos": 0, "existentes": 0, "unidades": 0}
    ubicaciones = {u.descripcion: u for u in db.scalars(select(Ubicacion))}
    for fila in limpias:
        if fila["producto_id"] is None:
            ubicacion = None
            if fila["ubicacion"]:
                ubicacion = ubicaciones.get(fila["ubicacion"])
                if ubicacion is None:
                    ubicacion = ubicaciones[fila["ubicacion"]] = Ubicacion(descripcion=fila["ubicacion"])
            producto = Producto(
                nombre=fila["nombre"], marca=fila["marca"], categoria=fila["categoria"],
                descripcion=fila["descripcion"], ubicacion=ubicacion,
                precio_costo=fila["precio_costo"], precio_venta=fila["precio_venta"],
                stock_minimo=fila["stock_minimo"],
            )
            db.add(producto)
            cuenta["nuevos"] += 1
        else:
            producto = db.get(Producto, fila["producto_id"])
            cuenta["existentes"] += 1
        if fila["stock"] > 0:
            db.add(KardexMovimiento(
                producto=producto, usuario_id=usuario_id,
                tipo_movimiento="ENTRADA", cantidad_movida=fila["stock"],
            ))
            cuenta["unidades"] += fila["stock"]
    db.flush()
    return cuenta

"""Las reglas del proyecto, como pruebas en vez de como párrafos.

Cada una de estas nació de algo que una revisión de código tuvo que corregir a
mano. Revisar es caro y se hace tarde; una prueba avisa en la misma corrida en
que se escribió el error, y le avisa a quien lo escribió, no a quien audita
después.
"""
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parent.parent
FUENTES = sorted((RAIZ / "src").rglob("*.py"))


def lineas_de(archivo: pathlib.Path):
    for numero, linea in enumerate(archivo.read_text(encoding="utf-8").splitlines(), 1):
        yield numero, linea.strip()


# La aplicación mueve el stock insertando en kardex_movimientos y dejando que
# los triggers lo apliquen. La única escritura directa que se acepta es el saldo
# inicial de un producto que recién se crea, porque antes de existir no tiene
# kardex al que colgarse. Todo lo demás sería un descuadre sin rastro.
ESCRITURAS_DE_STOCK_ACEPTADAS = {
    ("inventario.py", "producto.stock_actual = self.stock_actual.value()"),
}


def test_la_aplicacion_no_escribe_el_stock():
    """La regla número uno: el stock lo mueven los triggers, no la aplicación.

    Ya se rompió una vez: el ingreso de mercadería sumaba `stock_actual` además
    de insertar el movimiento, y el trigger volvía a sumar. El stock quedó al
    doble y nadie lo notó hasta la revisión.
    """
    import re

    # El receptor importa: `self.stock_actual` es el QSpinBox del formulario,
    # `producto.stock_actual` es la columna que solo pueden mover los triggers.
    asignacion = re.compile(r"(\w+)\.stock_actual\s*(?:=[^=]|\+=|-=)")

    encontradas = []
    for archivo in FUENTES:
        for numero, linea in lineas_de(archivo):
            calce = asignacion.search(linea)
            if not calce or calce.group(1) == "self":
                continue
            if (archivo.name, linea) in ESCRITURAS_DE_STOCK_ACEPTADAS:
                continue
            encontradas.append(f"{archivo.relative_to(RAIZ)}:{numero}  {linea}")
    assert not encontradas, (
        "el stock se mueve con un movimiento de kardex, no asignándolo:\n  "
        + "\n  ".join(encontradas)
    )


def test_ningun_widget_escribe_un_color_a_mano():
    """Los colores viven solo en tema.py, como dice su propio docstring."""
    import re

    sueltos = [
        f"{archivo.relative_to(RAIZ)}: {hallazgo}"
        for archivo in FUENTES
        if archivo.name != "tema.py"
        for hallazgo in re.findall(r'"#[0-9A-Fa-f]{3,6}"', archivo.read_text(encoding="utf-8"))
    ]
    assert not sueltos, f"colores fuera de tema.py: {sueltos}"


def test_las_pantallas_usan_los_layouts_del_sistema():
    """Márgenes y espaciado salen de `layout_de_pantalla()` y `layout_de_dialogo()`.

    Tres pantallas se escribieron con el margen por defecto de Qt —11px contra
    los 14/20 del resto— y la diferencia solo se ve poniendo dos ventanas al
    lado. Los layouts sobre paneles internos de un splitter sí van a mano,
    porque sus márgenes son la canaleta entre los dos lados.
    """
    crudos = [
        f"{archivo.relative_to(RAIZ)}:{numero}"
        for archivo in (RAIZ / "src" / "ui").glob("*.py")
        if archivo.name != "comunes.py"  # es donde viven los helpers
        for numero, linea in lineas_de(archivo)
        if "QVBoxLayout(self)" in linea
    ]
    assert not crudos, (
        "usa layout_de_pantalla() o layout_de_dialogo() en vez de QVBoxLayout(self):\n  "
        + "\n  ".join(crudos)
    )

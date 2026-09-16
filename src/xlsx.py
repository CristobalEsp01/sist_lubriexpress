"""Leer y escribir .xlsx con la biblioteca estándar.

Un .xlsx es un zip con XML adentro. Para las cinco planillas de la migración
y la plantilla de inventario no vale la pena sumar pandas y openpyxl al
proyecto (y al ejecutable del taller). Sin dependencias de UI ni de base de
datos, como rut.py.
"""
import re
import xml.etree.ElementTree as ET
import zipfile
from xml.sax.saxutils import escape

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
T = f"{{{NS['m']}}}t"


def _columna(referencia: str) -> int:
    """'AB12' -> 27 (base 0)."""
    n = 0
    for letra in re.match(r"[A-Z]+", referencia).group():
        n = n * 26 + ord(letra) - 64
    return n - 1


def _referencia(columna: int, fila: int) -> str:
    """(27, 12) -> 'AB12'."""
    letras = ""
    columna += 1
    while columna:
        columna, resto = divmod(columna - 1, 26)
        letras = chr(65 + resto) + letras
    return f"{letras}{fila}"


def leer_xlsx(ruta) -> list[dict]:
    """Filas de la primera hoja como dicts {encabezado: texto | None}.

    Los valores vienen como texto tal cual los guarda Excel: los números con
    su coma flotante ("8319.2999999999993") y las fechas como serial ("46272").
    Convertirlos es problema de quien sabe qué columna es.
    """
    with zipfile.ZipFile(ruta) as z:
        compartidas = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
                compartidas.append("".join(t.text or "" for t in si.iter(T)))
        hoja = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))

    filas = []
    for fila in hoja.iter(f"{{{NS['m']}}}row"):
        celdas = {}
        for c in fila.findall("m:c", NS):
            v = c.find("m:v", NS)
            tipo = c.get("t")
            if tipo == "s":
                valor = compartidas[int(v.text)]
            elif tipo == "inlineStr":
                valor = "".join(t.text or "" for t in c.iter(T))
            else:
                valor = v.text if v is not None else None
            celdas[_columna(c.get("r"))] = valor
        filas.append(celdas)
    if not filas:
        return []
    ancho = max(filas[0]) + 1
    nombres = [filas[0].get(i) or f"col{i}" for i in range(ancho)]
    return [{nombres[i]: f.get(i) for i in range(ancho)} for f in filas[1:]]


_PAQUETE = {
    "[Content_Types].xml": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    ),
    "_rels/.rels": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    ),
    "xl/workbook.xml": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Hoja1" sheetId="1" r:id="rId1"/></sheets></workbook>'
    ),
    "xl/_rels/workbook.xml.rels": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    ),
}


def escribir_xlsx(ruta, encabezados: list[str], filas=()) -> None:
    """Una hoja, sin estilos: lo justo para que Excel la abra y `leer_xlsx()`
    la lea de vuelta. Los números van como número; todo lo demás como texto."""
    def celda(columna, fila, valor):
        ref = _referencia(columna, fila)
        if valor is None or valor == "":
            return ""
        if isinstance(valor, (int, float)) and not isinstance(valor, bool):
            return f'<c r="{ref}"><v>{valor}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(valor))}</t></is></c>'

    lineas = [encabezados, *filas]
    xml_filas = "".join(
        f'<row r="{n}">' + "".join(celda(c, n, v) for c, v in enumerate(linea)) + "</row>"
        for n, linea in enumerate(lineas, 1)
    )
    hoja = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{xml_filas}</sheetData></worksheet>"
    )
    with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre, contenido in _PAQUETE.items():
            z.writestr(nombre, contenido)
        z.writestr("xl/worksheets/sheet1.xml", hoja)

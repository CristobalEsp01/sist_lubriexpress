"""La ubicación de bodega que el sistema antiguo dejó escrita en la descripción.

Aquel sistema no tenía dónde guardarla, así que el mostrador la anotó en el
texto libre del producto: "Ubicación: M4-C", "M-4C", "BANDEJA 7", "Caja Wurth",
"Bajo TV". Son unas ciento veinte repisas escritas de trescientas maneras.

`detectar()` devuelve la ubicación canónica y qué queda de la descripción. No
se pierde texto nunca: la descripción solo se vacía cuando no era más que la
ubicación; si había algo más escrito, vuelve intacta y la ubicación se copia a
su columna. Un producto repartido en dos estantes se queda con el primero.

Sin dependencias de base de datos ni de UI: lo usan la migración y el relleno
de una base que ya está en producción.
"""
import re

from .texto import sin_tildes

PREFIJO = re.compile(r"(?i)^\s*ubicaci[oó]n\s*[:\-]?\s*")

# Un módulo con lado ("M4-C", "M-1 IZQ") se reconoce donde sea; uno pelado
# ("M9") solo al principio. Si no, el "M14" de "M12x1.5,M14,M16,M18" —que es
# una medida de rosca— se leería como el módulo 14.
LADO = r"IZQUIERDA|IZQ|DERECHA|DER|CENTRO|[A-E]"
PATRONES = [
    re.compile(rf"(?i)\bM\s*-?\s*\d{{1,2}}\s*[-–/ ]?\s*(?:{LADO})\b"),
    re.compile(r"(?i)^M\s*-?\s*\d{1,2}(?![x\d])"),
    re.compile(r'(?i)\bBANDEJA\s+"?\d{1,2}"?|\bBANDEJA\s+[A-Z]\b'),
    re.compile(r"(?i)\bCAJAS?\s+-?\s*(?:MA?SIVO\s*\d?|WK\s*\d?|WU[RT]?TH|FILTROS|TAPONES|"
               r"AZULES|SOBRE\s+REPISA|N\d|\d{1,2}|[A-ZÑ]\d?)\b"),
    re.compile(r"(?i)\b(?:MINI\s+)?MUEBLE\s*[-–]?\s*(?:[A-D]\b|\d|TV|EXTERIOR|EXT\.?|YPF|"
               r"REPUESTOS|SALIDA\s+[A-D]|ESCRITORIO|SOBRE\s+IMPRESORA|MEDIA\s+LUNA)"),
    re.compile(r"(?i)\bREPISA(?:\s+YPF|\s+YOF)?\b"),
    re.compile(r"(?i)\bM\s+SALIDA\s*-?\s*[AB]\b"),
    re.compile(r"(?i)\bCOLGAD\w*(?:\s+AMARILLO|\s+VITRINA)?|\bESTANTE\b|\bVITRINA\b|"
               r"\bESQUINA(?:\s+\w+){0,2}|\bBAJO\s+TV\b|\bSOBRE\s+REFRI\b|\bTRAS\s+OFICINA\b|"
               r"\bLUGAR\s+CIELO\s+OFICINA\b"),
]

ERRATAS = {"MSIVO": "MASIVO", "WUTH": "WURTH", "WURT": "WURTH", "YOF": "YPF",
           "IZQUIERDA": "IZQ", "DERECHA": "DER", "EXT": "EXTERIOR",
           "COLGADO": "COLGADOR", "COLGADA": "COLGADOR", "COLGADAS": "COLGADOR",
           "COLGADDDO": "COLGADOR", "COLGADAS": "COLGADOR"}


def _canonico(bruto: str) -> str:
    # La Ñ se salva de sin_tildes: "CAJA Ñ" es el nombre de una caja de verdad
    # y el mostrador la busca así, no como "CAJA N".
    texto = sin_tildes(bruto.replace("Ñ", "\x00").replace("ñ", "\x00"))
    texto = texto.upper().replace("\x00", "Ñ").replace('"', " ").replace("'", " ")
    modulo = re.match(rf"^M\s*-?\s*0*(\d{{1,2}})\s*[-–/ ]?\s*({LADO})?", texto)
    if modulo and not texto.startswith("M SALIDA"):
        lado = ERRATAS.get(modulo.group(2) or "", modulo.group(2) or "")
        return f"M{modulo.group(1)}" + (f"-{lado}" if lado else "")

    texto = re.sub(r"[-–/]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip(" .")
    texto = re.sub(r"\b(MA?SIVO|WK)\s*(\d)", r"\1 \2", texto)
    palabras = [ERRATAS.get(palabra, palabra) for palabra in texto.split()]
    texto = " ".join(palabras)
    return re.sub(r"\b(BANDEJA|CAJA|CAJAS)\s+0+(\d)", r"\1 \2", texto)


def detectar(descripcion: str | None) -> tuple[str | None, str | None]:
    """(ubicación canónica, descripción que queda). Ver el módulo."""
    if not descripcion or not descripcion.strip():
        return None, descripcion or None

    cuerpo = PREFIJO.sub("", descripcion).strip()
    hallazgos = [m for m in (p.search(cuerpo) for p in PATRONES) if m]
    if not hallazgos:
        return None, descripcion

    # El de más a la izquierda: un producto repartido en dos estantes se queda
    # con el primero que anotaron, y la descripción entera lo dice igual.
    encontrado = min(hallazgos, key=lambda m: m.start())
    resto = (cuerpo[:encontrado.start()] + " " + cuerpo[encontrado.end():])
    sobra = re.sub(r"[\s().,;:\-–/]", "", resto)
    return _canonico(encontrado.group(0)), None if not sobra else descripcion

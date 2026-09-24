"""Identidad visual de la aplicación.

Azul sobre pizarra, con la paleta de Tailwind CSS: tonos ya medidos y usados
en miles de aplicaciones, en vez de una escala inventada acá. El acento se
reserva para donde el sistema está diciendo algo —la pestaña activa, el campo
con foco, la fila seleccionada, el botón principal—; todo lo demás es escala
de grises. Un color que aparece en todas partes no señala nada. El ámbar del
logo queda para el logo, que es donde identifica al taller.

Los colores y medidas viven solo acá: ningún widget escribe un hex a mano.
"""
from functools import cache
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

RECURSOS = Path(__file__).resolve().parent / "recursos"
LOGO = RECURSOS / "logo.jpeg"   # para el membrete del PDF
# El ícono va en .ico y recortado al círculo: Windows lo pide cuadrado para la
# barra de tareas, y el .jpeg del logo es más alto que ancho. Se genera con
#   ffmpeg -i logo.jpeg -vf "crop=1080:1080:0:34,scale=256:256" -pix_fmt bgra logo.ico
ICONO = RECURSOS / "logo.ico"

# Cada par texto/fondo de esta paleta está medido contra WCAG 2.1 AA: 4.5:1 para
# texto y 3:1 para bordes de control. Los tonos oscuros de cada color existen
# porque el tono medio no llegaba: ámbar 600 sobre el fondo da 3.02, y el mismo
# ámbar relleno con texto blanco da 3.19. Hay una prueba que mide los 26 pares.
FONDO = "#F8FAFC"          # slate 50
SUPERFICIE = "#FFFFFF"
TINTA = "#0F172A"          # slate 900
TINTA_SUAVE = "#64748B"    # slate 500

# Dos bordes con dos trabajos. El decorativo separa; el de campo delimita un
# control y por eso tiene que ser perceptible: un input blanco sobre un fondo
# casi blanco, con un borde de 1.23:1, es invisible hasta que recibe el foco.
BORDE = "#E2E8F0"
BORDE_CAMPO = "#7D8DA5"
BORDE_SUAVE = "#F1F5F9"

# Azul Tailwind. El claro señala (borde con foco, subrayado de pestaña); el
# oscuro es el que se puede leer como texto y rellenar con blanco encima.
ACENTO = "#2563EB"         # blue 600
ACENTO_OSCURO = "#1D4ED8"  # blue 700
ACENTO_PROFUNDO = "#1E40AF"  # blue 800
ACENTO_FONDO = "#DBEAFE"   # blue 100

ALERTA = "#B91C1C"
ALERTA_FONDO = "#FEE2E2"
EXITO = "#15803D"
EXITO_FONDO = "#DCFCE7"
# Teal y no azul: el azul es el acento, y dos insignias del mismo color no
# distinguen nada.
INFO = "#0F766E"           # teal 700
INFO_FONDO = "#CCFBF1"     # teal 100
ALTERNA = "#F8FAFC"
NEUTRAL_FONDO = "#F1F5F9"
NEUTRAL_TEXTO = "#475569"

# Solo para controles deshabilitados: la pauta exime a los inactivos del mínimo
# de contraste, y es justamente lo apagado lo que comunica que no se pueden
# usar. Para texto que sí hay que leer —un aviso, una fila inactiva— va
# TINTA_SUAVE, que sí lo cumple.
APAGADO = "#94A3B8"

ALTO_FILA = 36
# Tope para una columna ajustada a su contenido: una marca de 30 caracteres
# no puede empujar el stock y el precio fuera de la pantalla.
ANCHO_MAX_COLUMNA = 280
CUERPO_PT = 10

# El espaciado también es del tema: estaba copiado a mano en cinco pantallas y
# las tres nuevas se quedaron con el margen por defecto de Qt.
MARGEN_PANTALLA = (14, 12, 14, 10)
MARGEN_DIALOGO = (20, 18, 20, 18)
ESPACIO_PANTALLA = 8
ESPACIO_DIALOGO = 16
ESPACIO_BARRA = 10
ESPACIO_FORMULARIO = 12
CANAL_PANEL = 10   # separación entre los dos lados de un splitter
INSIGNIA_PT = 9    # tipografía de las pastillas de estado

# Familias monoespaciadas en orden de preferencia: Windows, Linux, macOS.
# Con figuras de ancho fijo las columnas de stock y precios calzan dígito con
# dígito y el inventario se lee de un vistazo.
MONOESPACIADAS = ["Consolas", "DejaVu Sans Mono", "Menlo", "Liberation Mono", "monospace"]
FAMILIAS_MONO = ", ".join(f'"{f}"' for f in MONOESPACIADAS)

# Qt trae sus propias flechas como recursos internos. Apenas se aplica una hoja
# de estilos a un QComboBox o QSpinBox, Qt deja de dibujar la flecha nativa y hay
# que dársela explícitamente; usar las suyas evita sumar imágenes al proyecto y
# empaquetarlas aparte.
ICONOS_QT = ":/qt-project.org/styles/commonstyle/images"

HOJA_DE_ESTILOS = f"""
QWidget {{
    background: {FONDO};
    color: {TINTA};
    font-size: 13px;
}}

QTabWidget::pane {{
    border: none;
    border-top: 1px solid {BORDE};
    background: {FONDO};
}}
QTabBar::tab {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 10px 22px;
    margin-right: 6px;
    color: {TINTA_SUAVE};
    font-weight: 500;
}}
QTabBar::tab:hover {{
    color: {TINTA};
    background: {BORDE_SUAVE};
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}}
QTabBar::tab:selected {{
    color: {ACENTO_OSCURO};
    border-bottom: 2px solid {ACENTO};
    font-weight: 600;
}}

/* La lista de reportes: se lee como navegación, no como una tabla más. */
QListWidget[clase="navegacion"] {{
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget[clase="navegacion"]::item {{
    padding: 8px 12px;
    margin-bottom: 2px;
    border-radius: 5px;
    color: {TINTA_SUAVE};
}}
QListWidget[clase="navegacion"]::item:hover {{
    background: {BORDE_SUAVE};
    color: {TINTA};
}}
QListWidget[clase="navegacion"]::item:selected {{
    background: {ACENTO_FONDO};
    color: {ACENTO_OSCURO};
    font-weight: 600;
}}

QTableWidget {{
    background: {SUPERFICIE};
    alternate-background-color: {ALTERNA};
    border: 1px solid {BORDE};
    border-radius: 6px;
    gridline-color: transparent;
    selection-background-color: {ACENTO_FONDO};
    selection-color: {TINTA};
    outline: none;
}}
QTableWidget::item {{
    padding: 6px 10px;
    border: none;
}}
QTableWidget::item:selected {{
    background-color: {ACENTO_FONDO};
    color: {TINTA};
}}
QHeaderView::section {{
    background: {FONDO};
    color: {TINTA_SUAVE};
    padding: 9px 10px;
    border: none;
    border-bottom: 1px solid {BORDE};
    font-weight: 600;
    font-size: 12px;
}}
QTableCornerButton::section {{
    background: {FONDO};
    border: none;
    border-bottom: 1px solid {BORDE};
}}

QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{
    background: {SUPERFICIE};
    border: 1px solid {BORDE_CAMPO};
    border-radius: 5px;
    padding: 7px 10px;
    color: {TINTA};
    selection-background-color: {ACENTO_FONDO};
    selection-color: {TINTA};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{
    border: 1px solid {ACENTO};
    background: {SUPERFICIE};
}}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled, QPlainTextEdit:disabled {{
    background: {BORDE_SUAVE};
    color: {APAGADO};
    border-color: {BORDE};
}}
/* Lista hacia abajo y con tope de filas: con Fusion se centraba en la opción
   elegida y crecía hasta el alto de la pantalla. */
QComboBox {{
    combobox-popup: 0;
}}
QComboBox::drop-down {{
    border: none;
    width: 26px;
}}
QComboBox::down-arrow {{
    image: url({ICONOS_QT}/arrow-down-16.png);
    width: 10px;
    height: 10px;
}}
QComboBox QAbstractItemView {{
    background: {SUPERFICIE};
    border: 1px solid {BORDE};
    selection-background-color: {ACENTO_FONDO};
    selection-color: {TINTA};
    padding: 4px;
    border-radius: 4px;
}}
QComboBox QAbstractItemView::item {{
    min-height: 26px;
    padding: 0 6px;
}}
QSpinBox {{
    padding-right: 22px;
}}
QSpinBox::up-button, QSpinBox::down-button {{
    subcontrol-origin: border;
    width: 20px;
    border: none;
    background: transparent;
}}
QSpinBox::up-button {{
    subcontrol-position: top right;
}}
QSpinBox::down-button {{
    subcontrol-position: bottom right;
}}
QSpinBox::up-arrow {{
    image: url({ICONOS_QT}/arrow-up-16.png);
    width: 9px;
    height: 9px;
}}
QSpinBox::down-arrow {{
    image: url({ICONOS_QT}/arrow-down-16.png);
    width: 9px;
    height: 9px;
}}

QDialog {{
    background: {FONDO};
}}
QDialog QFormLayout {{
    spacing: 12px;
}}
QDialogButtonBox {{
    button-layout: 2;
}}

QPushButton {{
    background: {SUPERFICIE};
    border: 1px solid {BORDE_CAMPO};
    border-radius: 5px;
    padding: 7px 16px;
    color: {TINTA};
    font-weight: 500;
}}
QPushButton:hover {{
    border-color: {ACENTO};
    background: {SUPERFICIE};
    color: {ACENTO_OSCURO};
}}
QPushButton:pressed {{
    background: {ACENTO_FONDO};
}}
QPushButton:disabled {{
    color: {APAGADO};
    border-color: {BORDE_SUAVE};
    background: {BORDE_SUAVE};
}}
QPushButton[clase="primario"] {{
    background: {ACENTO_OSCURO};
    border: 1px solid {ACENTO_OSCURO};
    color: {SUPERFICIE};
    font-weight: 600;
}}
QPushButton[clase="primario"]:hover {{
    background: {ACENTO_PROFUNDO};
    border-color: {ACENTO_PROFUNDO};
    color: {SUPERFICIE};
}}
QPushButton[clase="primario"]:pressed {{
    background: {ACENTO_PROFUNDO};
    border-color: {ACENTO_PROFUNDO};
}}
QPushButton[clase="primario"]:disabled {{
    background: {BORDE_SUAVE};
    border-color: {BORDE_SUAVE};
    color: {APAGADO};
}}

QLabel[clase="seccion"] {{
    color: {TINTA};
    font-weight: 600;
    font-size: 13px;
    padding: 4px 2px;
}}
QLabel[clase="error"] {{
    color: {ALERTA};
    font-size: 12px;
}}
QLabel[clase="titulo"] {{
    color: {TINTA};
    font-weight: 700;
    font-size: 20px;
}}
QFrame[clase="tarjeta"] {{
    background: {SUPERFICIE};
    border: 1px solid {BORDE};
    border-radius: 8px;
}}
QFrame[clase="tarjeta"] QLabel {{
    background: transparent;
}}
QLabel[clase="tarjeta-titulo"] {{
    color: {TINTA};
    font-weight: 600;
    font-size: 14px;
}}
QLabel[clase="tarjeta-texto"] {{
    color: {TINTA_SUAVE};
    font-size: 12px;
}}
QFrame[clase="tarjeta"] QLabel[clase="patente"] {{
    font-family: {FAMILIAS_MONO};
    font-size: 22px;
    font-weight: 700;
    color: {ACENTO_OSCURO};
    background: {ACENTO_FONDO};
    border-radius: 6px;
    padding: 6px 12px;
}}
QLabel[clase="resumen"] {{
    color: {TINTA_SUAVE};
    font-size: 12px;
    padding: 3px 2px;
}}
QLabel[clase="aviso"] {{
    background: {ALERTA_FONDO};
    color: {ALERTA};
    border-radius: 6px;
    padding: 8px 12px;
}}
QLabel[clase="aviso-vacio"] {{
    background: transparent;
    color: {TINTA_SUAVE};
    font-style: italic;
    padding: 12px;
}}

/* El total es el resultado de la pantalla, no un campo más del formulario: va
   sobre su propia superficie, separado por una línea, como el pie de una
   boleta. La cifra en monoespaciada para que no baile de ancho al escribir. */
QFrame[clase="total"] {{
    background: {SUPERFICIE};
    border: none;
    border-top: 1px solid {BORDE};
    border-radius: 0;
}}
QFrame[clase="total"] QLabel {{
    background: transparent;
}}
QLabel[clase="total-rotulo"] {{
    color: {TINTA_SUAVE};
    font-size: 12px;
    font-weight: 600;
}}
QLabel[clase="total-cifra"] {{
    font-family: {FAMILIAS_MONO};
    font-size: 30px;
    font-weight: 700;
    color: {TINTA};
}}
QLabel[clase="total-cifra-menor"] {{
    font-family: {FAMILIAS_MONO};
    font-size: 20px;
    font-weight: 700;
    color: {TINTA};
}}
QLabel[clase="total-cifra-desglose"] {{
    font-family: {FAMILIAS_MONO};
    font-size: 13px;
    color: {TINTA_SUAVE};
}}

QSplitter::handle:vertical {{
    background: {BORDE};
    height: 1px;
    margin: 2px 0;
}}
QSplitter::handle:horizontal {{
    background: {BORDE};
    width: 1px;
    margin: 0 2px;
}}

QCheckBox {{
    spacing: 8px;
    color: {TINTA};
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {BORDE};
    border-radius: 4px;
    background: {SUPERFICIE};
}}
QCheckBox::indicator:checked {{
    background: {ACENTO};
    border-color: {ACENTO};
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDE};
    border-radius: 5px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: {APAGADO};
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {BORDE};
    border-radius: 5px;
    min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {APAGADO};
}}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none;
    border: none;
    height: 0;
    width: 0;
}}

QToolTip {{
    background: {TINTA};
    color: {SUPERFICIE};
    border: none;
    border-radius: 4px;
    padding: 5px 8px;
    font-size: 11px;
}}
"""


def fuente_tabular(negrita: bool = False) -> QFont:
    """Monoespaciada para cifras: los dígitos quedan alineados. Copia de una
    cacheada (armarla por celda costaba ~130 ms en el catálogo)."""
    return QFont(_fuente_tabular(negrita))


@cache
def _fuente_tabular(negrita: bool) -> QFont:
    fuente = QFont()
    fuente.setFamilies(MONOESPACIADAS)
    fuente.setStyleHint(QFont.Monospace)
    fuente.setPointSize(CUERPO_PT)
    fuente.setBold(negrita)
    return fuente


def aplicar(app: QApplication) -> None:
    """Fija el estilo y la paleta.

    Fusion explícito: sin esto Qt usa el estilo nativo de cada sistema y la
    aplicación se ve distinta en el Arch de desarrollo que en el Windows del
    taller.
    """
    if ICONO.is_file():
        app.setWindowIcon(QIcon(str(ICONO)))

    # Chile usa punto para los miles: sin esto los QSpinBox muestran $ 20,000.
    QLocale.setDefault(QLocale(QLocale.Spanish, QLocale.Chile))

    # qtbase_es.qm viene dentro de PySide6 y traduce los botones estándar
    # (Guardar, Cancelar, Sí, No). Al empaquetar con PyInstaller hay que
    # incluir el archivo o los diálogos vuelven al inglés.
    traductor = QTranslator(app)
    if traductor.load(QLocale(), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(traductor)

    app.setStyle("Fusion")
    cuerpo = app.font()
    cuerpo.setPointSize(CUERPO_PT)
    app.setFont(cuerpo)
    app.setStyleSheet(HOJA_DE_ESTILOS)

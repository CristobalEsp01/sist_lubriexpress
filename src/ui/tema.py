"""Identidad visual de la aplicación.

Ámbar de aceite sobre grafito. El acento sale del material con el que trabaja
el negocio y se reserva para donde el sistema está diciendo algo —la pestaña
activa, el campo con foco, la fila seleccionada, el stock bajo mínimo—; todo
lo demás es escala de grises. Un color que aparece en todas partes no señala
nada.

Los colores y medidas viven solo acá: ningún widget escribe un hex a mano.
"""
from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

FONDO = "#F8F9FA"
SUPERFICIE = "#FFFFFF"
TINTA = "#1E232A"
TINTA_SUAVE = "#64748B"
BORDE = "#E2E8F0"
BORDE_SUAVE = "#F1F5F9"
ACENTO = "#D97706"
ACENTO_HOVER = "#B45309"
ACENTO_FONDO = "#FEF3C7"
ALERTA = "#DC2626"
ALERTA_FONDO = "#FEE2E2"
EXITO = "#16A34A"
EXITO_FONDO = "#DCFCE7"
INFO = "#2563EB"
INFO_FONDO = "#DBEAFE"
ALTERNA = "#FAFAFA"
APAGADO = "#94A3B8"
NEUTRAL_FONDO = "#F1F5F9"
NEUTRAL_TEXTO = "#475569"

ALTO_FILA = 36
CUERPO_PT = 10

# Familias monoespaciadas en orden de preferencia: Windows, Linux, macOS.
# Con figuras de ancho fijo las columnas de stock y precios calzan dígito con
# dígito y el inventario se lee de un vistazo.
MONOESPACIADAS = ["Consolas", "DejaVu Sans Mono", "Menlo", "Liberation Mono", "monospace"]

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
    color: {ACENTO};
    border-bottom: 2px solid {ACENTO};
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
    border: 1px solid {BORDE};
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
    border: 1px solid {BORDE};
    border-radius: 5px;
    padding: 7px 16px;
    color: {TINTA};
    font-weight: 500;
}}
QPushButton:hover {{
    border-color: {ACENTO};
    background: {SUPERFICIE};
    color: {ACENTO_HOVER};
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
    background: {ACENTO};
    border: 1px solid {ACENTO};
    color: {SUPERFICIE};
    font-weight: 600;
}}
QPushButton[clase="primario"]:hover {{
    background: {ACENTO_HOVER};
    border-color: {ACENTO_HOVER};
    color: {SUPERFICIE};
}}
QPushButton[clase="primario"]:pressed {{
    background: #92400E;
    border-color: #92400E;
}}
QPushButton[clase="primario"]:disabled {{
    background: {BORDE_SUAVE};
    border-color: {BORDE_SUAVE};
    color: {APAGADO};
}}

QPushButton[clase="accion-rapida"] {{
    background: {SUPERFICIE};
    border: 1px solid {ACENTO};
    color: {ACENTO_HOVER};
    font-weight: 600;
}}
QPushButton[clase="accion-rapida"]:hover {{
    background: {ACENTO_FONDO};
}}
QPushButton[clase="accion-rapida"]:disabled {{
    border-color: {BORDE};
    color: {APAGADO};
}}

QLabel[clase="seccion"] {{
    color: {TINTA};
    font-weight: 600;
    font-size: 13px;
    padding: 4px 2px;
}}
QLabel[clase="resumen"] {{
    color: {TINTA_SUAVE};
    font-size: 12px;
    padding: 3px 2px;
}}
QLabel[clase="aviso-vacio"] {{
    color: {APAGADO};
    font-style: italic;
    padding: 12px;
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
    """Monoespaciada para columnas numéricas: los dígitos quedan alineados."""
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

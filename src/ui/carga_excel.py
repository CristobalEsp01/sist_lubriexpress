"""Diálogo de carga masiva de inventario: elegir la planilla, ver qué va a
entrar y qué se rechaza, y confirmar. La lógica vive en src/carga_excel.py."""
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
    QTableWidgetItem,
)
from sqlalchemy.exc import IntegrityError

from ..auth import Sesion
from ..carga_excel import cargar, clasificar, guardar_plantilla, validar
from ..database import SessionLocal
from ..xlsx import leer_xlsx
from .comunes import (
    BADGE_EXITO, BADGE_INFO, ROL_INSIGNIA, ItemNumerico, barra, clp, con_aviso_vacio,
    crear_tabla, layout_de_dialogo, reordenar,
)

COLUMNAS = ["Producto", "Situación", "Stock", "Costo", "Venta neto"]


class CargaExcelDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cargar inventario desde Excel")
        self.resize(720, 480)
        self.setModal(True)
        self.limpias: list[dict] = []

        self.boton_plantilla = QPushButton("Guardar plantilla…")
        self.boton_plantilla.setAutoDefault(False)
        self.boton_plantilla.clicked.connect(self.guardar_plantilla)
        self.boton_archivo = QPushButton("Elegir planilla…")
        self.boton_archivo.setProperty("clase", "primario")
        self.boton_archivo.clicked.connect(self.elegir_archivo)
        self.archivo = QLabel("Ninguna planilla elegida.")

        self.tabla = con_aviso_vacio(
            crear_tabla(COLUMNAS, ancha=0, orden=0, numericas=(2, 3, 4)),
            "Elige una planilla para ver qué va a entrar.",
        )
        self.rechazos = QPlainTextEdit()
        self.rechazos.setReadOnly(True)
        self.rechazos.setPlaceholderText("Lo que no pase la validación aparece acá.")
        self.rechazos.setMaximumHeight(110)

        self.boton_cargar = QPushButton("Cargar")
        self.boton_cargar.setProperty("clase", "primario")
        self.boton_cargar.setAutoDefault(False)
        self.boton_cargar.setEnabled(False)
        self.boton_cargar.clicked.connect(self.cargar)
        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.setAutoDefault(False)
        boton_cerrar.clicked.connect(self.reject)

        layout = layout_de_dialogo(self)
        layout.addLayout(barra(self.boton_plantilla, self.boton_archivo, self.archivo, estira=2))
        layout.addWidget(self.tabla, 1)
        layout.addWidget(self.rechazos)
        layout.addLayout(barra(boton_cerrar, self.boton_cargar, estira=0))

    def guardar_plantilla(self) -> None:
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Guardar plantilla", "plantilla_inventario.xlsx", "Excel (*.xlsx)"
        )
        if ruta:
            guardar_plantilla(ruta)

    def elegir_archivo(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(self, "Elegir planilla", "", "Excel (*.xlsx)")
        if ruta:
            self.previsualizar(ruta)

    def previsualizar(self, ruta) -> None:
        """Lee, valida y muestra. Cargar se enciende solo si nada se rechazó."""
        self.archivo.setText(str(ruta))
        try:
            filas = leer_xlsx(ruta)
        except (OSError, KeyError, ValueError) as e:
            self.limpias = []
            self.rechazos.setPlainText(f"No se pudo leer la planilla: {e}")
            self.tabla.setRowCount(0)
            self.boton_cargar.setEnabled(False)
            return
        self.limpias, rechazos = validar(filas)
        with SessionLocal() as db:
            clasificar(db, self.limpias)

        self.tabla.setSortingEnabled(False)
        self.tabla.setRowCount(len(self.limpias))
        for fila, item in enumerate(self.limpias):
            situacion = QTableWidgetItem(item["situacion"])
            situacion.setData(ROL_INSIGNIA, BADGE_EXITO if item["situacion"] == "nuevo" else BADGE_INFO)
            self.tabla.setItem(fila, 0, QTableWidgetItem(item["nombre"]))
            self.tabla.setItem(fila, 1, situacion)
            self.tabla.setItem(fila, 2, ItemNumerico(str(item["stock"]), item["stock"]))
            self.tabla.setItem(fila, 3, ItemNumerico(clp(item["precio_costo"]), item["precio_costo"]))
            self.tabla.setItem(fila, 4, ItemNumerico(clp(item["precio_venta"]), item["precio_venta"]))
        reordenar(self.tabla)
        self.rechazos.setPlainText("\n".join(rechazos))
        self.boton_cargar.setEnabled(bool(self.limpias) and not rechazos)

    def cargar(self) -> None:
        if not Sesion.activa():
            QMessageBox.critical(self, "Error", "No hay sesión activa.")
            return
        if not self.limpias or self.rechazos.toPlainText():
            return
        with SessionLocal() as db:
            try:
                cuenta = cargar(db, self.limpias, Sesion.usuario_id)
                db.commit()
            except IntegrityError as e:
                db.rollback()
                QMessageBox.warning(
                    self, "No se pudo cargar", f"La base de datos rechazó la carga:\n\n{e.orig}"
                )
                return
        QMessageBox.information(
            self, "Inventario cargado",
            f"{cuenta['nuevos']} producto(s) nuevo(s), {cuenta['existentes']} existente(s) "
            f"con stock sumado, {cuenta['unidades']} unidades en total.",
        )
        self.accept()

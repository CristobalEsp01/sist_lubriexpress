"""Mantenedor de usuarios —quién entra al sistema y con qué rol— y de
mecánicos, que trabajan los autos y no siempre tienen cuenta.

Solo lo ve un ADMINISTRADOR (ver permisos.py). El primer administrador de una
instalación nueva se crea con scripts/crear_usuario.py; de ahí en adelante,
todo pasa por acá.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSplitter, QTableWidgetItem, QVBoxLayout, QWidget,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..auth import Sesion, hash_password
from ..database import SessionLocal
from ..models import Mecanico, Usuario
from .comunes import (
    BADGE_EXITO, BADGE_NEUTRAL, ROL_INSIGNIA, barra, botonera, con_aviso_vacio,
    crear_tabla, exigir_permiso, layout_de_dialogo, layout_de_pantalla, reordenar,
)
from .tema import CANAL_PANEL, ESPACIO_FORMULARIO

COLUMNAS = ["Nombre", "Usuario", "Rol", "Estado"]
COLUMNAS_MECANICOS = ["Nombre", "Estado"]
ETIQUETAS_ROL = {
    "USUARIO_NORMAL": "Usuario normal",
    "SUPERVISOR": "Supervisor",
    "ADMINISTRADOR": "Administrador",
}
LARGO_MINIMO = 6  # el mismo que pide scripts/crear_usuario.py


class FormularioUsuario(QDialog):
    """Alta y edición. La contraseña se pide al crear; al editar, dejarla en
    blanco la conserva."""

    def __init__(self, parent=None, usuario_id: int | None = None):
        super().__init__(parent)
        self.usuario_id = usuario_id
        self.setWindowTitle("Nuevo usuario" if usuario_id is None else "Editar usuario")
        self.setMinimumWidth(400)

        self.nombre = QLineEdit(placeholderText="Nombre y apellido")
        self.username = QLineEdit(placeholderText="Con el que inicia sesión")
        self.rol = QComboBox()
        for rol, etiqueta in ETIQUETAS_ROL.items():
            self.rol.addItem(etiqueta, rol)
        self.activo = QCheckBox("Puede iniciar sesión")
        self.activo.setChecked(True)
        pista = "" if usuario_id is None else "Dejar en blanco para no cambiarla"
        self.password = QLineEdit(placeholderText=pista)
        self.password.setEchoMode(QLineEdit.Password)
        self.confirmacion = QLineEdit(placeholderText=pista)
        self.confirmacion.setEchoMode(QLineEdit.Password)

        form = QFormLayout()
        form.setSpacing(ESPACIO_FORMULARIO)
        form.addRow("Nombre *", self.nombre)
        form.addRow("Usuario *", self.username)
        form.addRow("Rol", self.rol)
        form.addRow("Contraseña" + (" *" if usuario_id is None else ""), self.password)
        form.addRow("Repetir contraseña", self.confirmacion)
        form.addRow("", self.activo)

        layout = layout_de_dialogo(self)
        layout.addLayout(form)
        layout.addWidget(botonera(self))

        if usuario_id is not None:
            self._cargar()

    def _cargar(self) -> None:
        with SessionLocal() as db:
            u = db.get(Usuario, self.usuario_id)
            self.nombre.setText(u.nombre)
            self.username.setText(u.username)
            self.rol.setCurrentIndex(self.rol.findData(u.rol))
            self.activo.setChecked(u.activo)

    def accept(self) -> None:
        nombre, username = self.nombre.text().strip(), self.username.text().strip()
        password = self.password.text()
        if not nombre or not username:
            QMessageBox.warning(self, "Faltan datos", "El usuario necesita nombre y nombre de usuario.")
            return
        if self.usuario_id is None and not password:
            QMessageBox.warning(self, "Falta la contraseña", "Un usuario nuevo necesita contraseña.")
            return
        if password and len(password) < LARGO_MINIMO:
            QMessageBox.warning(
                self, "Contraseña corta", f"La contraseña debe tener al menos {LARGO_MINIMO} caracteres."
            )
            return
        if password != self.confirmacion.text():
            QMessageBox.warning(self, "Las contraseñas no coinciden", "Escríbela igual en los dos campos.")
            return
        # Desactivarse a uno mismo deja el sistema sin nadie que pueda entrar a
        # deshacerlo. Se ataja acá y no en la base porque es un error de uso.
        if self.usuario_id == Sesion.usuario_id and not self.activo.isChecked():
            QMessageBox.warning(self, "No puedes desactivarte", "Pídeselo a otro administrador.")
            return
        if self.guardar(nombre, username, password):
            super().accept()

    def guardar(self, nombre: str, username: str, password: str) -> bool:
        with SessionLocal() as db:
            usuario = db.get(Usuario, self.usuario_id) if self.usuario_id else Usuario()
            usuario.nombre = nombre
            usuario.username = username
            usuario.rol = self.rol.currentData()
            usuario.activo = self.activo.isChecked()
            if password:
                usuario.password_hash = hash_password(password)
            if self.usuario_id is None:
                db.add(usuario)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                QMessageBox.warning(self, "Usuario repetido", f"Ya existe un usuario '{username}'.")
                return False
            self.usuario_id = usuario.id
        return True


class FormularioMecanico(QDialog):
    """Alta y edición de un mecánico: el nombre que sale en la orden y su PDF.
    Se desactiva en vez de borrarse, porque tiene órdenes."""

    def __init__(self, parent=None, mecanico_id: int | None = None):
        super().__init__(parent)
        self.mecanico_id = mecanico_id
        self.setWindowTitle("Nuevo mecánico" if mecanico_id is None else "Editar mecánico")
        self.setMinimumWidth(360)

        self.nombre = QLineEdit(placeholderText="Como sale en la orden")
        self.activo = QCheckBox("Aparece al abrir una orden")
        self.activo.setChecked(True)

        form = QFormLayout()
        form.setSpacing(ESPACIO_FORMULARIO)
        form.addRow("Nombre *", self.nombre)
        form.addRow("", self.activo)
        layout = layout_de_dialogo(self)
        layout.addLayout(form)
        layout.addWidget(botonera(self))

        if mecanico_id is not None:
            with SessionLocal() as db:
                mecanico = db.get(Mecanico, mecanico_id)
                self.nombre.setText(mecanico.nombre)
                self.activo.setChecked(mecanico.activo)

    def accept(self) -> None:
        nombre = " ".join(self.nombre.text().split())
        if not nombre:
            QMessageBox.warning(self, "Falta el nombre", "El mecánico necesita un nombre.")
            return
        with SessionLocal() as db:
            mecanico = db.get(Mecanico, self.mecanico_id) if self.mecanico_id else Mecanico()
            mecanico.nombre, mecanico.activo = nombre, self.activo.isChecked()
            db.add(mecanico)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                QMessageBox.warning(self, "Mecánico repetido", f"Ya existe un mecánico '{nombre}'.")
                return
            self.mecanico_id = mecanico.id
        super().accept()


class UsuariosWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        boton_nuevo = QPushButton("Nuevo usuario")
        boton_nuevo.setProperty("clase", "primario")
        boton_nuevo.clicked.connect(self.nuevo)
        self.boton_editar = QPushButton("Editar")
        self.boton_editar.setEnabled(False)
        self.boton_editar.clicked.connect(self.editar)

        self.tabla = con_aviso_vacio(
            crear_tabla(COLUMNAS, ancha=0, orden=0), "No hay usuarios registrados."
        )
        self.tabla.doubleClicked.connect(self.editar)
        self.tabla.itemSelectionChanged.connect(
            lambda: self.boton_editar.setEnabled(self.tabla.selectionModel().hasSelection())
        )

        boton_nuevo_mecanico = QPushButton("Nuevo mecánico")
        boton_nuevo_mecanico.clicked.connect(self.nuevo_mecanico)
        self.boton_editar_mecanico = QPushButton("Editar")
        self.boton_editar_mecanico.setEnabled(False)
        self.boton_editar_mecanico.clicked.connect(self.editar_mecanico)

        self.tabla_mecanicos = con_aviso_vacio(
            crear_tabla(COLUMNAS_MECANICOS, ancha=0, orden=0),
            "Sin mecánicos: no se puede guardar ninguna orden hasta agregar uno.",
        )
        self.tabla_mecanicos.doubleClicked.connect(self.editar_mecanico)
        self.tabla_mecanicos.itemSelectionChanged.connect(
            lambda: self.boton_editar_mecanico.setEnabled(
                self.tabla_mecanicos.selectionModel().hasSelection())
        )

        # El rótulo absorbe el ancho: si lo hiciera el botón, "Nuevo usuario"
        # ocuparía la pantalla entera.
        rotulo = QLabel("Quién entra al sistema y con qué rol. Las contraseñas se cambian editando.")
        rotulo.setProperty("clase", "resumen")
        rotulo.setWordWrap(True)
        usuarios = QWidget()
        columna = QVBoxLayout(usuarios)
        columna.setContentsMargins(0, 0, CANAL_PANEL, 0)
        columna.addLayout(barra(rotulo, boton_nuevo, self.boton_editar, estira=0))
        columna.addWidget(self.tabla)

        # Al lado y no en otra pestaña: son la otra mitad de "quién trabaja acá".
        rotulo_mecanicos = QLabel("Quién trabaja los autos. Sale como técnico en la orden.")
        rotulo_mecanicos.setProperty("clase", "resumen")
        rotulo_mecanicos.setWordWrap(True)
        mecanicos = QWidget()
        columna = QVBoxLayout(mecanicos)
        columna.setContentsMargins(CANAL_PANEL, 0, 0, 0)
        columna.addLayout(barra(rotulo_mecanicos, boton_nuevo_mecanico,
                                self.boton_editar_mecanico, estira=0))
        columna.addWidget(self.tabla_mecanicos)

        division = QSplitter(Qt.Horizontal)
        division.setHandleWidth(1)
        division.addWidget(usuarios)
        division.addWidget(mecanicos)
        division.setSizes([600, 400])

        layout = layout_de_pantalla(self)
        layout.addWidget(division)
        self.recargar()
        self.recargar_mecanicos()

    def recargar(self) -> None:
        with SessionLocal() as db:
            usuarios = db.scalars(select(Usuario).order_by(Usuario.nombre)).all()
            filas = [(u.id, u.nombre, u.username, u.rol, u.activo) for u in usuarios]

        self.tabla.setSortingEnabled(False)
        self.tabla.setRowCount(len(filas))
        for fila, (uid, nombre, username, rol, activo) in enumerate(filas):
            celda_nombre = QTableWidgetItem(nombre)
            celda_nombre.setData(Qt.UserRole, uid)
            estado = QTableWidgetItem("Activo" if activo else "Inactivo")
            estado.setData(ROL_INSIGNIA, BADGE_EXITO if activo else BADGE_NEUTRAL)
            self.tabla.setItem(fila, 0, celda_nombre)
            self.tabla.setItem(fila, 1, QTableWidgetItem(username))
            self.tabla.setItem(fila, 2, QTableWidgetItem(ETIQUETAS_ROL.get(rol, rol)))
            self.tabla.setItem(fila, 3, estado)
        reordenar(self.tabla)
        self.boton_editar.setEnabled(False)

    def _id_seleccionado(self) -> int | None:
        fila = self.tabla.currentRow()
        return None if fila < 0 else self.tabla.item(fila, 0).data(Qt.UserRole)

    def nuevo(self) -> None:
        if not exigir_permiso("usuarios", self):
            return
        if FormularioUsuario(self).exec():
            self.recargar()

    def editar(self) -> None:
        usuario_id = self._id_seleccionado()
        if usuario_id is None or not exigir_permiso("usuarios", self):
            return
        if FormularioUsuario(self, usuario_id).exec():
            self.recargar()

    def recargar_mecanicos(self) -> None:
        with SessionLocal() as db:
            filas = db.execute(
                select(Mecanico.id, Mecanico.nombre, Mecanico.activo).order_by(Mecanico.nombre)
            ).all()

        self.tabla_mecanicos.setSortingEnabled(False)
        self.tabla_mecanicos.setRowCount(len(filas))
        for fila, (mid, nombre, activo) in enumerate(filas):
            celda_nombre = QTableWidgetItem(nombre)
            celda_nombre.setData(Qt.UserRole, mid)
            estado = QTableWidgetItem("Activo" if activo else "Inactivo")
            estado.setData(ROL_INSIGNIA, BADGE_EXITO if activo else BADGE_NEUTRAL)
            self.tabla_mecanicos.setItem(fila, 0, celda_nombre)
            self.tabla_mecanicos.setItem(fila, 1, estado)
        reordenar(self.tabla_mecanicos)
        self.boton_editar_mecanico.setEnabled(False)

    def nuevo_mecanico(self) -> None:
        if not exigir_permiso("usuarios", self):
            return
        if FormularioMecanico(self).exec():
            self.recargar_mecanicos()

    def editar_mecanico(self) -> None:
        fila = self.tabla_mecanicos.currentRow()
        if fila < 0 or not exigir_permiso("usuarios", self):
            return
        if FormularioMecanico(self, self.tabla_mecanicos.item(fila, 0).data(Qt.UserRole)).exec():
            self.recargar_mecanicos()

"""Mantenedor de usuarios: quién entra al sistema y con qué rol.

Solo lo ve un ADMINISTRADOR (ver permisos.py). El primer administrador de una
instalación nueva se crea con scripts/crear_usuario.py; de ahí en adelante,
todo pasa por acá.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QLineEdit, QMessageBox,
    QPushButton, QTableWidgetItem, QWidget,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..auth import Sesion, hash_password
from ..database import SessionLocal
from ..models import Usuario
from .comunes import (
    BADGE_EXITO, BADGE_NEUTRAL, ROL_INSIGNIA, barra, botonera, con_aviso_vacio,
    crear_tabla, exigir_permiso, layout_de_dialogo, layout_de_pantalla, reordenar,
)
from .tema import ESPACIO_FORMULARIO

COLUMNAS = ["Nombre", "Usuario", "Rol", "Estado"]
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

        layout = layout_de_pantalla(self)
        layout.addLayout(barra(boton_nuevo, self.boton_editar, estira=0))
        layout.addWidget(self.tabla)
        self.recargar()

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

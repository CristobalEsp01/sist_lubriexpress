"""Pantalla de inicio de sesión. Se muestra una vez, antes de abrir la
ventana principal (ver main.py)."""
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)
from sqlalchemy import select

from ..auth import Sesion, verificar_password
from ..database import SessionLocal
from ..models import Usuario


class LoginDialog(QDialog):
    """Pide usuario y contraseña; si son correctos, deja la sesión activa en
    `Sesion` y se cierra con Accepted. Si se cancela, queda Rejected y quien
    llama (main.py) debe terminar la aplicación sin abrir la ventana principal.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Lubri-Express — Iniciar sesión")
        self.setMinimumWidth(360)
        self.setModal(True)

        titulo = QLabel("Sistema de Gestión de Taller")
        titulo.setProperty("clase", "seccion")

        self.username = QLineEdit(placeholderText="Usuario")
        self.password = QLineEdit(placeholderText="Contraseña")
        self.password.setEchoMode(QLineEdit.Password)
        self.username.returnPressed.connect(self.password.setFocus)
        self.password.returnPressed.connect(self._intentar)

        form = QFormLayout()
        form.setSpacing(12)
        form.addRow("Usuario", self.username)
        form.addRow("Contraseña", self.password)

        boton_entrar = QPushButton("Ingresar")
        boton_entrar.setProperty("clase", "primario")
        boton_entrar.clicked.connect(self._intentar)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)
        layout.addWidget(titulo)
        layout.addLayout(form)
        layout.addWidget(boton_entrar)

        self.username.setFocus()

    def _intentar(self) -> None:
        username = self.username.text().strip()
        password = self.password.text()
        if not username or not password:
            QMessageBox.warning(self, "Datos incompletos", "Ingresa usuario y contraseña.")
            return

        with SessionLocal() as db:
            usuario = db.scalar(select(Usuario).where(Usuario.username == username))

        if usuario is None or not verificar_password(password, usuario.password_hash):
            QMessageBox.warning(self, "No se pudo ingresar", "Usuario o contraseña incorrectos.")
            self.password.clear()
            self.password.setFocus()
            return

        if not usuario.activo:
            QMessageBox.warning(
                self, "Usuario deshabilitado",
                "Esta cuenta está desactivada. Habla con un administrador.",
            )
            return

        Sesion.iniciar(usuario)
        self.accept()

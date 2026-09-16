"""Pantalla de inicio de sesión. Se muestra una vez, antes de abrir la
ventana principal (ver main.py)."""
from PySide6.QtWidgets import QDialog, QFormLayout, QLabel, QLineEdit, QPushButton
from sqlalchemy import select

from ..auth import Sesion, verificar_password
from ..database import SessionLocal
from ..models import Usuario
from .comunes import layout_de_dialogo
from .tema import ESPACIO_FORMULARIO


class LoginDialog(QDialog):
    """Pide usuario y contraseña; si son correctos, deja la sesión activa en
    `Sesion` y se cierra con Accepted. Si se cancela, queda Rejected y quien
    llama (main.py) debe terminar la aplicación sin abrir la ventana principal.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Lubri-Express — Iniciar sesión")
        self.setMinimumWidth(400)
        self.setModal(True)

        titulo = QLabel("Lubri-Express")
        titulo.setProperty("clase", "titulo")
        subtitulo = QLabel("Sistema de Gestión de Taller — inicia sesión para abrir el turno")
        subtitulo.setProperty("clase", "resumen")

        self.username = QLineEdit(placeholderText="Usuario")
        self.password = QLineEdit(placeholderText="Contraseña")
        self.password.setEchoMode(QLineEdit.Password)
        self.username.returnPressed.connect(self.password.setFocus)
        self.password.returnPressed.connect(self._intentar)

        form = QFormLayout()
        form.setSpacing(ESPACIO_FORMULARIO)
        form.addRow("Usuario", self.username)
        form.addRow("Contraseña", self.password)

        # El error va bajo los campos, no en un modal que hay que cerrar para
        # volver a intentar.
        self.aviso = QLabel()
        self.aviso.setProperty("clase", "error")
        self.aviso.setWordWrap(True)

        boton_entrar = QPushButton("Ingresar")
        boton_entrar.setProperty("clase", "primario")
        boton_entrar.clicked.connect(self._intentar)

        layout = layout_de_dialogo(self)
        layout.addWidget(titulo)
        layout.addWidget(subtitulo)
        layout.addSpacing(ESPACIO_FORMULARIO)
        layout.addLayout(form)
        layout.addWidget(self.aviso)
        layout.addWidget(boton_entrar)

        self.username.setFocus()

    def _intentar(self) -> None:
        username = self.username.text().strip()
        password = self.password.text()
        if not username or not password:
            self.aviso.setText("Ingresa usuario y contraseña.")
            return

        with SessionLocal() as db:
            usuario = db.scalar(select(Usuario).where(Usuario.username == username))

        if usuario is None or not verificar_password(password, usuario.password_hash):
            self.aviso.setText("Usuario o contraseña incorrectos.")
            self.password.clear()
            self.password.setFocus()
            return

        if not usuario.activo:
            self.aviso.setText("Esta cuenta está desactivada. Habla con un administrador.")
            return

        Sesion.iniciar(usuario)
        self.accept()

"""Interfaz de escritorio (PySide6).

Cada mantenedor vive en su módulo; acá solo se arma la ventana con pestañas.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QMessageBox, QPushButton, QTabWidget

from ..auth import Sesion
from ..permisos import puede
from ..version import VERSION
from .caja import CajaWidget
from .clientes import ClientesWidget, FormularioCliente, FormularioVehiculo
from .comunes import ItemNumerico, clp
from .finanzas import FinanzasWidget
from .inventario import FormularioProducto, InventarioWidget
from .login import LoginDialog
from .ordenes import OrdenesWidget
from .reportes import ReportesWidget
from .usuarios import ETIQUETAS_ROL, FormularioUsuario, UsuariosWidget
from .ventas import VentasWidget

__all__ = [
    "CajaWidget", "ClientesWidget", "FinanzasWidget", "FormularioCliente", "FormularioProducto", "FormularioUsuario",
    "FormularioVehiculo", "InventarioWidget", "ItemNumerico", "LoginDialog", "OrdenesWidget",
    "ReportesWidget", "UsuariosWidget", "VentanaPrincipal", "VentasWidget", "clp",
]


class VentanaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        # main.py lo mira al cerrarse la ventana: si fue por "Cerrar sesión" vuelve
        # al login; si fue por la X, la aplicación termina.
        self.sesion_cerrada = False
        self.setWindowTitle(f"Lubri-Express v{VERSION} — Gestión de Taller")
        self.resize(1050, 640)
        # 640 de alto es lo que necesita la pantalla más densa —la orden de
        # trabajo, con sus cinco bloques y el total— para no cortar la cifra.
        self.setMinimumSize(960, 640)

        self.inventario = InventarioWidget(self)
        self.ventas = VentasWidget(self)
        self.clientes = ClientesWidget(self)
        self.ordenes = OrdenesWidget(self)

        self.pestanias = QTabWidget()
        self.pestanias.addTab(self.inventario, "Inventario")
        self.pestanias.addTab(self.ventas, "Ventas")
        self.pestanias.addTab(self.clientes, "Clientes")
        self.pestanias.addTab(self.ordenes, "Órdenes de Trabajo")
        self.caja = CajaWidget(self)
        self.pestanias.addTab(self.caja, "Caja")
        self.reportes = ReportesWidget(self)
        self.pestanias.addTab(self.reportes, "Reportes")
        # Finanzas y Usuarios existen solo para quien puede usarlas.
        if puede("finanzas"):
            self.finanzas = FinanzasWidget(self)
            self.pestanias.addTab(self.finanzas, "Finanzas")
        # La pestaña de usuarios existe solo para quien puede usarla: una
        # pestaña apagada invita a preguntar por qué.
        if puede("usuarios"):
            self.usuarios = UsuariosWidget(self)
            self.pestanias.addTab(self.usuarios, "Usuarios")
        # Arriba a la derecha, donde se busca: a la altura de las pestañas.
        self.boton_cerrar_sesion = QPushButton("Cerrar sesión")
        self.boton_cerrar_sesion.setToolTip("Termina el turno y vuelve a la pantalla de inicio de sesión")
        self.boton_cerrar_sesion.clicked.connect(self.cerrar_sesion)
        self.pestanias.setCornerWidget(self.boton_cerrar_sesion, Qt.TopRightCorner)
        self.setCentralWidget(self.pestanias)

        if Sesion.activa():
            self.statusBar().showMessage(
                f"Conectado como {Sesion.nombre} · {ETIQUETAS_ROL.get(Sesion.rol, Sesion.rol)}"
                f" · v{VERSION}"
            )

    def iniciar_venta_con_producto(self, producto_id: int) -> None:
        """Acceso directo desde Inventario: botón 'Generar Venta' (Propuesta 3.3)."""
        self.pestanias.setCurrentWidget(self.ventas)
        self.ventas.agregar_producto(producto_id)

    def cerrar_sesion(self) -> bool:
        """Pide confirmación, cierra la sesión y la ventana; main.py vuelve al
        login. Devuelve si se cerró. Lo que estaba a medio hacer (una venta u
        orden sin guardar) se pierde, y el aviso lo dice."""
        respuesta = QMessageBox.question(
            self, "Cerrar sesión",
            f"¿Cerrar la sesión de {Sesion.nombre or 'este usuario'}?\n\n"
            "Lo que tengas sin guardar (una venta u orden en curso) se perderá.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if respuesta != QMessageBox.Yes:
            return False
        Sesion.cerrar()
        self.sesion_cerrada = True
        self.close()
        return True

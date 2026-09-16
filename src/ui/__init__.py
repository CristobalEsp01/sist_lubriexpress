"""Interfaz de escritorio (PySide6).

Cada mantenedor vive en su módulo; acá solo se arma la ventana con pestañas.
"""
from PySide6.QtWidgets import QMainWindow, QTabWidget

from ..auth import Sesion
from ..permisos import puede
from .clientes import ClientesWidget, FormularioCliente, FormularioVehiculo
from .comunes import ItemNumerico, clp
from .inventario import FormularioProducto, InventarioWidget
from .login import LoginDialog
from .ordenes import OrdenesWidget
from .reportes import ReportesWidget
from .usuarios import ETIQUETAS_ROL, FormularioUsuario, UsuariosWidget
from .ventas import VentasWidget

__all__ = [
    "ClientesWidget", "FormularioCliente", "FormularioProducto", "FormularioUsuario",
    "FormularioVehiculo", "InventarioWidget", "ItemNumerico", "LoginDialog", "OrdenesWidget",
    "ReportesWidget", "UsuariosWidget", "VentanaPrincipal", "VentasWidget", "clp",
]


class VentanaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lubri-Express — Gestión de Taller")
        self.resize(1050, 640)
        self.setMinimumSize(960, 580)

        self.inventario = InventarioWidget(self)
        self.ventas = VentasWidget(self)
        self.clientes = ClientesWidget(self)
        self.ordenes = OrdenesWidget(self)

        self.pestanias = QTabWidget()
        self.pestanias.addTab(self.inventario, "Inventario")
        self.pestanias.addTab(self.ventas, "Ventas")
        self.pestanias.addTab(self.clientes, "Clientes")
        self.pestanias.addTab(self.ordenes, "Órdenes de Trabajo")
        self.reportes = ReportesWidget(self)
        self.pestanias.addTab(self.reportes, "Reportes")
        # La pestaña de usuarios existe solo para quien puede usarla: una
        # pestaña apagada invita a preguntar por qué.
        if puede("usuarios"):
            self.usuarios = UsuariosWidget(self)
            self.pestanias.addTab(self.usuarios, "Usuarios")
        self.setCentralWidget(self.pestanias)

        if Sesion.activa():
            self.statusBar().showMessage(
                f"Conectado como {Sesion.nombre} · {ETIQUETAS_ROL.get(Sesion.rol, Sesion.rol)}"
            )

    def iniciar_venta_con_producto(self, producto_id: int) -> None:
        """Acceso directo desde Inventario: botón 'Generar Venta' (Propuesta 3.3)."""
        self.pestanias.setCurrentWidget(self.ventas)
        self.ventas.agregar_producto(producto_id)

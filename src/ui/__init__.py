"""Interfaz de escritorio (PySide6).

Cada mantenedor vive en su módulo; acá solo se arma la ventana con pestañas.
"""
from PySide6.QtWidgets import QMainWindow, QTabWidget

from .clientes import ClientesWidget, FormularioCliente, FormularioVehiculo
from .comunes import ItemNumerico, clp
from .inventario import FormularioProducto, InventarioWidget

__all__ = [
    "ClientesWidget", "FormularioCliente", "FormularioProducto", "FormularioVehiculo",
    "InventarioWidget", "ItemNumerico", "VentanaPrincipal", "clp",
]


class VentanaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lubri-Express — Gestión de Taller")
        self.resize(1050, 640)

        self.pestanias = QTabWidget()
        self.pestanias.addTab(InventarioWidget(self), "Inventario")
        self.pestanias.addTab(ClientesWidget(self), "Clientes")
        self.setCentralWidget(self.pestanias)

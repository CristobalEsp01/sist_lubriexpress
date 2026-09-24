"""Qué puede hacer cada rol.

Una acción por entrada. La pantalla apaga el botón según esto y el slot vuelve
a preguntar (`exigir_permiso()` en comunes.py): así el doble click, el atajo
y las pruebas que llaman al slot directo pasan por el mismo filtro.

Vender, abrir órdenes y mantener clientes y vehículos no se restringe: es el
trabajo del mesón y lo hace cualquier rol. Anular y aplicar descuentos se
suman acá cuando existan en pantalla.
"""
from .auth import Sesion

PERMISOS = {
    # Crear y editar productos, ingresar mercadería, ajustar stock. Los
    # formularios de bodega piden el costo de la compra, así que ahí se ve.
    "inventario": {"SUPERVISOR", "ADMINISTRADOR"},
    # El costo en los listados y el inventario valorizado: lo que vale la bodega.
    "costos": {"ADMINISTRADOR"},
    # Los reportes de plata (ventas por producto, por usuario, por mecánico,
    # descuentos). El de reabastecimiento lo ve cualquiera: es la lista de compras.
    "reportes": {"ADMINISTRADOR"},
    # Ingresos por período. Aparte de "reportes" para poder cerrarlo de nuevo
    # sin tocar la pantalla: hoy lo ven todos.
    "ingresos": {"USUARIO_NORMAL", "SUPERVISOR", "ADMINISTRADOR"},
    # Dar de alta usuarios y mecánicos, y asignar roles.
    "usuarios": {"ADMINISTRADOR"},
}


def puede(accion: str) -> bool:
    return Sesion.rol in PERMISOS[accion]

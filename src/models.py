"""Modelos ORM. Calzan uno a uno con database/schema_lubriexpress.sql; hay una
prueba que lo verifica.

Dos cosas que el esquema hace y estas clases no muestran:

- `created_at` y `updated_at` no se mapean: los mantienen los triggers.
- Los triggers de stock modifican "productos" por fuera de la sesión, así que
  después de confirmar una venta, una orden o un movimiento de kardex hay que
  hacer `db.refresh(producto)` para no leer un `stock_actual` viejo de la caché.
"""
from sqlalchemy import (
    Column, Integer, String, Boolean, Numeric, DateTime, Text, ForeignKey, func
)
from sqlalchemy.orm import relationship

from .database import Base


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    rol = Column(String(20), nullable=False)
    activo = Column(Boolean, default=True, nullable=False)


class Cliente(Base):
    __tablename__ = "clientes"

    id = Column(Integer, primary_key=True, index=True)
    rut = Column(String(12), unique=True)  # opcional: solo las empresas lo exigen
    nombre_completo = Column(String(150), nullable=False)
    tipo_cliente = Column(String(20), default="PERSONA", nullable=False)
    telefono = Column(String(15))

    # Relación bidireccional (permite acceder a los vehículos del cliente como una lista)
    vehiculos = relationship("Vehiculo", back_populates="cliente")


class Vehiculo(Base):
    __tablename__ = "vehiculos"

    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False)
    patente = Column(String(10), unique=True, nullable=False)
    marca = Column(String(50))
    modelo = Column(String(50))
    anio_fabricacion = Column(Integer)
    color = Column(String(30))
    transmision = Column(String(20))
    cilindrada = Column(String(20))
    traccion = Column(String(20))
    combustible = Column(String(20))
    # Del sistema antiguo, tal cual vienen (ver el .sql).
    tipo = Column(String(30))
    version = Column(String(50))
    vin = Column(String(20))
    numero_motor = Column(String(30))

    # Relaciones
    cliente = relationship("Cliente", back_populates="vehiculos")
    ordenes = relationship("Orden", back_populates="vehiculo")


class Ubicacion(Base):
    __tablename__ = "ubicaciones"

    id = Column(Integer, primary_key=True, index=True)
    descripcion = Column(String(100), nullable=False)

    productos = relationship("Producto", back_populates="ubicacion")


class Producto(Base):
    __tablename__ = "productos"

    id = Column(Integer, primary_key=True, index=True)
    ubicacion_id = Column(Integer, ForeignKey("ubicaciones.id"))
    nombre = Column(String(100), nullable=False)
    marca = Column(String(50))
    categoria = Column(String(50))
    descripcion = Column(Text)
    precio_costo = Column(Numeric(10, 2), nullable=False)
    precio_venta = Column(Numeric(10, 2), nullable=False)  # neto, sin IVA
    stock_actual = Column(Integer, default=0, nullable=False)
    stock_minimo = Column(Integer, default=0, nullable=False)
    activo = Column(Boolean, default=True, nullable=False)

    ubicacion = relationship("Ubicacion", back_populates="productos")

    @property
    def stock_critico(self) -> bool:
        return self.stock_actual <= self.stock_minimo


class Servicio(Base):
    """Mano de obra que se cobra en una orden. No tiene stock ni Kardex."""

    __tablename__ = "servicios"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    categoria = Column(String(50))
    precio_venta = Column(Numeric(10, 2), nullable=False)  # neto, sin IVA
    activo = Column(Boolean, default=True, nullable=False)


class Orden(Base):
    __tablename__ = "ordenes"

    id = Column(Integer, primary_key=True, index=True)
    vehiculo_id = Column(Integer, ForeignKey("vehiculos.id"), nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    folio_mercado_publico = Column(String(50))
    fecha_creacion = Column(DateTime, server_default=func.now(), nullable=False)
    kilometraje_ingreso = Column(Integer)  # la pantalla lo exige; NULL solo en lo migrado
    # La BD prohíbe usar porcentaje y monto a la vez (CHECK descuento_exclusivo_orden).
    descuento_porcentaje = Column(Numeric(5, 2), default=0, nullable=False)
    descuento_monto = Column(Numeric(10, 2), default=0, nullable=False)
    # subtotal es neto; total_final = subtotal - descuento + impuesto + ajuste.
    subtotal = Column(Numeric(10, 2), default=0, nullable=False)
    impuesto = Column(Numeric(10, 2), default=0, nullable=False)
    ajuste_redondeo = Column(Numeric(10, 2), default=0, nullable=False)  # ley de redondeo
    total_final = Column(Numeric(10, 2), default=0, nullable=False)
    numero_boleta = Column(String(50), unique=True)
    estado = Column(String(20), nullable=False, server_default="ENTREGADA")
    estado_pago = Column(Boolean, default=False, nullable=False)
    notas = Column(Text)
    # Flyer o gremio (src/convenios.py); los pesos van en descuento_monto.
    convenio = Column(String(20))
    folio_flyer = Column(Integer)   # único entre las no anuladas

    vehiculo = relationship("Vehiculo", back_populates="ordenes")
    usuario = relationship("Usuario")
    detalles = relationship("DetalleOrden", back_populates="orden")
    pagos = relationship("PagoOrden", back_populates="orden")

    @property
    def descuento_aplicado(self) -> int:
        """El descuento en pesos, venga como monto o como porcentaje del neto."""
        if self.descuento_monto:
            return int(self.descuento_monto)
        return int(round(self.subtotal * self.descuento_porcentaje / 100))

    @property
    def monto_pagado(self) -> int:
        return int(sum(p.monto for p in self.pagos))

    @property
    def saldo(self) -> int:
        """Lo que falta por cobrar.

        Las 3.021 órdenes migradas vienen marcadas como pagadas y sin ningún
        abono detrás: para ellas la resta daría el total entero. `estado_pago`
        manda, y es el trigger quien lo pone al día cuando entra un abono.
        """
        return 0 if self.estado_pago else int(self.total_final) - self.monto_pagado


class DetalleOrden(Base):
    __tablename__ = "detalle_ordenes"

    id = Column(Integer, primary_key=True, index=True)
    orden_id = Column(Integer, ForeignKey("ordenes.id"), nullable=False)
    # Uno de los dos, nunca ambos (CHECK detalle_orden_un_item). Solo las
    # líneas de producto descuentan stock.
    producto_id = Column(Integer, ForeignKey("productos.id"))
    servicio_id = Column(Integer, ForeignKey("servicios.id"))
    cantidad = Column(Integer, nullable=False)
    precio_unitario_cobrado = Column(Numeric(10, 2), nullable=False)

    orden = relationship("Orden", back_populates="detalles")
    producto = relationship("Producto")
    servicio = relationship("Servicio")


class PagoOrden(Base):
    """Un abono de una orden. Append-only: los pagos se suman, no se corrigen."""

    __tablename__ = "pagos_orden"

    id = Column(Integer, primary_key=True, index=True)
    orden_id = Column(Integer, ForeignKey("ordenes.id"), nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    monto = Column(Numeric(10, 2), nullable=False)
    medio_pago = Column(String(20), default="EFECTIVO", nullable=False)
    fecha_pago = Column(DateTime, server_default=func.now(), nullable=False)

    orden = relationship("Orden", back_populates="pagos")
    usuario = relationship("Usuario")


class Venta(Base):
    __tablename__ = "ventas"

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    cliente_id = Column(Integer, ForeignKey("clientes.id"))
    fecha_venta = Column(DateTime, server_default=func.now(), nullable=False)
    numero_boleta = Column(String(50), unique=True)
    impuesto = Column(Numeric(10, 2), default=0, nullable=False)
    ajuste_redondeo = Column(Numeric(10, 2), default=0, nullable=False)  # ley de redondeo
    total_final = Column(Numeric(10, 2), nullable=False)  # neto + impuesto + ajuste
    medio_pago = Column(String(20), default="EFECTIVO", nullable=False)

    usuario = relationship("Usuario")
    cliente = relationship("Cliente")
    detalles = relationship("DetalleVenta", back_populates="venta")


class DetalleVenta(Base):
    __tablename__ = "detalle_ventas"

    id = Column(Integer, primary_key=True, index=True)
    venta_id = Column(Integer, ForeignKey("ventas.id"), nullable=False)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    cantidad = Column(Integer, nullable=False)
    precio_unitario_cobrado = Column(Numeric(10, 2), nullable=False)

    venta = relationship("Venta", back_populates="detalles")
    producto = relationship("Producto")


class KardexMovimiento(Base):
    """Historial append-only. Lo escriben los triggers, no la aplicación."""

    __tablename__ = "kardex_movimientos"

    id = Column(Integer, primary_key=True, index=True)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    tipo_movimiento = Column(String(20), nullable=False)
    cantidad_movida = Column(Integer, nullable=False)
    stock_resultante = Column(Integer, nullable=False)
    costo_unitario = Column(Numeric(10, 2))
    orden_id = Column(Integer, ForeignKey("ordenes.id"))
    venta_id = Column(Integer, ForeignKey("ventas.id"))
    fecha_movimiento = Column(DateTime, server_default=func.now(), nullable=False)

    producto = relationship("Producto")
    usuario = relationship("Usuario")
    orden = relationship("Orden")
    venta = relationship("Venta")


class MovimientoCaja(Base):
    """Caja chica del día: el efectivo del cajón que no pasa por una venta.

    Append-only. Lo que entra por una venta o un abono no se copia acá; se
    suma de "ventas" y "pagos_orden". Corregir una fila es anularla con su
    inversa, no borrarla.
    """

    __tablename__ = "movimientos_caja"

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    tipo = Column(String(10), nullable=False)
    monto = Column(Numeric(10, 2), nullable=False)
    motivo = Column(String(200), nullable=False)
    fecha = Column(DateTime, server_default=func.now(), nullable=False)
    anula_id = Column(Integer, ForeignKey("movimientos_caja.id"), unique=True)

    usuario = relationship("Usuario")
    anulado = relationship("MovimientoCaja", remote_side=[id])

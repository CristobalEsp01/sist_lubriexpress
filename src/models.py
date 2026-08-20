from sqlalchemy import (
    Column, Integer, String, Boolean, Numeric, DateTime, Text, ForeignKey, func
)
from sqlalchemy.orm import relationship
from .database import Base

# Nota general: created_at / updated_at no se mapean porque los triggers de la
# base de datos ya se encargan de mantenerlos.
# ponytail: los triggers de stock modifican "productos" por fuera de la sesión.
# Después de confirmar una venta u orden hay que hacer session.refresh(producto)
# (o session.expire_all()) para no leer un stock_actual obsoleto de la caché.


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
    rut = Column(String(12), unique=True, nullable=False)
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
    precio_venta = Column(Numeric(10, 2), nullable=False)
    stock_actual = Column(Integer, default=0, nullable=False)
    stock_minimo = Column(Integer, default=0, nullable=False)
    activo = Column(Boolean, default=True, nullable=False)

    ubicacion = relationship("Ubicacion", back_populates="productos")

    @property
    def stock_critico(self) -> bool:
        return self.stock_actual <= self.stock_minimo


class Orden(Base):
    __tablename__ = "ordenes"

    id = Column(Integer, primary_key=True, index=True)
    vehiculo_id = Column(Integer, ForeignKey("vehiculos.id"), nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    folio_mercado_publico = Column(String(50))
    fecha_creacion = Column(DateTime, server_default=func.now())
    kilometraje_ingreso = Column(Integer, nullable=False)
    # La BD prohíbe usar porcentaje y monto a la vez (CHECK descuento_exclusivo_orden).
    descuento_porcentaje = Column(Numeric(5, 2), default=0, nullable=False)
    descuento_monto = Column(Numeric(10, 2), default=0, nullable=False)
    subtotal = Column(Numeric(10, 2), default=0, nullable=False)
    total_final = Column(Numeric(10, 2), default=0, nullable=False)
    numero_boleta = Column(String(50), unique=True)
    estado_pago = Column(Boolean, default=False, nullable=False)
    notas = Column(Text)

    vehiculo = relationship("Vehiculo", back_populates="ordenes")
    usuario = relationship("Usuario")
    detalles = relationship("DetalleOrden", back_populates="orden")


class DetalleOrden(Base):
    __tablename__ = "detalle_ordenes"

    id = Column(Integer, primary_key=True, index=True)
    orden_id = Column(Integer, ForeignKey("ordenes.id"), nullable=False)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    cantidad = Column(Integer, nullable=False)
    precio_unitario_cobrado = Column(Numeric(10, 2), nullable=False)

    orden = relationship("Orden", back_populates="detalles")
    producto = relationship("Producto")


class Venta(Base):
    __tablename__ = "ventas"

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    cliente_id = Column(Integer, ForeignKey("clientes.id"))
    fecha_venta = Column(DateTime, server_default=func.now())
    numero_boleta = Column(String(50), unique=True)
    total_final = Column(Numeric(10, 2), nullable=False)

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
    orden_id = Column(Integer, ForeignKey("ordenes.id"))
    venta_id = Column(Integer, ForeignKey("ventas.id"))
    fecha_movimiento = Column(DateTime, server_default=func.now())

    producto = relationship("Producto")
    usuario = relationship("Usuario")
    orden = relationship("Orden")
    venta = relationship("Venta")

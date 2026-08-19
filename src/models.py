from sqlalchemy import Column, Integer, String, Boolean, Numeric, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
import datetime

class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    rol = Column(String(20), nullable=False)
    activo = Column(Boolean, default=True, nullable=False)
    
    # Nota: No necesitamos definir created_at ni updated_at aquí 
    # porque los triggers de tu base de datos ya se encargan de eso de forma automática.

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
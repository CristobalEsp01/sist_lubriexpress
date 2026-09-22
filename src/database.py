"""Conexión a PostgreSQL: el motor, la fábrica de sesiones y la Base del ORM.

La URL vive en el .env y no tiene valor por defecto a propósito: más vale que la
aplicación no arranque a que se conecte en silencio a una base que no es la que
se creía. Una sesión por operación, con `with SessionLocal() as db:`.
"""
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .rutas import carpeta_app

# Empaquetada con PyInstaller, la aplicación busca el .env junto al ejecutable:
# find_dotenv() partiría desde la carpeta temporal del bundle y no lo hallaría.
load_dotenv(carpeta_app() / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("No se encontró DATABASE_URL en las variables de entorno.")

# La hora de cada venta, abono y movimiento la pone el servidor con
# CURRENT_TIMESTAMP, así que hay que decirle en qué huso está el taller. Con el
# servidor en UTC —el contenedor lo está— una venta de las nueve de la noche
# queda fechada al día siguiente: se cae del cierre de caja y del reporte de
# hoy, y el cajón no cuadra sin que nada en pantalla lo explique. Fijarlo en la
# conexión y no en el servidor hace que valga igual en el PC del taller, sin
# depender de cómo quedó instalado PostgreSQL ahí.
ZONA_HORARIA = "America/Santiago"
engine = create_engine(DATABASE_URL, echo=False,
                       connect_args={"options": f"-c timezone={ZONA_HORARIA}"})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

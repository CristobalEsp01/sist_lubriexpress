"""Conexión a PostgreSQL: el motor, la fábrica de sesiones y la Base del ORM.

La URL vive en el .env y no tiene valor por defecto a propósito: más vale que la
aplicación no arranque a que se conecte en silencio a una base que no es la que
se creía. Una sesión por operación, con `with SessionLocal() as db:`.
"""
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("No se encontró DATABASE_URL en las variables de entorno.")

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

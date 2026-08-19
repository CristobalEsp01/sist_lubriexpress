import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# 1. Cargar las variables del archivo .env
load_dotenv()

# 2. Leer la variable de entorno
DATABASE_URL = os.getenv("DATABASE_URL")

# 3. Pequeña validación de seguridad por si a alguien se le olvida crear el .env
if not DATABASE_URL:
    raise ValueError("¡Error! No se encontró DATABASE_URL en las variables de entorno.")

# Creamos el motor
engine = create_engine(DATABASE_URL, echo=False)

# Creamos la fábrica de sesiones
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base para los modelos
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
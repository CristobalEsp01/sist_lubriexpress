import pandas as pd
from sqlalchemy import select
import sys
import os
import re

# Ajustar el path para poder importar los modelos
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import SessionLocal
from src.models import Cliente, Vehiculo, Orden, Usuario

def limpiar_patente(patente: str) -> str | None:
    if pd.isna(patente): 
        return None
        
    # 1. Limpiar caracteres especiales y pasar a mayúsculas
    patente_limpia = str(patente).replace("-", "").replace(".", "").replace(" ", "").upper()
    
    # 2. Validar que cumpla con el formato chileno estricto
    # Coincide con: AA1111, BBBB11, AA111, o AAA11
    patron_chileno = re.compile(r'^([A-Z]{2}\d{4}|[A-Z]{4}\d{2}|[A-Z]{2}\d{3}|[A-Z]{3}\d{2})$')
    
    if not patron_chileno.match(patente_limpia):
        return None  # Si es argentina, brasileña o tiene basura, devolvemos None
        
    return patente_limpia

def importar_excel(ruta_archivo: str, usuario_admin_id: int = 1) -> None:
    print(f"Analizando archivo: {ruta_archivo}...")
    
    # 1. Lectura del archivo y hoja
    df = pd.read_excel(ruta_archivo, sheet_name='Ordenes de trabajo')
    
    # 2. Limpieza de nombres concatenando nombre y apellido
    df['Nombre'] = df['Nombre'].fillna('').astype(str).str.strip()
    df['Apellidos'] = df['Apellidos'].fillna('').astype(str).str.strip()
    df['nombre_completo'] = (df['Nombre'] + ' ' + df['Apellidos']).str.strip()
    
    # 3. Aislamiento del último registro
    # Ordenamos por fecha de forma ascendente
    df = df.sort_values('date_created', ascending=True)
    # Descartamos filas sin patente (las que vengan nulas del Excel)
    df = df.dropna(subset=['Vehiculos_presup_SEGUNPATENTE::patente'])
    # Nos quedamos solo con la última fila de cada patente (la visita más reciente)
    df_unicos = df.drop_duplicates(subset=['Vehiculos_presup_SEGUNPATENTE::patente'], keep='last')
    
    # Convertir todos los NaN a None para que el ORM de SQLAlchemy los acepte
    df_unicos = df_unicos.where(pd.notnull(df_unicos), None)

    print(f"Datos limpios. Procediendo a insertar {len(df_unicos)} vehículos únicos.\n")

    with SessionLocal() as db:
        # --- NUEVO: Buscar el ID real del usuario admin ---
        usuario = db.execute(select(Usuario).where(Usuario.username == 'admin')).scalar_one_or_none()
        if not usuario:
            print("Error fatal: No se encontró el usuario 'admin' en la base de datos.")
            return
        
        usuario_admin_id = usuario.id
        print(f"Usuario 'admin' detectado con el ID: {usuario_admin_id}")
        # -------------------------------------------------
        contador_clientes = 0
        contador_vehiculos = 0
        
        for index, row in df_unicos.iterrows():
            try:
                # Mapeo exacto de las columnas de tu archivo Excel
                nombre_cliente = row['nombre_completo']
                patente = limpiar_patente(row['Vehiculos_presup_SEGUNPATENTE::patente'])
                marca = row['Vehiculos_presup_SEGUNPATENTE::marca']
                modelo = row['Vehiculos_presup_SEGUNPATENTE::modelo']
                
                # El año de fabricación suele venir como float en Excel (ej. 2017.0)
                anio_bruto = row['Vehiculos_presup_SEGUNPATENTE::año']
                anio = int(anio_bruto) if pd.notnull(anio_bruto) and str(anio_bruto).replace('.0','').isnumeric() else None
                
                kms = row['kms']
                fecha = row['date_created']
                falla = row['Falla']
                id_antiguo = str(row['id_gato']).replace('#', '').strip()
                
                if not nombre_cliente or not patente:
                    continue

                # --- A. Buscar o Crear Cliente ---
                cliente = db.execute(select(Cliente).where(Cliente.nombre_completo == nombre_cliente)).scalar_one_or_none()
                
                if not cliente:
                    cliente = Cliente(
                        rut=None, # Como el excel no trae RUT, se asume None 
                        nombre_completo=nombre_cliente,
                        tipo_cliente='PERSONA'
                    )
                    db.add(cliente)
                    db.flush()
                    contador_clientes += 1

                # --- B. Buscar o Crear Vehículo ---
                vehiculo = db.execute(select(Vehiculo).where(Vehiculo.patente == patente)).scalar_one_or_none()
                
                if not vehiculo:
                    vehiculo = Vehiculo(
                        cliente_id=cliente.id,
                        patente=patente,
                        marca=marca,
                        modelo=modelo,
                        anio_fabricacion=anio
                    )
                    db.add(vehiculo)
                    db.flush()
                    contador_vehiculos += 1

                # --- C. Anclar Kilometraje con una Orden "Fantasma" ---
                if kms is not None and pd.notnull(kms):
                    # Incluir el ID del sistema antiguo en las observaciones para respaldar trazabilidad
                    notas_migracion = f"Migración de sistema antiguo (N° Ref: {id_antiguo})."
                    if falla:
                        notas_migracion += f"\nMotivo original: {falla}"
                        
                    orden_historica = Orden(
                        vehiculo_id=vehiculo.id,
                        usuario_id=usuario_admin_id,
                        kilometraje_ingreso=int(kms),
                        fecha_creacion=fecha,
                        subtotal=0,
                        total_final=0,
                        notas=notas_migracion
                    )
                    db.add(orden_historica)

                # Comprometer a la base de datos vehículo por vehículo para aislar errores
                db.commit()

            except Exception as e:
                db.rollback()
                print(f"Error procesando la patente {row.get('Vehiculos_presup_SEGUNPATENTE::patente')}: {str(e)}")

        print(f"\n--- Migración Finalizada ---")
        print(f"Nuevos Clientes creados: {contador_clientes}")
        print(f"Nuevos Vehículos registrados: {contador_vehiculos}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Error: Debes proporcionar la ruta del archivo Excel.")
        print("Uso: python scripts/importar_datos.py <ruta_al_archivo>")
        sys.exit(1)
        
    ruta_excel = sys.argv[1]
    importar_excel(ruta_excel)
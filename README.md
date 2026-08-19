
# Sistema de Gestión - Lubri-Express

Sistema de escritorio local para la gestión integral de órdenes de trabajo, inventario (Kardex) y ventas de mostrador del taller mecánico Lubri-Express.

## Requisitos Previos

* Python 3.8 o superior
* Git
* Postgresql (Instalado y corriendo localmente)

## Configuración del Entorno de Desarrollo

Sigue estos pasos para inicializar y levantar el entorno de trabajo en tu máquina local:

### 1. Clonar el repositorio
```bash
git clone <https://github.com/CristobalEsp01/sist_lubriexpress.git>
cd sist_lubriexpress
```

### 2. Crear el entorno virtual
Es indispensable utilizar un entorno virtual aislado para no generar conflictos con las librerías globales del sistema.

```bash
python3 -m venv venv
````

### 3. Activar el entorno virtual
Dependiendo de tu sistema operativo, ejecuta el comando correspondiente:

En Ubuntu/Linux o macOS:

```bash
source venv/bin/activate
```
En Windows (Command Prompt):

```DOS
venv\Scripts\activate.bat
```

En Windows (PowerShell):

```PowerShell
venv\Scripts\Activate.ps1
````
(Sabrás que el entorno está activo porque aparecerá (venv) al inicio de la línea en tu terminal).

### 4. Instalar dependencias
Con el entorno virtual activado, instala los paquetes necesarios para el proyecto:

```bash
pip install -r requirements.txt
```

### 5. Configuracion de la Base de Datos (Postgresql)
El sistema utiliza PostgreSQL para asegurar la integridad transaccional del Kardex. Para levantar la base de datos:
1. Abre tu gestos de base de datos nativo (pgAdmin4 o DBeaver)
2. Crea una nueva base de datos llamada exactamente "lubriexpress"
3. Abre una hoja de consulta (SQL Editor o Query Tool) apuntando especificamente a esa nueva base de datos.
4. Abre el archivo ```database/schema_lubriexpress.sql```, copia todo su contenido y ejecutalo. Esto generara la estructura completa de tablas, restricciones (contraints) y los triggers automaticos de inventario.

### 6. Variables de entorno (.env)
Las credenciales de conexion no estan escritas en el codigo por seguridad.

1. En la raiz del proyecto, ubicar el archivo de plantilla ```.env.example```
2. Duplicar el archivo y renombrar la copia exactamente como ```.env``` (este archivo esta incluido en el ```.gitignore```)
3. Abrir el archivo ```.env``` y reemplazar la contrasenia de prueba por la clave real de tu instalacion local de PSQL.
```bash
DATABASE_URL=postgresql+psycopg2://postgres:TU_CONTRASEÑA@localhost:5432/lubriexpress
```

### Estructura del Proyecto
```text
sist_lubriexpress/
├── src/
│   ├── database.py              # Motor de conexión y fábrica de sesiones
│   ├── models.py                # Modelos ORM (SQLAlchemy) mapeados a la BD
├── database/
│   └── schema_lubriexpress.sql  # Script oficial de creación de tablas y triggers
├── docs/
│   ├── requirements/            # Levantamiento de requerimientos
│   └── manuals/                 # Manuales y documentación técnica[cite: 2]
├── .env.example                 # Plantilla de variables de entorno (Sí se sube a Git)
├── .env                         # Credenciales locales (NO se sube a Git)
├── main.py                       # Código principal de la aplicación
├── README.md                    # Documentación del proyecto[cite: 2]
├── requirements.txt             # Dependencias del proyecto[cite: 2]
├── .gitignore                   # Archivos ignorados por Git[cite: 2]
└── venv/                        # Entorno virtual local (no se sube)[cite: 2]
```

### Ejecución
Para iniciar la aplicación en modo desarrollo, asegúrate de tener el entorno virtual activado y ejecuta:

```bash
python main.py
```

### Consideraciones para el Control de Versiones
No realizar commits de la base de datos: El archivo local de la base de datos (ej. .db o .sqlite3) está ignorado por defecto para evitar colisiones.

No subir el entorno: La carpeta venv/ y los archivos de caché de Python __pycache__/ no deben subirse jamás al repositorio.
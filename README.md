
# Sistema de Gestión - Lubri-Express

Sistema de escritorio local para la gestión integral de órdenes de trabajo, inventario (Kardex) y ventas de mostrador del taller mecánico Lubri-Express.

## Requisitos Previos

* Python 3.8 o superior
* Git

## Configuración del Entorno de Desarrollo

Sigue estos pasos para inicializar y levantar el entorno de trabajo en tu máquina local:

### 1. Clonar el repositorio
```bash
git clone <URL_DEL_REPOSITORIO>
cd lubri-express-sys
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

### Estructura del Proyecto
```text
sist_lubriexpress/
├── src/
│   └── main.py                  # Código principal de la aplicación
├── database/
│   ├── migrations/              # Scripts de migración y estructura de BD
│   └── lubriexpress.db         # Base de datos local (ignorada en Git)
├── docs/
│   ├── requirements/            # Levantamiento de requerimientos
│   └── manuals/                 # Manuales y documentación técnica
├── README.md                    # Documentación del proyecto
├── requirements.txt             # Dependencias del proyecto
├── .gitignore                   # Archivos ignorados por Git
├── venv/                        # Entorno virtual local (no se sube)
├── .git/                        # Metadatos de Git
└──main.py                  # Código principal de la aplicación
```

### Ejecución
Para iniciar la aplicación en modo desarrollo, asegúrate de tener el entorno virtual activado y ejecuta:

```bash
python src/main.py
```

### Consideraciones para el Control de Versiones
No realizar commits de la base de datos: El archivo local de la base de datos (ej. .db o .sqlite3) está ignorado por defecto para evitar colisiones.

No subir el entorno: La carpeta venv/ y los archivos de caché de Python __pycache__/ no deben subirse jamás al repositorio.
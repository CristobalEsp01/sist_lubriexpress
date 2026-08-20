# Sistema de Gestión — Lubri-Express

Aplicación de escritorio para la gestión de taller, inventario (Kardex) y ventas de
Lubri-Express (Inversiones Tres Puntos SpA). Corre localmente sobre PostgreSQL.

## Estado actual

| Módulo | Estado |
|---|---|
| Esquema de base de datos y triggers de Kardex | Funcionando |
| Mantenedor de Inventario | Funcionando |
| Mantenedor de Clientes y Vehículos | Funcionando |
| Login y control de acceso por rol | Pendiente |
| Ventas de mostrador | Pendiente |
| Órdenes de trabajo | Pendiente |
| Carga masiva desde Excel | Pendiente |
| Exportación a PDF y reportería | Pendiente |

Las entradas de mercadería y los ajustes de inventario ya funcionan a nivel de base de
datos, pero todavía no tienen pantalla: requieren un usuario autenticado, porque cada
movimiento del Kardex queda firmado por quien lo hizo.

## Requisitos

- Python 3.10 o superior
- Docker (para la base de datos)
- Git

## Instalación

### 1. Clonar y crear el entorno virtual

```bash
git clone https://github.com/CristobalEsp01/sist_lubriexpress.git
cd sist_lubriexpress
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

`requirements.txt` trae solo lo que necesita la aplicación para correr.
`requirements-dev.txt` agrega las herramientas de pruebas.

### 2. Levantar PostgreSQL

```bash
docker run -d --name lubriexpress-db \
  -e POSTGRES_PASSWORD=lubriexpress \
  -e POSTGRES_DB=lubriexpress \
  -p 127.0.0.1:55432:5432 \
  -v lubriexpress-pgdata:/var/lib/postgresql/data \
  postgres:16
```

Puerto **55432** para no chocar con un PostgreSQL instalado en la máquina, y atado a
`127.0.0.1` para que la base no quede expuesta en la red local.

En los arranques siguientes basta con `docker start lubriexpress-db`.

### 3. Cargar el esquema

```bash
docker exec -i lubriexpress-db psql -U postgres -d lubriexpress -v ON_ERROR_STOP=1 \
  < database/schema_lubriexpress.sql
```

El `-i` no es opcional: sin él, `docker exec` no pasa la entrada estándar, psql no
recibe nada y **termina con éxito sin haber ejecutado una sola línea**.

### 4. Configurar las credenciales

```bash
cp .env.example .env
```

Y dejar en `.env`:

```
DATABASE_URL=postgresql+psycopg2://postgres:lubriexpress@localhost:55432/lubriexpress
```

`.env` está en `.gitignore` y no se sube nunca.

## Uso

```bash
.venv/bin/python main.py
```

## Pruebas

```bash
.venv/bin/python -m pytest              # toda la batería
.venv/bin/python -m pytest -v tests/test_rut.py
```

No hace falta configurar nada más: `pytest.ini` resuelve las rutas y las pruebas de
interfaz corren sin abrir ventanas. Si PostgreSQL no está levantado, las pruebas que
lo necesitan se saltan solas en vez de fallar.

## Estructura

```text
sist_lubriexpress/
├── main.py                          # Punto de entrada
├── src/
│   ├── database.py                  # Motor de conexión y fábrica de sesiones
│   ├── models.py                    # Modelos ORM (SQLAlchemy)
│   ├── rut.py                       # RUT chileno: validación módulo 11 y formato
│   └── ui/
│       ├── __init__.py              # Ventana principal con pestañas
│       ├── comunes.py               # Formato de moneda y tablas compartidas
│       ├── inventario.py            # Mantenedor de Inventario
│       └── clientes.py              # Mantenedor de Clientes y Vehículos
├── database/
│   └── schema_lubriexpress.sql      # Tablas, restricciones, triggers y vistas
├── tests/
├── docs/
│   ├── base-de-datos.md             # Contrato del esquema: léelo antes de tocar stock
│   └── desarrollo.md                # Convenciones de código y de pruebas
├── requirements.txt                 # Dependencias de la aplicación
├── requirements-dev.txt             # + herramientas de pruebas
└── .env                             # Credenciales locales (no se sube)
```

## Antes de modificar el inventario

El stock **nunca** se actualiza con un `UPDATE` sobre `productos`. Se inserta el
movimiento en `kardex_movimientos` y los triggers mueven el stock. Es lo que garantiza
que todo cambio de inventario quede auditable. Está explicado en
[docs/base-de-datos.md](docs/base-de-datos.md).

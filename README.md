# Sistema de Gestión — Lubri-Express

Aplicación de escritorio para la gestión de taller, inventario (Kardex) y ventas de
Lubri-Express. Corre localmente sobre PostgreSQL.

## Estado actual

| Módulo | Estado |
|---|---|
| Esquema de base de datos y triggers de Kardex | Funcionando |
| Login y control de acceso por rol | Funcionando (tres roles; pestaña Usuarios para el administrador) |
| Mantenedor de Inventario | Funcionando (con el valorizado a precio costo de lo listado) |
| Historial de Kardex por producto | Funcionando (solo lectura) |
| Ingreso de mercadería y ajuste de stock por recuento | Funcionando |
| Carga masiva de inventario desde Excel | Funcionando (plantilla que genera el propio sistema) |
| Stock mínimo por categoría | Funcionando (acción masiva; cada producto puede sobrescribirlo) |
| Mantenedor de Clientes y Vehículos | Funcionando |
| Ventas de mostrador | Funcionando |
| Órdenes de trabajo: insumos, servicios, descuentos, folio y estado de pago | Funcionando |
| Pago parcial de una orden: abono al cerrarla y saldo cobrado después | Funcionando (el saldo se registra desde el historial) |
| Aviso al cliente por WhatsApp | Funcionando (desde la orden abierta y desde una guardada, que cita su N° de OT) |
| Exportación de la orden a PDF | Funcionando |
| Reportería (ingresos, productos, usuarios, reabastecimiento) | Funcionando (con gráficos y exportación a Excel) |
| Migración del sistema antiguo | Funcionando (`scripts/migrar_sistema_antiguo.py`) |
| Respaldo automatizado local y a OneDrive | Funcionando (`scripts/respaldar.py`, con restauración probada) |
| Aplicación empaquetada para Windows | Especificación lista (`lubriexpress.spec`); el `.exe` se construye en Windows |
| Manuales de usuario y técnico | Entregados (`docs/manuales/*.pdf`) |

Los precios del catálogo son **netos**: el IVA (19 %) se calcula al cobrar y queda
guardado en el documento, así el historial no depende de la tasa vigente. El
historial de movimientos de cada producto se consulta desde el mantenedor de
Inventario, y desde ahí se registran las entradas de mercadería y los ajustes por
recuento. Todo movimiento exige una sesión iniciada: cada línea del Kardex queda
firmada por quien la hizo.

Los reportes y los PDF de las órdenes se guardan en `Documentos/Lubri-Express/`.

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

`requirements.txt` trae solo lo que necesita la aplicación para correr;
`requirements-dev.txt` agrega las herramientas de pruebas. Al actualizar el
repositorio conviene volver a correrlo: las dependencias cambian de vez en cuando.

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

### 1. Crear el primer administrador

```bash
.venv/bin/python scripts/crear_usuario.py
```

Solo hace falta una vez por instalación: de ahí en adelante los usuarios se
administran desde la pestaña **Usuarios**, que ve únicamente el rol
`ADMINISTRADOR`. La contraseña debe tener al menos 6 caracteres y se guarda
hasheada con bcrypt.

### 2. Ejecutar el programa

```bash
.venv/bin/python main.py
```

### 3. Migrar los datos del sistema antiguo (opcional, una vez)

```bash
.venv/bin/python scripts/migrar_sistema_antiguo.py "/ruta/a/las/planillas" --detalle
```

Carga clientes, vehículos, productos, servicios y el historial de órdenes en una
sola transacción, y se niega a correr dos veces. El informe final dice qué se
descartó y por qué. **Las planillas del taller no van al repositorio**: son datos
reales de clientes y este repositorio es público.

### 4. Respaldar

```bash
.venv/bin/python scripts/respaldar.py            # deja un .sql.gz en respaldos/
.venv/bin/python scripts/restaurar.py <archivo>  # lo pone de vuelta
```

Con `RESPALDO_ONEDRIVE` configurado en el `.env`, el respaldo se copia además a
esa carpeta. En el PC del taller conviene dejarlo como tarea programada diaria.

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
├── lubriexpress.spec                # Empaquetado con PyInstaller (el .exe se arma en Windows)
├── src/
│   ├── auth.py                      # Sesión en memoria y hash de contraseñas (bcrypt)
│   ├── permisos.py                  # Qué puede hacer cada rol
│   ├── database.py                  # Motor de conexión y fábrica de sesiones
│   ├── models.py                    # Modelos ORM (SQLAlchemy)
│   ├── rut.py                       # RUT chileno: validación módulo 11 y formato
│   ├── patente.py                   # Patente chilena: formato y normalización
│   ├── texto.py                     # Normalización para buscar (sin tildes ni puntuación)
│   ├── precios.py                   # IVA: los precios del catálogo son netos
│   ├── xlsx.py                      # Leer y escribir .xlsx con la biblioteca estándar
│   ├── carga_excel.py               # Carga masiva de inventario por plantilla
│   ├── documentos.py                # La orden de trabajo como documento para el cliente
│   ├── whatsapp.py                  # Enlace wa.me y plantillas del aviso al cliente
│   ├── reportes.py                  # Los cuatro reportes, sin interfaz
│   └── ui/
│       ├── __init__.py              # Ventana principal con pestañas
│       ├── tema.py                  # Colores, tipografía y hoja de estilos
│       ├── comunes.py               # Tablas, combos buscables, totales y moneda
│       ├── login.py                 # Ventana modal para el inicio de sesión
│       ├── inventario.py            # Inventario, Kardex, ingreso y ajuste de stock
│       ├── carga_excel.py           # Diálogo de la carga masiva
│       ├── clientes.py              # Clientes y vehículos
│       ├── ventas.py                # Punto de venta, carrito e historial
│       ├── ordenes.py               # Órdenes de trabajo, aviso por WhatsApp y PDF
│       ├── reportes.py              # Pestaña de reportes con gráficos
│       └── usuarios.py              # Alta de usuarios y asignación de roles
├── database/
│   └── schema_lubriexpress.sql      # Tablas, restricciones, triggers y vistas
├── tests/
├── docs/
│   ├── convenciones.md              # Cómo se escribe en este proyecto: léelo antes de tocar src/
│   └── base-de-datos.md             # Contrato del esquema: tablas, triggers e invariantes
├── scripts/
│   ├── crear_usuario.py             # El primer administrador de una instalación
│   ├── migrar_sistema_antiguo.py    # Las cinco planillas del sistema viejo
│   ├── respaldar.py                 # Respaldo comprimido, con copia a OneDrive
│   └── restaurar.py                 # Vuelve a poner un respaldo
├── requirements.txt                 # Dependencias de la aplicación
├── requirements-dev.txt             # + pruebas y empaquetado
└── .env                             # Credenciales locales (no se sube)
```

## Antes de escribir código

Las convenciones del proyecto están en [docs/convenciones.md](docs/convenciones.md):
dónde va cada cosa, cómo se usan las piezas compartidas de `src/ui/comunes.py` y
qué reglas verifica la batería de pruebas por su cuenta. Leerlo primero ahorra
que la revisión devuelva lo mismo dos veces.

## Antes de modificar el inventario

El stock **nunca** se actualiza con un `UPDATE` sobre `productos`. Se inserta el
movimiento en `kardex_movimientos` y los triggers mueven el stock. Es lo que garantiza
que todo cambio de inventario quede auditable. Está explicado en
[docs/base-de-datos.md](docs/base-de-datos.md).

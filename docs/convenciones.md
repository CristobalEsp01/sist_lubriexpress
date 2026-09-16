# Convenciones de desarrollo

## Estructura del código

- `src/models.py` — modelos ORM. Deben calzar exactamente con el `.sql`; hay una prueba que lo verifica.
- `src/rut.py` — RUT chileno. Sin dependencias de UI ni de base de datos, para que lo pueda usar también la carga masiva desde Excel.
- `src/texto.py` — normalización para buscar (sin tildes ni puntuación), en Python y en SQL. Sin dependencias de UI.
- `src/patente.py` — patente chilena, con el mismo criterio que `rut.py`.
- `src/precios.py` — el IVA. Los precios del catálogo son netos; el impuesto se calcula al cobrar y se guarda en el documento.
- `src/permisos.py` — qué puede hacer cada rol, una acción por entrada. La sesión sigue en `src/auth.py`.
- `src/xlsx.py` — leer y escribir `.xlsx` con la biblioteca estándar. Lo usan la migración y la carga masiva; no se suma pandas ni openpyxl por esto.
- `src/carga_excel.py` — carga masiva de inventario por plantilla, sin UI. Todo o nada: una fila rechazada no deja escribir ninguna.
- `scripts/migrar_sistema_antiguo.py` — las cinco planillas del sistema viejo; las planillas viven fuera del repo.
- `lubriexpress.spec` — el empaquetado con PyInstaller para el PC del taller. El `.exe` se construye en Windows.
- `src/ui/` — un módulo por mantenedor. `comunes.py` tiene lo que comparten y `tema.py` la identidad visual.
- `main.py` — solo arranca la aplicación y avisa si la base no responde.

Un mantenedor nuevo son dos clases en su propio módulo bajo `src/ui/`: un
`QDialog` para el formulario y un `QWidget` para el listado, y una línea en
`src/ui/__init__.py` para agregar la pestaña.

`created_at` y `updated_at` no se mapean en el ORM: los mantienen los triggers.

## Piezas compartidas: búscalas antes de escribirlas

Casi todo lo que una pantalla necesita ya está resuelto. Reescribirlo no solo
cuesta tiempo: hace que la misma tarea se comporte distinto según la pestaña,
que es el peor defecto que puede tener un sistema de este tamaño.

De `src/ui/comunes.py`:

| Necesitas | Usa |
|---|---|
| Una tabla de solo lectura, ordenable | `crear_tabla(columnas, ancha, orden, numericas=…)` |
| Reordenarla tras repoblarla | `reordenar(tabla)` |
| Reajustar sus anchos sin reordenar | `ajustar_columnas(tabla)` |
| Que diga algo cuando está vacía | `con_aviso_vacio(tabla, mensaje)` y después `tabla.aviso.setText(…)` |
| Elegir un cliente, producto o cualquier registro | `hacer_buscable(combo)` — se filtra tecleando, tolera tildes y RUT sin puntos |
| Un combo donde escribir algo nuevo lo crea | `hacer_buscable(combo, libre=True)` |
| Guardar / Cancelar en un diálogo | `botonera(dialogo)` |
| Márgenes de una pestaña | `layout_de_pantalla(self)` |
| Márgenes de un diálogo | `layout_de_dialogo(self)` |
| Una fila de controles | `barra(uno, otro, …, estira=0)` |
| Mostrar neto, IVA y total de una pantalla de cobro | `bloque_total()` → `Totales.calcular(neto)` al armar, `Totales.fijar(...)` al mostrar lo guardado |
| Formatear pesos | `clp(valor)` |
| Una celda numérica que ordene por su valor | `ItemNumerico(texto, valor)` |
| Restringir una acción por rol | `puede(accion)` para apagar el botón al construir, y `exigir_permiso(accion, self)` al inicio del slot |

De `src/texto.py`:

| Necesitas | Usa |
|---|---|
| Filtrar un listado por lo que se tecleó | `filtro_busqueda(consulta, texto, Col1, Col2, …)` |
| Comparar texto ignorando tildes y puntuación | `normalizar(texto)` |

Nadie escribe un RUT con puntos ni un apellido con tilde cuando busca. Un
`ilike('%' + texto + '%')` a mano no encuentra "Pérez" tecleando "perez" ni
`12.345.678-5` tecleando `12345678`, y además se rompe con dos palabras.
`filtro_busqueda()` ya resuelve las tres cosas.

## Lo que la batería verifica sola

`tests/test_convenciones.py` falla si alguna de estas se rompe, así que el aviso
llega en la misma corrida en que se escribió el error y no en una revisión días
después:

- La aplicación nunca asigna `stock_actual`. El stock lo mueven los triggers a
  partir de un movimiento de kardex. Ya se rompió una vez y el stock quedó al doble.
- Ningún widget escribe un color a mano; los colores viven en `tema.py`.
- Las pantallas usan `layout_de_pantalla()` / `layout_de_dialogo()`, no
  `QVBoxLayout(self)` con el margen por defecto de Qt.

`tests/test_tema.py` mide el contraste WCAG de la paleta, y `conftest.py` hace
fallar la prueba si un slot de Qt lanzó una excepción — Qt se las traga y las
imprime por `sys.excepthook` sin que pytest se entere.

## Identidad visual

Todos los colores y medidas están en `src/ui/tema.py`. Ningún widget escribe un
hex a mano: si un color hace falta en dos lugares, se agrega ahí como constante.

El acento ámbar se reserva para donde el sistema está diciendo algo —pestaña
activa, campo con foco, fila seleccionada, botón de acción principal— y el rojo
óxido solo para stock bajo mínimo y cantidades negativas. Un color que aparece en
todas partes deja de señalar nada.

Las columnas numéricas van en monoespaciada (`fuente_tabular()`), incluidos RUT y
patentes: son identificadores de dígitos y alineados se escanean de un vistazo.

Seis cosas que cuestan tiempo si no se saben:

- **`resizeColumnsToContents()`, en plural, arruina la columna que estira.**
  Le aplica ancho de contenido también a la sección en `Stretch`, que deja de
  absorber el sobrante: la tabla se pasa del ancho disponible y la última
  columna —el subtotal, en una pantalla de cobro— queda detrás de una barra de
  scroll. La versión en singular respeta el modo de cada sección; eso hace
  `ajustar_columnas()`, y `reordenar()` la usa.
- **`QSpinBox.setSpecialValueText("")` con cadena vacía no hace nada:** Qt lo
  lee como "sin texto especial". Para que un campo obligatorio no muestre un
  `0` que parece dato escrito, hay que darle texto de verdad.
- **`currentRow()` no es "hay una fila elegida".** Qt conserva la celda actual
  después de un ctrl+clic que deselecciona, así que un botón encendido con
  `currentRow() >= 0` queda apuntando a una fila que ya no se ve elegida. Para
  encender un botón con la selección va `tabla.selectionModel().hasSelection()`.
- **`QComboBox.setPlaceholderText()` no hace nada si el combo es editable**, y
  `hacer_buscable()` los deja editables a todos. El texto de fondo va en
  `combo.lineEdit().setPlaceholderText(...)`.
- **`app.setStyle("Fusion")` es obligatorio.** Sin fijarlo, Qt usa el estilo nativo de cada sistema y la aplicación se ve distinta en Linux que en el Windows del taller.
- **Apenas se aplica QSS a un `QComboBox` o `QSpinBox`, Qt deja de dibujar sus flechas.** Hay que dárselas explícitamente; se usan los recursos internos de Qt (`ICONOS_QT` en `tema.py`) para no sumar imágenes al proyecto.
- **El locale se fija a es-CL** en `aplicar()`. Sin eso los `QSpinBox` muestran `$ 20,000` con coma. En la misma función se instala `qtbase_es.qm`, que traduce los botones estándar de los diálogos; al empaquetar con PyInstaller hay que incluir ese archivo.

## Roles

Tres roles (`usuarios.rol`, con CHECK en la base) y dos acciones restringidas,
en `src/permisos.py`:

| Acción | USUARIO_NORMAL | SUPERVISOR | ADMINISTRADOR |
|---|---|---|---|
| Vender, abrir órdenes, mantener clientes y vehículos, consultar inventario y Kardex | ✓ | ✓ | ✓ |
| Crear y editar productos, ingresar mercadería, ajustar stock, ver el costo | | ✓ | ✓ |
| Dar de alta usuarios y asignar roles (pestaña Usuarios) | | | ✓ |

El botón nace apagado según `puede()` y el slot vuelve a preguntar con
`exigir_permiso()`: el doble click, el atajo y las pruebas que llaman al slot
directo pasan por el mismo filtro. La pestaña Usuarios solo se agrega a la
ventana cuando el rol puede usarla. El primer administrador de una instalación
nueva se crea con `scripts/crear_usuario.py`.

## Sesiones de base de datos

Una sesión por operación, con `with SessionLocal() as db:`. Los triggers modifican
`productos` por fuera de la sesión, así que después de confirmar una venta, una orden
o un movimiento de Kardex hay que hacer `db.refresh(producto)` — si no, el objeto en
memoria sigue mostrando el stock viejo.

## Pruebas

```bash
.venv/bin/python -m pytest
```

Las pruebas corren contra la base de desarrollo real, no contra mocks: lo que más
importa verificar son los triggers, y esos solo existen en PostgreSQL. `tests/conftest.py`
se encarga de que Qt no abra ventanas y de que las pruebas se salten solas si la base
no está levantada.

Tres reglas, cada una aprendida rompiendo la batería:

**1. Nunca contar filas globalmente.** La base de desarrollo tiene datos commiteados.
Una prueba que dice `db.query(KardexMovimiento).count() == 0` pasa hoy y falla mañana,
cuando alguien registre una entrada de mercadería. Filtrar siempre por el registro de
la fixture:

```python
db.query(KardexMovimiento).filter_by(producto_id=producto.id).count() == 0
```

**2. Nunca usar identificadores fijos.** Un RUT o una patente fija termina chocando
contra el `UNIQUE` de una fila real. `tests/conftest.py` expone `rut_de_prueba()` y
`patente_de_prueba()`, que generan uno distinto en cada corrida.

**3. Revertir con SAVEPOINT, no con rollback completo.** Para probar que una operación
inválida no deja rastro, `db.begin_nested()` revierte solo el intento y deja viva la
transacción de la fixture. Un `db.rollback()` borra también los datos de la fixture y
deja la aserción sin nada que comprobar:

```python
with pytest.raises(IntegrityError):
    with db.begin_nested():
        db.add(DetalleVenta(...))   # más unidades de las que hay
        db.flush()

db.refresh(producto)
assert producto.stock_actual == 10   # intacto
```

Las pruebas que escriben con `commit()` —las de interfaz— limpian lo suyo en una
fixture con `yield`.

**Una prueba por sujeto, no por aserción.** Si dos pruebas arman el mismo
escenario para mirar dos ángulos del mismo objeto, son una sola prueba con dos
bloques; si el cuerpo se repite cambiando un dato, es `parametrize`. La suite
son 28 funciones y 79 casos, y se poda cuando crece: lo que importa es que cada
bug conocido tenga quién lo ataje, no cuántos `def test_` hay.

Antes de dar por buena una poda, reintroducir los bugs conocidos uno por uno y
verificar que la suite caiga en cada caso. Una prueba que no falla cuando el bug
vuelve no estaba cubriendo nada.

**Qt no propaga lo que revienta dentro de un slot**: imprime el traceback por
`sys.excepthook` y sigue corriendo. Sin ayuda, la batería pasa en verde mientras
la aplicación escupe un error en cada recarga de tabla. El hookwrapper
`pytest_runtest_call` de `conftest.py` vigila el excepthook y convierte eso en un
fallo de la prueba; va como hookwrapper y no como fixture porque una fixture solo
puede reclamar en el teardown, y ahí pytest ya contó la prueba como pasada.

Eso no alcanza si ninguna prueba dispara la señal. Las pruebas de interfaz tienen
que **elegir una fila** además de leer la tabla: seleccionar es lo primero que
hace cualquiera al abrir una pantalla, y es donde se juntan los `connect`.

## Deuda marcada en el código

Los atajos deliberados llevan un comentario `ponytail:` con su techo y su salida.
Para listarlos:

```bash
grep -rn "ponytail:" src/
```

Hoy hay tres: la normalización de tildes que `texto.py` escribe a mano en SQL, el
listado de inventario que carga la tabla completa en memoria, y la idempotencia de la
migración, que es un guardián global y no un upsert por fila.


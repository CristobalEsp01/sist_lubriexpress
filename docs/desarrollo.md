# Convenciones de desarrollo

## Estructura del código

- `src/models.py` — modelos ORM. Deben calzar exactamente con el `.sql`; hay una prueba que lo verifica.
- `src/rut.py` — RUT chileno. Sin dependencias de UI ni de base de datos, para que lo pueda usar también la carga masiva desde Excel.
- `src/ui/` — un módulo por mantenedor. `comunes.py` tiene lo que comparten (formato de moneda, construcción de tablas) y `tema.py` la identidad visual.
- `main.py` — solo arranca la aplicación y avisa si la base no responde.

Un mantenedor nuevo son dos clases en su propio módulo bajo `src/ui/`: un
`QDialog` para el formulario y un `QWidget` para el listado, y una línea en
`src/ui/__init__.py` para agregar la pestaña.

`created_at` y `updated_at` no se mapean en el ORM: los mantienen los triggers.

## Identidad visual

Todos los colores y medidas están en `src/ui/tema.py`. Ningún widget escribe un
hex a mano: si un color hace falta en dos lugares, se agrega ahí como constante.

El acento ámbar se reserva para donde el sistema está diciendo algo —pestaña
activa, campo con foco, fila seleccionada, botón de acción principal— y el rojo
óxido solo para stock bajo mínimo y cantidades negativas. Un color que aparece en
todas partes deja de señalar nada.

Las columnas numéricas van en monoespaciada (`fuente_tabular()`), incluidos RUT y
patentes: son identificadores de dígitos y alineados se escanean de un vistazo.

Tres cosas que cuestan tiempo si no se saben:

- **`app.setStyle("Fusion")` es obligatorio.** Sin fijarlo, Qt usa el estilo nativo de cada sistema y la aplicación se ve distinta en Linux que en el Windows del taller.
- **Apenas se aplica QSS a un `QComboBox` o `QSpinBox`, Qt deja de dibujar sus flechas.** Hay que dárselas explícitamente; se usan los recursos internos de Qt (`ICONOS_QT` en `tema.py`) para no sumar imágenes al proyecto.
- **El locale se fija a es-CL** en `aplicar()`. Sin eso los `QSpinBox` muestran `$ 20,000` con coma. En la misma función se instala `qtbase_es.qm`, que traduce los botones estándar de los diálogos; al empaquetar con PyInstaller hay que incluir ese archivo.

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

## Deuda marcada en el código

Los atajos deliberados llevan un comentario `ponytail:` con su techo y su salida.
Para listarlos:

```bash
grep -rn "ponytail:" src/
```

Hoy hay dos: el listado de inventario carga la tabla completa en memoria (sirve para
un lubricentro, no para miles de SKU) y el recordatorio de `db.refresh()` tras los
triggers de stock.

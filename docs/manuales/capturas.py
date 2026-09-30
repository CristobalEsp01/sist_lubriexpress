"""Capturas para el manual de usuario, con datos inventados.

Las pantallas del taller están llenas de nombres y patentes de clientes reales
y este repositorio es público, así que las capturas NO se toman de la base de
trabajo: se levanta una base desechable, se le cargan unos pocos registros de
fantasía y se fotografía eso.

    docker run -d --name lubriexpress-demo -e POSTGRES_PASSWORD=demo \\
      -e POSTGRES_DB=lubriexpress -p 127.0.0.1:55434:5432 postgres:16
    docker exec -i lubriexpress-demo psql -U postgres -d lubriexpress \\
      < database/schema_lubriexpress.sql
    DATABASE_URL=postgresql+psycopg2://postgres:demo@localhost:55434/lubriexpress \\
      QT_QPA_PLATFORM=offscreen .venv/bin/python docs/manuales/capturas.py
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))
DESTINO = Path(__file__).resolve().parent / "imagenes"

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication([])
for nombre in ("warning", "critical", "information"):
    setattr(QMessageBox, nombre, staticmethod(lambda *a, **k: None))

from src import finanzas  # noqa: E402
from src.auth import Sesion, hash_password  # noqa: E402
from src.database import SessionLocal  # noqa: E402
from src.models import (  # noqa: E402
    Cliente, CuentaPorCobrar, DetalleOrden, Mecanico, DetalleVenta, KardexMovimiento, MovimientoCaja, Orden,
    PagoOrden, Producto, Servicio, Ubicacion, Usuario, Vehiculo, Venta,
)
from src.ui.tema import aplicar  # noqa: E402

aplicar(app)

PRODUCTOS = [
    ("Aceite 5W30 Sintético 4L", "Mobil", "Aceite motor", 20000, 35000, 24, 6),
    ("Aceite 15W40 Mineral 4L", "Castrol", "Aceite motor", 14000, 24000, 18, 6),
    ("Filtro de aceite C-1234", "Mann", "Filtros", 4500, 8900, 12, 4),
    ("Filtro de aire A-5521", "Mann", "Filtros", 6200, 12500, 3, 5),
    ("Filtro de combustible D-330", "Bosch", "Filtros", 7800, 15000, 9, 4),
    ("Plumilla 22 pulgadas", "Bosch", "Plumillas", 4600, 9900, 7, 3),
    ("Líquido de frenos DOT4 500 ml", "Bosch", "Fluidos", 3200, 6900, 2, 4),
    ("Refrigerante verde 1 L", "Shell", "Fluidos", 3900, 7500, 15, 5),
]
SERVICIOS = [
    ("Cambio de aceite motor — sedán", "Mantención", 15126),
    ("Cambio de aceite motor — camioneta", "Mantención", 16807),
    ("Cambio de filtro de petróleo", "Mantención", 15126),
    ("Revisión de frenos", "Revisión", 12605),
    ("Rotación de neumáticos", "Mantención", 5042),
    ("Hora de taller", "Mano de obra", 20168),
]
CLIENTES = [
    ("Marcela Ríos Fuentes", "998877665", "LKTR48", "Toyota", "Yaris", 2019, "Rojo"),
    ("Jorge Bustamante Paz", "977665544", "JHSV21", "Nissan", "Np300", 2017, "Blanco"),
    ("Constructora del Sur Ltda.", "632145879", "BTKR56", "Chevrolet", "D-Max", 2021, "Gris"),
    ("Paulina Cárdenas Vera", "955443322", "HGFD90", "Hyundai", "Accent", 2015, "Azul"),
    ("Rodrigo Miranda Soto", "944332211", "KRTP12", "Kia", "Sportage", 2020, "Negro"),
]


def sembrar() -> dict:
    with SessionLocal() as db:
        if db.query(Usuario).count():
            return {"vehiculo": db.query(Vehiculo).first().id,
                    "producto": db.query(Producto).first().id,
                    "servicio": db.query(Servicio).filter(Servicio.precio_variable.is_(False)).first().id,
                    "servicio_publico": db.query(Servicio).filter(Servicio.precio_variable.is_(True)).first().id,
                    "usuario": db.query(Usuario).first().id}
        admin = Usuario(nombre="Fabián Soto", username="fabian",
                        password_hash=hash_password("demo123"), rol="ADMINISTRADOR")
        supervisor = Usuario(nombre="Camila Vidal", username="camila",
                             password_hash=hash_password("demo123"), rol="SUPERVISOR")
        mesero = Usuario(nombre="Diego Pérez", username="diego",
                         password_hash=hash_password("demo123"), rol="USUARIO_NORMAL")
        repisas = [Ubicacion(descripcion=d) for d in
                   ("M2-B", "M2-C", "Bandeja 7", "Caja Wurth", "Mueble exterior")]
        mecanicos = [Mecanico(nombre=n) for n in ("Jorge Muñoz", "Iván Castro")]
        db.add_all([admin, supervisor, mesero, *repisas, *mecanicos])
        db.flush()

        productos = []
        for indice, (nombre, marca, categoria, costo, venta, stock, minimo) in enumerate(PRODUCTOS):
            p = Producto(nombre=nombre, marca=marca, categoria=categoria,
                         ubicacion=repisas[indice % len(repisas)],
                         precio_costo=costo, precio_venta=venta, stock_minimo=minimo)
            db.add(p); db.flush()
            db.add(KardexMovimiento(producto=p, usuario=supervisor, tipo_movimiento="ENTRADA",
                                    cantidad_movida=stock, costo_unitario=costo))
            productos.append(p)
        servicios = [Servicio(nombre=n, categoria=c, precio_venta=p) for n, c, p in SERVICIOS]
        db.add_all(servicios)

        vehiculos = []
        for nombre, telefono, patente, marca, modelo, anio, color in CLIENTES:
            tipo = "EMPRESA" if "Ltda" in nombre else "PERSONA"
            cliente = Cliente(nombre_completo=nombre, telefono=telefono, tipo_cliente=tipo,
                              rut="76.543.210-K" if tipo == "EMPRESA" else None)
            vehiculo = Vehiculo(cliente=cliente, patente=patente, marca=marca, modelo=modelo,
                                anio_fabricacion=anio, color=color, combustible="Bencina",
                                transmision="Manual", tipo="Sedán")
            db.add_all([cliente, vehiculo]); vehiculos.append(vehiculo)
        db.flush()

        ahora = datetime.now()
        for i, vehiculo in enumerate(vehiculos):
            for j in range(2):
                neto = 35000 + i * 4000 + j * 2500
                iva = round(neto * 0.19)
                orden = Orden(vehiculo=vehiculo, usuario=supervisor if i % 2 else admin,
                              mecanico=mecanicos[(i + j) % 2],
                              fecha_creacion=ahora - timedelta(days=12 * (i + 1) + j * 40),
                              kilometraje_ingreso=45000 + i * 12000 + j * 8000,
                              subtotal=neto, impuesto=iva, total_final=neto + iva,
                              notas="Nivel de Combustible: Medio")
                db.add(orden); db.flush()
                db.add_all([
                    DetalleOrden(orden=orden, producto=productos[j], cantidad=1,
                                 precio_unitario_cobrado=productos[j].precio_venta),
                    DetalleOrden(orden=orden, servicio=servicios[j], cantidad=1,
                                 precio_unitario_cobrado=servicios[j].precio_venta),
                ])
                # El estado de pago no se escribe: sale de los abonos. Casi
                # todas se pagan al retirar el auto; una queda abonada y otra
                # sin pagar, que es lo que el manual muestra en el historial y
                # en el detalle de la orden.
                pagado = {(0, 0): neto + iva - 18000, (1, 0): 0}.get((i, j), neto + iva)
                if pagado:
                    db.add(PagoOrden(orden=orden, usuario=orden.usuario, monto=pagado))
        for n in range(3):
            neto = 9900 * (n + 1)
            venta = Venta(usuario=mesero, cliente=vehiculos[n].cliente,
                          numero_boleta=f"B-100{n + 1}", impuesto=round(neto * 0.19),
                          total_final=neto + round(neto * 0.19),
                          fecha_venta=ahora - timedelta(days=n))
            db.add(venta); db.flush()
            db.add(DetalleVenta(venta=venta, producto=productos[5], cantidad=n + 1,
                                precio_unitario_cobrado=productos[5].precio_venta))
        # Un auto que sigue en el taller: su orden queda abierta.
        abierta = Orden(vehiculo=vehiculos[3], usuario=supervisor,
                        fecha_creacion=ahora - timedelta(hours=5),
                        kilometraje_ingreso=96400, estado="ABIERTA",
                        subtotal=47500, impuesto=9025, total_final=56525,
                        notas="Nivel de Combustible: 1/4\nObservaciones: Espera filtro de aire")
        db.add(abierta)
        db.flush()
        db.add_all([
            DetalleOrden(orden=abierta, producto=productos[1], cantidad=1,
                         precio_unitario_cobrado=productos[1].precio_venta),
            DetalleOrden(orden=abierta, servicio=servicios[0], cantidad=1,
                         precio_unitario_cobrado=servicios[0].precio_venta),
        ])

        # Mercado Público: órdenes con folio (el trigger abre su cuenta por cobrar),
        # unas facturadas y pagadas, otras por cobrar, morosas o sin factura aún.
        organismos = [("Servicio Regional de Ejemplo", "1001-15-LE26"),
                      ("Gobernación Provincial de Ejemplo", "1001-22-LE26"),
                      ("Dirección de Prueba", "1001-31-LE26"),
                      ("Servicio Regional de Ejemplo", "1001-40-LE26")]
        for k, (nombre, folio) in enumerate(organismos):
            cli = Cliente(nombre_completo=nombre, tipo_cliente="EMPRESA", rut=f"6{k}.000.00{k}-{k}")
            veh = Vehiculo(cliente=cli, patente=f"MP{k}0{k + 1}{k}", marca="Toyota", modelo="Hilux",
                           anio_fabricacion=2021, color="Blanco", combustible="Diésel",
                           transmision="Manual", tipo="Camioneta")
            db.add_all([cli, veh]); db.flush()
            neto = 60000 + 25000 * k
            ord_mp = Orden(vehiculo=veh, usuario=admin, folio_mercado_publico=folio, mecanico=mecanicos[k % 2],
                           fecha_creacion=ahora - timedelta(days=75 - 20 * k),
                           kilometraje_ingreso=60000 + 10000 * k, estado="ENTREGADA",
                           subtotal=neto, impuesto=round(neto * 0.19), total_final=neto + round(neto * 0.19))
            db.add(ord_mp); db.flush()
            db.add_all([
                DetalleOrden(orden=ord_mp, producto=productos[0], cantidad=1,
                             precio_unitario_cobrado=productos[0].precio_venta),
                DetalleOrden(orden=ord_mp, servicio=servicios[0], cantidad=1,
                             precio_unitario_cobrado=neto - productos[0].precio_venta),
            ])
            db.flush()
        cuentas = db.query(CuentaPorCobrar).order_by(CuentaPorCobrar.id).all()
        for k, cuenta in enumerate(cuentas[:3]):    # la última queda esperando factura
            finanzas.registrar_factura(db, cuenta, str(700 + k), ahora.date() - timedelta(days=60 - 22 * k),
                                       admin.id)
        finanzas.registrar_pago_cobro(db, cuentas[0], cuentas[0].monto, ahora.date() - timedelta(days=20), admin.id)
        finanzas.crear_cuenta_manual(db, cliente_nombre="Ilustre Municipalidad de Ejemplo",
                                     numero_factura="655", fecha_factura=ahora.date() - timedelta(days=95),
                                     venta_neto=182000, costo=121000, usuario_id=admin.id)
        for nombre, plazo in (("Lubricantes del Sur Ltda.", 30), ("Distribuidora Andes SpA", 45)):
            prov = finanzas.crear_proveedor(db, nombre, plazo_credito_dias=plazo)
            for m, dias in enumerate((50, 20)):
                fac = finanzas.registrar_factura_proveedor(
                    db, prov, f"{4100 + m + plazo}", ahora.date() - timedelta(days=dias),
                    380000 + 90000 * m, admin.id)
                if m == 0 and plazo == 45:
                    finanzas.registrar_pago_proveedor(db, fac, fac.monto, ahora.date() - timedelta(days=5), admin.id)
        db.flush()

        hoy = datetime.now()
        for tipo, monto, motivo, hora in [
            ("APERTURA", 80000, "Apertura de caja", 8),
            ("EGRESO", 9500, "Bencina de la camioneta", 11),
            ("EGRESO", 18000, "Flete de repuestos", 15),
        ]:
            db.add(MovimientoCaja(usuario=mesero, tipo=tipo, monto=monto, motivo=motivo,
                                  fecha=hoy.replace(hour=hora, minute=20)))
        db.commit()
        return {"vehiculo": vehiculos[0].id, "producto": productos[0].id,
                "servicio": servicios[0].id, "usuario": admin.id,
                "servicio_publico": db.query(Servicio).filter(Servicio.precio_variable.is_(True)).first().id}


def capturar(datos: dict) -> None:
    from src.ui import LoginDialog, VentanaPrincipal
    from src.ui.carga_excel import CargaExcelDialog
    from src.ui.clientes import FormularioVehiculo
    from src.ui.inventario import AjusteStockDialog, IngresoMercaderiaDialog, MinimoPorCategoriaDialog
    from src.ui.ordenes import DialogoDetalleOrden
    from src.ui.ventas import PuntoVentaWidget

    DESTINO.mkdir(parents=True, exist_ok=True)
    guardar = lambda w, nombre: (app.processEvents(), w.grab().save(str(DESTINO / f"{nombre}.png")))

    login = LoginDialog(); login.username.setText("fabian"); login.show()
    guardar(login, "login")
    login.close()

    Sesion.iniciar(SimpleNamespace(id=datos["usuario"], nombre="Fabián Soto", rol="ADMINISTRADOR"))
    v = VentanaPrincipal(); v.resize(1160, 700); v.show()

    v.pestanias.setCurrentWidget(v.inventario); v.inventario.tabla.selectRow(0)
    guardar(v, "inventario")
    v.pestanias.setCurrentWidget(v.ventas)
    punto = v.ventas.findChild(PuntoVentaWidget)
    punto.agregar_producto(datos["producto"], cantidad=2)
    guardar(v, "ventas")
    v.pestanias.setCurrentWidget(v.clientes); v.clientes.tabla.selectRow(0)
    guardar(v, "clientes")

    v.pestanias.setCurrentWidget(v.ordenes)
    v.ordenes._iniciar_nueva_orden(datos["vehiculo"])
    v.ordenes.agregar_al_carrito(datos["producto"], 1)
    v.ordenes.agregar_servicio_al_carrito(datos["servicio"])
    v.ordenes.catalogo.busqueda.setText("filtro aceite")
    v.ordenes.spin_kilometraje.setValue(78500)
    v.ordenes.tipo_descuento.setCurrentIndex(1); v.ordenes.valor_descuento.setValue(10)
    guardar(v, "orden")
    v.ordenes._iniciar_nueva_orden(datos["vehiculo"])
    v.ordenes.folio.setText("1001-15-LE26")
    v.ordenes.agregar_al_carrito(datos["producto"], 1)
    v.ordenes._insertar_en_carrito({"servicio_id": datos["servicio_publico"], "descripcion": "Mantención 60.000 km"},
                                   "Servicio Público – Mantención 60.000 km", 118400, 1)
    guardar(v, "orden_mercado_publico")
    v.ordenes._iniciar_nueva_orden(datos["vehiculo"])
    v.ordenes.agregar_al_carrito(datos["producto"], 1)
    v.ordenes.agregar_servicio_al_carrito(datos["servicio"])
    v.ordenes.tipo_descuento.setCurrentIndex(1); v.ordenes.valor_descuento.setValue(10)
    v.ordenes.setCurrentIndex(2); v.ordenes.tabla_historial.selectRow(0)
    guardar(v, "historial_ordenes")
    v.ordenes.setCurrentIndex(0)

    v.ordenes.setCurrentIndex(1)
    v.ordenes.cargar_abiertas()
    v.ordenes.tabla_abiertas.selectRow(0)
    guardar(v, "ordenes_abiertas")
    v.ordenes.setCurrentIndex(0)

    v.pestanias.setCurrentWidget(v.caja); v.caja.recargar(); v.caja.tabla.selectRow(0)
    guardar(v, "caja")

    v.pestanias.setCurrentWidget(v.reportes)
    guardar(v, "reportes")
    titulos = [d.titulo for d in v.reportes.definiciones]
    v.reportes.lista.setCurrentRow(titulos.index("Público vs Mercado Público"))
    guardar(v, "reporte_publico_vs_mp")
    v.reportes.lista.setCurrentRow(titulos.index("Reabastecimiento"))
    guardar(v, "reabastecimiento")

    v.pestanias.setCurrentWidget(v.finanzas)
    v.finanzas.por_cobrar.recargar()
    v.finanzas.por_cobrar.tabla.selectRow(0)
    v.finanzas.setCurrentWidget(v.finanzas.por_cobrar)
    guardar(v, "finanzas_por_cobrar")
    v.finanzas.por_pagar.recargar()
    v.finanzas.por_pagar.tabla.selectRow(0)
    v.finanzas.setCurrentWidget(v.finanzas.por_pagar)
    guardar(v, "finanzas_por_pagar")
    v.pestanias.setCurrentWidget(v.usuarios); v.usuarios.tabla.selectRow(0)
    guardar(v, "usuarios")

    with SessionLocal() as db:
        orden_id = db.query(Orden).order_by(Orden.id).first().id
    from src.ui.ordenes import DialogoServicioPublico
    servicio_publico = DialogoServicioPublico(lambda neto: neto + round(neto * 0.19))
    servicio_publico.descripcion.setText("Mantención 60.000 km")
    servicio_publico.presupuesto.setValue(118400)
    ingreso = IngresoMercaderiaDialog()
    ingreso.combo_productos.setCurrentIndex(0)
    ingreso.spin_cantidad.setValue(12)
    ingreso.spin_costo.setValue(21500)   # el proveedor subió el precio
    ingreso.agregar_a_lista()

    for nombre, dialogo in [
        ("dialogo_ingreso", ingreso),
        ("dialogo_ajuste", AjusteStockDialog(producto_id=datos["producto"])),
        ("dialogo_minimos", MinimoPorCategoriaDialog()),
        ("dialogo_excel", CargaExcelDialog()),
        ("dialogo_vehiculo", FormularioVehiculo(cliente_id=1)),
        ("dialogo_detalle_orden", DialogoDetalleOrden(orden_id)),
        ("dialogo_servicio_publico", servicio_publico),
    ]:
        dialogo.show()
        guardar(dialogo, nombre)
        dialogo.close()

    from src.ui.ordenes import guardar_pdf_de_orden
    guardar_pdf_de_orden(orden_id, DESTINO.parent / "ejemplo-orden.pdf")


if __name__ == "__main__":
    if "55432" in os.getenv("DATABASE_URL", ""):
        raise SystemExit("Apunta a la base de demostración, no a la de trabajo: "
                         "sus pantallas traen datos reales de clientes.")
    capturar(sembrar())
    print(f"Capturas en {DESTINO}")

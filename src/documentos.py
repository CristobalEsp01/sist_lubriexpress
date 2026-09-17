"""Documentos para el cliente: la orden de trabajo como HTML, que la pantalla
convierte a PDF con QTextDocument (ver `guardar_pdf_de_orden` en ordenes.py).

Sin Qt a propósito: el HTML se prueba sin ventana. Las cifras vienen ya
guardadas en la orden (subtotal, descuento aplicado, impuesto, total): acá no
se recalcula nada, se muestra lo que se cobró.
"""
from html import escape

from .precios import clp

# El membrete y el pie del informe técnico que el taller ya usaba en papel.
TALLER = "LUBRI-EXPRESS"
DIRECCION = "Rene Schneider 3631"
TELEFONO = "+56920489399"
SITIO = "www.lubri-express.cl"
CORREO = "contacto@lubri-express.cl"
PIE = f"{DIRECCION} | {TELEFONO} | {CORREO} | {SITIO}"
# Las dos cifras que el cliente busca con el dedo: lo que salió y lo que debe.
DESTACADOS = ("Total", "Saldo")


def estado_de_pago(pagada: bool, pagado: int, total: int) -> str:
    """Cómo se nombra el pago de una orden, en el PDF y en pantalla.

    Una orden a medio pagar no es "No pagada": el cliente que abonó la mitad
    y lee eso en su copia vuelve al mesón a reclamar, con razón.
    """
    if pagada:
        return "Pagada"
    if pagado:
        return f"Abonada {clp(pagado)} · saldo {clp(total - pagado)}"
    return "No pagada"


def html_de_orden(o: dict) -> str:
    """`o` trae: numero, fecha, cliente, rut, telefono, patente, vehiculo,
    kilometraje, tecnico, lineas [(nombre, cantidad, precio_unitario)],
    subtotal, descuento, impuesto, total, pagada, pagado, folio, notas."""
    e = escape
    filas = "".join(
        f"<tr><td>{e(nombre)}</td><td align='right'>{cantidad}</td>"
        f"<td align='right'>{clp(precio)}</td><td align='right'>{clp(precio * cantidad)}</td></tr>"
        for nombre, cantidad, precio in o["lineas"]
    ) or "<tr><td colspan='4'>Orden sin detalle de insumos.</td></tr>"
    totales = [("Neto", clp(o["subtotal"]))]
    if o["descuento"]:
        totales.append(("Descuento", f"- {clp(o['descuento'])}"))
    totales += [("IVA 19 %", clp(o["impuesto"])), ("Total", clp(o["total"]))]
    # Lo abonado y el saldo solo salen cuando la orden quedó a medio pagar: al
    # contado serían dos filas para decir cero.
    if o["pagado"] and not o["pagada"]:
        totales += [("Abonado", f"- {clp(o['pagado'])}"),
                    ("Saldo", clp(int(o["total"]) - o["pagado"]))]
    filas_totales = "".join(
        f"<tr><td align='right'><b>{rotulo}</b></td><td align='right'>"
        f"{'<b>' if rotulo in DESTACADOS else ''}{cifra}"
        f"{'</b>' if rotulo in DESTACADOS else ''}</td></tr>"
        for rotulo, cifra in totales
    )
    km = f"{o['kilometraje']:,} km".replace(",", ".") if o["kilometraje"] is not None else "sin registrar"
    estado = estado_de_pago(o["pagada"], o["pagado"], int(o["total"]))
    folio = f"<br><b>Folio Mercado Público:</b> {e(o['folio'])}" if o["folio"] else ""
    contacto = " · ".join(filter(None, (o.get("rut"), o.get("telefono"))))
    # El logo va como recurso del documento (ver guardar_pdf_de_orden); si no se
    # cargó, la celda queda vacía y el resto del membrete no cambia.
    return f"""<html><body style="font-family: sans-serif; font-size: 10pt;">
<table width="100%" cellpadding="0">
<tr>
  <td valign="top"><h2 style="margin: 0;">ORDEN DE TRABAJO</h2>
      <p style="margin: 2px 0 0 0;"><b>N° {o['numero']}</b> | {o['fecha']:%d-%m-%Y %H:%M}</p></td>
  <td align="right" valign="top" style="font-size: 8pt; color: gray;">
      {e(TALLER)}<br>{e(DIRECCION)}<br>{e(TELEFONO)}<br>{e(SITIO)}<br>{e(CORREO)}</td>
  <td align="right" valign="top" width="90"><img src="logo" width="80"></td>
</tr>
</table>
<hr>
<table width="100%" cellpadding="4">
<tr><td width="50%"><b>Cliente</b><br>{e(o['cliente'])}{('<br>' + e(contacto)) if contacto else ''}</td>
<td><b>Vehículo</b><br>{e(o['vehiculo'])}<br>Patente <b>{e(o['patente'])}</b> · {km}</td></tr>
<tr><td><b>Técnico</b><br>{e(o['tecnico'])}</td><td><b>Estado</b><br>{estado}{folio}</td></tr>
</table>
<h3>Insumos y servicios</h3>
<table width="100%" border="1" cellspacing="0" cellpadding="4">
<tr><th align="left">Ítem</th><th align="right">Cant.</th><th align="right">Precio unit.</th><th align="right">Subtotal</th></tr>
{filas}
</table>
<table width="100%" cellpadding="3">{filas_totales}</table>
<h3>Notas</h3>
<p>{e(o['notas'] or 'Sin observaciones.').replace(chr(10), '<br>')}</p>
<hr>
<p align="center" style="font-size: 8pt; color: gray;">{e(PIE)}</p>
</body></html>"""

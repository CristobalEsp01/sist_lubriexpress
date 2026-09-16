"""Documentos para el cliente: la orden de trabajo como HTML, que la pantalla
convierte a PDF con QTextDocument (ver `guardar_pdf_de_orden` en ordenes.py).

Sin Qt a propósito: el HTML se prueba sin ventana. Las cifras vienen ya
guardadas en la orden (subtotal, descuento aplicado, impuesto, total): acá no
se recalcula nada, se muestra lo que se cobró.
"""
from html import escape

from .precios import clp

TALLER = "Lubri-Express — Inversiones Tres Puntos SpA"


def html_de_orden(o: dict) -> str:
    """`o` trae: numero, fecha, cliente, rut, telefono, patente, vehiculo,
    kilometraje, tecnico, lineas [(nombre, cantidad, precio_unitario)],
    subtotal, descuento, impuesto, total, pagada, folio, notas."""
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
    filas_totales = "".join(
        f"<tr><td align='right'><b>{rotulo}</b></td><td align='right'>"
        f"{'<b>' if rotulo == 'Total' else ''}{cifra}{'</b>' if rotulo == 'Total' else ''}</td></tr>"
        for rotulo, cifra in totales
    )
    km = f"{o['kilometraje']:,} km".replace(",", ".") if o["kilometraje"] is not None else "sin registrar"
    estado = "Pagada" if o["pagada"] else "No pagada"
    folio = f"<br><b>Folio Mercado Público:</b> {e(o['folio'])}" if o["folio"] else ""
    contacto = " · ".join(filter(None, (o.get("rut"), o.get("telefono"))))
    return f"""<html><body style="font-family: sans-serif; font-size: 10pt;">
<h2 style="margin-bottom: 0;">Orden de Trabajo N° {o['numero']}</h2>
<p style="color: gray; margin-top: 0;">{e(TALLER)}<br>{o['fecha']:%d-%m-%Y %H:%M}</p>
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
</body></html>"""

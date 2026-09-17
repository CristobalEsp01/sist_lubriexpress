"""Avisos al cliente por WhatsApp.

Vive fuera de la UI, igual que rut.py y texto.py: el enlace y la redacción son
reglas de negocio —qué se le dice al cliente y cómo se arma el número— y se
prueban sin levantar Qt ni la base.

El envío es por `wa.me`, que abre WhatsApp de escritorio si está instalado y
WhatsApp Web si no. No se manda nada automático: el enlace deja el mensaje
escrito en la conversación y el operador aprieta enviar. Es a propósito —
mandar solo, sin que nadie lea lo que sale, es como se le avisa a un cliente
que su auto está listo cuando todavía no lo está.
"""
import re
from urllib.parse import quote

# El orden importa: es el que ve el operador en el desplegable, y el primero
# viene elegido. "Listo para retiro" es el aviso que se manda todos los días.
PLANTILLAS: dict[str, str] = {
    "Listo para retiro": (
        "Hola {cliente}, le saludamos de Lubri-Express.\n\n"
        "Su vehículo {vehiculo} ya está listo para ser retirado. Lo esperamos "
        "en nuestro horario de atención.\n\n"
        "¡Gracias por preferirnos!"
    ),
    "Trabajo en curso": (
        "Hola {cliente}, le saludamos de Lubri-Express.\n\n"
        "Le informamos que su vehículo {vehiculo} se encuentra en proceso de "
        "mantención. Le avisaremos por este mismo medio apenas esté listo "
        "para retiro."
    ),
    "Requiere su autorización": (
        "Hola {cliente}, le saludamos de Lubri-Express.\n\n"
        "Revisando su vehículo {vehiculo} detectamos un trabajo adicional que "
        "necesita su autorización antes de continuar. ¿Podría confirmarnos si "
        "desea que lo realicemos?"
    ),
    "Esperando repuesto": (
        "Hola {cliente}, le saludamos de Lubri-Express.\n\n"
        "Para terminar el trabajo en su vehículo {vehiculo} estamos a la "
        "espera de un repuesto. Le confirmaremos la fecha de entrega apenas "
        "lo tengamos disponible."
    ),
}


def enlace_whatsapp(telefono: str | None, mensaje: str | None = None) -> str | None:
    """'9 5666 7509' -> 'https://wa.me/56956667509'. Celulares chilenos: 9
    dígitos, o 8 de los tiempos en que el 9 no se anotaba. Otra cosa, None.

    Con `mensaje` agrega el texto ya escrito en la conversación (?text=), que
    es lo que WhatsApp deja listo para que el operador lo revise y envíe.
    """
    digitos = re.sub(r"\D", "", telefono or "")
    if digitos.startswith("56") and len(digitos) == 11:
        numero = digitos
    # Nueve dígitos que no parten en 9 son un fijo (223334444 es Santiago), y
    # WhatsApp sobre un fijo abre una conversación que no existe. El botón se
    # apaga en vez de prometer un aviso que el cliente nunca va a recibir.
    elif len(digitos) == 9 and digitos.startswith("9"):
        numero = f"56{digitos}"
    elif len(digitos) == 8:
        numero = f"569{digitos}"
    else:
        return None
    enlace = f"https://wa.me/{numero}"
    # quote() por sobre quote_plus(): en un query de WhatsApp el '+' viaja
    # literal y el cliente recibiría "Su+vehículo+está+listo".
    return f"{enlace}?text={quote(mensaje)}" if mensaje else enlace


def describir_vehiculo(patente: str, marca: str | None = None,
                       modelo: str | None = None, anio: int | None = None) -> str:
    """Cómo se nombra el auto dentro del mensaje, sin que nunca quede cojo.

    Va entero en un solo hueco de la plantilla, no repartido en dos, porque
    "su vehículo {vehiculo} (patente {patente})" con un auto sin marca deja
    "su vehículo  (patente KDXS12)". La patente es el único dato garantizado
    —la columna es NOT NULL— así que es la que sostiene el caso sin marca.
    """
    partes = [p for p in (marca, modelo, str(anio) if anio else None) if p]
    if not partes:
        return f"de patente {patente}"
    return f"{' '.join(partes)} (patente {patente})"


def redactar(plantilla: str, *, cliente: str, vehiculo: str,
             orden_id: int | None = None) -> str:
    """Arma el borrador que el operador va a revisar antes de enviarlo.

    El nombre va tal como está guardado, sin recortarlo al primer nombre: los
    clientes institucionales son razones sociales ("Transportes Sur SpA") y
    cortarlas deja un saludo a "Transportes". Si queda largo, el operador lo
    edita — para eso el mensaje se muestra en una caja editable.
    """
    texto = PLANTILLAS[plantilla].format(cliente=cliente.strip(), vehiculo=vehiculo.strip())
    # La OT recién se numera al guardarla: mientras la orden está en pantalla
    # sin guardar no hay número que citar, y no se inventa uno.
    if orden_id is not None:
        texto += f"\n\nOrden de trabajo N° {orden_id}."
    return texto

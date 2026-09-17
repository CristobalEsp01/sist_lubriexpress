"""El enlace y la redacción del aviso por WhatsApp, sin Qt ni base de datos."""
from urllib.parse import parse_qs, urlparse

import pytest

from src.whatsapp import PLANTILLAS, describir_vehiculo, enlace_whatsapp, redactar


@pytest.mark.parametrize("telefono, esperado", [
    ("9 5666 7509", "https://wa.me/56956667509"),      # como se anota en el mesón
    ("+56 9 8220 0997", "https://wa.me/56982200997"),  # con código de país
    ("56982200997", "https://wa.me/56982200997"),      # todo junto
    ("82200997", "https://wa.me/56982200997"),         # sin el 9 de antes
])
def test_arma_el_numero_como_sea_que_este_escrito(telefono, esperado):
    assert enlace_whatsapp(telefono) == esperado


@pytest.mark.parametrize("telefono", [
    "", None, "123",
    "223334444",   # fijo de Santiago: nueve dígitos, pero parte en 2
    "22333444",    # el mismo fijo como se anotaba antes: ocho dígitos
    "632222333",   # fijo de Valdivia
    "9566675091",  # diez dígitos: un celular con un dígito de más
])
def test_lo_que_no_parece_celular_chileno_no_da_enlace(telefono):
    """Los fijos importan: son nueve dígitos igual que un celular, y WhatsApp
    sobre un fijo abre una conversación vacía. Mejor el botón apagado que un
    aviso que el cliente nunca recibe."""
    assert enlace_whatsapp(telefono) is None


def test_el_mensaje_viaja_en_la_url_sin_convertir_los_espacios_en_mas():
    url = enlace_whatsapp("9 5666 7509", "Su vehículo está listo")
    # parse_qs revierte la codificación: si los espacios hubieran viajado como
    # '+' esto pasaría igual, así que además se mira la cadena cruda.
    assert parse_qs(urlparse(url).query)["text"] == ["Su vehículo está listo"]
    assert "+" not in urlparse(url).query


def test_sin_mensaje_el_enlace_queda_limpio():
    assert enlace_whatsapp("9 5666 7509") == "https://wa.me/56956667509"


def test_describe_el_vehiculo_con_lo_que_haya():
    assert describir_vehiculo("KDXS12", "Toyota", "Hilux", 2019) == (
        "Toyota Hilux 2019 (patente KDXS12)"
    )
    assert describir_vehiculo("KDXS12", "Toyota") == "Toyota (patente KDXS12)"
    # Sin marca ni modelo la frase se sostiene en la patente, que es NOT NULL.
    assert describir_vehiculo("KDXS12") == "de patente KDXS12"


@pytest.mark.parametrize("plantilla", list(PLANTILLAS))
@pytest.mark.parametrize("vehiculo", [
    describir_vehiculo("KDXS12", "Toyota", "Hilux", 2019),
    describir_vehiculo("KDXS12"),
])
def test_ninguna_plantilla_queda_coja(plantilla, vehiculo):
    """Un auto sin marca no puede dejar 'su vehículo  (patente ...)'.

    Pasó al escribir esto: la plantilla nombraba el vehículo en dos huecos y
    el respaldo de uno repetía la palabra del otro.
    """
    texto = redactar(plantilla, cliente="Juan Pérez", vehiculo=vehiculo)
    assert "{" not in texto           # ningún hueco sin rellenar
    assert "  " not in texto          # ningún dato faltante dejando el doble espacio
    assert "vehículo vehículo" not in texto
    assert "Juan Pérez" in texto and "KDXS12" in texto


def test_la_razon_social_se_saluda_entera():
    # Recortar al primer nombre dejaría "Hola Transportes,".
    texto = redactar(
        "Listo para retiro", cliente="Transportes Sur SpA",
        vehiculo=describir_vehiculo("KDXS12"),
    )
    assert "Transportes Sur SpA" in texto


def test_la_ot_se_cita_solo_cuando_ya_tiene_numero():
    """La orden en pantalla todavía no está guardada y no tiene id: el mensaje
    no puede citar un número que la base aún no asignó."""
    vehiculo = describir_vehiculo("KDXS12", "Toyota")
    assert "Orden de trabajo" not in redactar(
        "Listo para retiro", cliente="Juan", vehiculo=vehiculo
    )
    assert "Orden de trabajo N° 42." in redactar(
        "Listo para retiro", cliente="Juan", vehiculo=vehiculo, orden_id=42
    )

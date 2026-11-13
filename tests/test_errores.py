"""La captura de errores inesperados: el aviso único y el `errores.log`.

En el .exe no hay consola: sin esto, lo que revienta en un slot de Qt se
imprime en ninguna parte y el usuario ve que "Guardar" no hizo nada.
"""
import sys

from sqlalchemy.exc import OperationalError

from src import errores
from src.errores import ARCHIVO, mensaje, registrar


def error(texto: str):
    try:
        raise ValueError(texto)
    except ValueError:
        return sys.exc_info()


def test_el_error_queda_en_el_log_con_su_rastro(tmp_path):
    texto = registrar(*error("boom"), carpeta=tmp_path).read_text(encoding="utf-8")
    assert texto.startswith("=== ")
    assert "Traceback" in texto and "ValueError: boom" in texto


def test_el_log_no_crece_sin_tope(tmp_path, monkeypatch):
    monkeypatch.setattr(errores, "TOPE", 2000)
    for i in range(60):
        registrar(*error(f"n{i}"), carpeta=tmp_path)
    texto = (tmp_path / ARCHIVO).read_text(encoding="utf-8")
    assert len(texto.encode()) <= 2000
    assert texto.startswith("=== ") and "n59" in texto


def test_el_mensaje_distingue_la_conexion_caida():
    assert "conexión" in mensaje(OperationalError("SELECT 1", {}, Exception("x")))
    assert "inesperado" in mensaje(ValueError())
    assert mensaje(ValueError()).endswith("El detalle quedó en errores.log, junto al programa.")


def test_una_rafaga_de_errores_muestra_un_solo_aviso(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from src.ui import errores as pantalla

    monkeypatch.setattr(errores, "carpeta_app", lambda: tmp_path)
    avisos = []

    def critical(*args, **kwargs):
        avisos.append(args[2])
        pantalla.manejar(*error("mientras el aviso está abierto"))
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "critical", critical)
    pantalla.manejar(*error("a"))
    assert len(avisos) == 1
    pantalla.manejar(*error("b"))                     # cerrado el aviso, el siguiente se ve
    assert len(avisos) == 2
    assert (tmp_path / ARCHIVO).read_text(encoding="utf-8").count("=== ") == 4

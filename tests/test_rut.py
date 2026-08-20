import pytest

from src.rut import digito_verificador, es_valido, formatear, normalizar

# 77.297.666-6 es el RUT de Inversiones Tres Puntos SpA que aparece en la propuesta:
# sirve de contraste contra una fuente externa al código.
VALIDOS = ["77.297.666-6", "11.111.111-1", "22.222.222-2", "12.345.678-5", "12345678-5", "123456785"]
INVALIDOS = ["77.297.666-5", "11.111.111-2", "12.345.678-9", "", "abc", "1234-5", "123456789012"]


@pytest.mark.parametrize("rut", VALIDOS)
def test_ruts_validos(rut):
    assert es_valido(rut)


@pytest.mark.parametrize("rut", INVALIDOS)
def test_ruts_invalidos(rut):
    assert not es_valido(rut)


def test_normalizar_saca_puntos_guion_y_espacios():
    assert normalizar(" 12.345.678-k ") == "12345678K"


def test_formatear_es_estable_venga_como_venga():
    assert formatear("123456785") == formatear("12.345.678-5") == "12.345.678-5"
    assert formatear("9561396-9") == "9.561.396-9"


def test_dv_k_y_cero():
    # Los dos casos que rompen las implementaciones ingenuas del módulo 11.
    assert digito_verificador("11111111") == "1"
    assert es_valido(f"12345670-{digito_verificador('12345670')}")

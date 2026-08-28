import pytest

from src.rut import digito_verificador, es_valido, formatear, normalizar

# 77.297.666-6 es el RUT de Inversiones Tres Puntos SpA que aparece en la propuesta:
# sirve de contraste contra una fuente externa al código.
RUTS = [
    ("77.297.666-6", True), ("11.111.111-1", True), ("22.222.222-2", True),
    ("12.345.678-5", True), ("12345678-5", True), ("123456785", True),
    ("77.297.666-5", False), ("11.111.111-2", False), ("12.345.678-9", False),
    ("", False), ("abc", False), ("1234-5", False), ("123456789012", False),
]


@pytest.mark.parametrize("rut, valido", RUTS)
def test_es_valido(rut, valido):
    assert es_valido(rut) is valido


def test_normalizar_y_formatear():
    assert normalizar(" 12.345.678-k ") == "12345678K"
    assert formatear("123456785") == formatear("12.345.678-5") == "12.345.678-5"
    assert formatear("9561396-9") == "9.561.396-9"

    # El RUT es opcional: el formulario llama a formatear() con el campo vacío.
    assert formatear("") == formatear("   ") == ""

    # Los dos casos que rompen las implementaciones ingenuas del módulo 11.
    assert digito_verificador("11111111") == "1"
    assert es_valido(f"12345670-{digito_verificador('12345670')}")

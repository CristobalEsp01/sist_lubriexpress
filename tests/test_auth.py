"""Hash y verificación de contraseñas: no toca la base de datos."""
from src.auth import hash_password, verificar_password


def test_una_contrasena_correcta_verifica():
    hash_ = hash_password("aceite2026")
    assert verificar_password("aceite2026", hash_)


def test_una_contrasena_incorrecta_no_verifica():
    hash_ = hash_password("aceite2026")
    assert not verificar_password("otra-clave", hash_)


def test_dos_hashes_de_la_misma_clave_son_distintos():
    # bcrypt genera una sal distinta cada vez: dos hashes de "123456" no
    # deben coincidir como texto, aunque ambos verifiquen la misma contraseña.
    assert hash_password("123456") != hash_password("123456")


def test_un_hash_con_formato_invalido_no_revienta():
    # Ej: datos de prueba antiguos con password_hash="x", que no es un hash
    # bcrypt válido. Debe fallar la verificación, no lanzar una excepción.
    assert not verificar_password("cualquier-cosa", "no-es-un-hash-bcrypt")

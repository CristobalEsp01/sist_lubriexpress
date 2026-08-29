"""Hash y verificación de contraseñas: no toca la base de datos."""
from src.auth import hash_password, verificar_password


def test_hash_y_verificacion():
    hash_ = hash_password("aceite2026")
    assert verificar_password("aceite2026", hash_)
    assert not verificar_password("otra-clave", hash_)

    # bcrypt sala cada hash: dos de la misma clave no coinciden como texto.
    assert hash_password("123456") != hash_password("123456")

    # Datos viejos con password_hash="x" no son bcrypt válido: eso tiene que
    # fallar la verificación, no reventar.
    assert not verificar_password("cualquier-cosa", "no-es-un-hash-bcrypt")

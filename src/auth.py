"""Autenticación: hash de contraseñas (bcrypt) y la sesión de quien tiene el
turno abierto.

Es deliberadamente mínimo: no hay tokens, ni expiración, ni multi-sesión.
El sistema es de escritorio y de un solo usuario conectado a la vez (Propuesta
3.1), así que basta con saber quién inició sesión mientras la app está abierta.
"""
import bcrypt


def hash_password(password: str) -> str:
    """Genera un hash con sal aleatoria, listo para guardar en usuarios.password_hash."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verificar_password(password: str, password_hash: str) -> bool:
    """Compara una contraseña en texto plano contra un hash ya guardado."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Hash con formato inválido (por ejemplo, "x" en datos de prueba
        # antiguos). No es una contraseña correcta: no revienta, solo falla.
        return False


class Sesion:
    """Quién tiene el turno abierto. Vive solo en memoria del proceso: no
    sobrevive a un reinicio, y así debe ser — cada apertura de la aplicación
    exige volver a autenticarse (login.py se encarga de eso al arrancar).
    """

    usuario_id: int | None = None
    nombre: str | None = None
    rol: str | None = None

    @classmethod
    def iniciar(cls, usuario) -> None:
        """Recibe cualquier objeto con .id, .nombre y .rol (un Usuario del ORM
        o, en pruebas, un objeto liviano equivalente)."""
        cls.usuario_id = usuario.id
        cls.nombre = usuario.nombre
        cls.rol = usuario.rol

    @classmethod
    def cerrar(cls) -> None:
        cls.usuario_id = None
        cls.nombre = None
        cls.rol = None

    @classmethod
    def activa(cls) -> bool:
        return cls.usuario_id is not None

"""Punto de entrada de la aplicación de escritorio."""
import sys

from sqlalchemy.exc import OperationalError

from src.database import engine


def ejecutar_sesiones(app) -> int:
    """Login → ventana principal, y de nuevo el login cada vez que se cierra la
    sesión desde el botón. Termina cuando se cancela el login o se cierra la
    ventana con la X."""
    from src.ui import LoginDialog, VentanaPrincipal

    while True:
        if not LoginDialog().exec():
            return 0  # se cerró el login sin ingresar

        ventana = VentanaPrincipal()
        # Maximizada: en el portátil del taller (1366×768) la ventana por defecto
        # no alcanza para la pantalla de órdenes.
        ventana.showMaximized()
        resultado = app.exec()
        if not ventana.sesion_cerrada:
            return resultado
        ventana.deleteLater()   # la siguiente sesión arma la suya, con sus permisos


def main() -> int:
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication(sys.argv)

    from src.ui.tema import aplicar

    aplicar(app)

    try:
        engine.connect().close()
    except OperationalError as e:
        QMessageBox.critical(
            None, "Sin conexión a la base de datos",
            f"No se pudo conectar usando DATABASE_URL.\n\n{e.orig}",
        )
        return 1

    return ejecutar_sesiones(app)


if __name__ == "__main__":
    sys.exit(main())

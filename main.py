"""Punto de entrada de la aplicación de escritorio."""
import sys

from sqlalchemy.exc import OperationalError

from src.database import engine


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

    from src.ui import LoginDialog, VentanaPrincipal

    if not LoginDialog().exec():
        return 0  # se cerró el login sin ingresar

    ventana = VentanaPrincipal()
    ventana.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

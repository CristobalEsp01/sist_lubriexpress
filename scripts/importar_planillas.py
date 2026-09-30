"""Importa las planillas de Excel antiguas (por cobrar / por pagar) al módulo Finanzas.

Función de prueba: por defecto NO escribe nada, solo muestra un informe de lo
que haría. Con --aplicar guarda (antes hace un respaldo, y todo va en una sola
transacción: si algo falla, no queda nada a medias). Volver a correrlo no
duplica: lo que ya está (mismo N° de factura) se salta.

Uso, desde el repositorio:

    .venv/Scripts/python scripts/importar_planillas.py --cobrar "C:\\ruta\\X_COBRAR.xlsx" --pagar "C:\\ruta\\X_PAGAR.xlsx"
    ... y lo mismo con --aplicar para guardar
    .venv/Scripts/python scripts/importar_planillas.py --deshacer

--deshacer saca todo lo importado (las cuentas y facturas marcadas como
"Importada de planilla", con sus pagos). Los proveedores creados se dejan.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import importar_planillas as imp  # noqa: E402
from src.precios import clp  # noqa: E402

MAX_DETALLE = 25


def _titulo(texto: str) -> None:
    print(f"\n{texto}\n{'-' * len(texto)}")


def _omitidas(lectura: imp.Lectura) -> None:
    if not lectura.omitidas:
        return
    print("\n  Filas que NO se importan:")
    for motivo, cuantas in imp.resumen_por_motivo(lectura.omitidas).most_common():
        print(f"    {cuantas:4d}  {motivo}")
    for o in lectura.omitidas[:MAX_DETALLE]:
        if o.detalle:
            print(f"          · {o.hoja} fila {o.fila}: {o.motivo} — {o.detalle}")
    resto = len([o for o in lectura.omitidas if o.detalle]) - MAX_DETALLE
    if resto > 0:
        print(f"          … y {resto} más")


def _avisos(lectura: imp.Lectura) -> None:
    if lectura.avisos:
        print("\n  Avisos (se importan igual, conviene mirarlos):")
        for aviso in lectura.avisos:
            print(f"    · {aviso}")


def informe_cobrar(lectura: imp.Lectura, plan: imp.Plan) -> None:
    _titulo("POR COBRAR")
    sin_pago = [c for c in plan.nuevas if not c.fecha_pago]
    print(f"  Filas con factura: {len(lectura.items)}")
    print(f"  Ya estaban en el sistema: {len(plan.existentes)}")
    print(f"  Se crearían: {len(plan.nuevas)} "
          f"({len(plan.nuevas) - len(sin_pago)} pagadas, {len(sin_pago)} por cobrar)")
    if sin_pago:
        print(f"  Por cobrar: {clp(sum(c.total for c in sin_pago))} en total")
        for c in sin_pago:
            print(f"    · factura {c.factura} — {c.cliente} — {clp(c.total)} — emitida {c.fecha_factura:%d-%m-%Y}")
    _omitidas(lectura)
    _avisos(lectura)


def informe_pagar(lectura: imp.Lectura, plan: imp.Plan, nombres: dict[str, str]) -> None:
    _titulo("POR PAGAR")
    pendientes = []
    for f in plan.nuevas:
        pagado = sum(m for m, _ in f.pagos)
        if pagado < f.monto:
            pendientes.append((f, f.monto - pagado))
    print(f"  Facturas distintas: {len(lectura.items)} (repetidas y descartadas: {lectura.duplicadas})")
    print(f"  Ya estaban en el sistema: {len(plan.existentes)}")
    print(f"  Se crearían: {len(plan.nuevas)} ({len(plan.nuevas) - len(pendientes)} pagadas, "
          f"{len(pendientes)} con saldo)")
    if pendientes:
        print(f"  Saldo por pagar: {clp(sum(s for _, s in pendientes))}")
        for f, saldo in pendientes:
            print(f"    · {f.proveedor} — factura {f.numero} — saldo {clp(saldo)} — vence {f.vence:%d-%m-%Y}")
    _omitidas(lectura)
    _avisos(lectura)

    grupos: dict[str, set[str]] = {}
    for original, unificado in nombres.items():
        grupos.setdefault(unificado, set()).add(original)
    print(f"\n  Proveedores: {len(grupos)} (a partir de {len(nombres)} nombres distintos en la planilla)")
    for unificado, originales in sorted(grupos.items()):
        otros = sorted(originales - {unificado})
        print(f"    {unificado}" + (f"   ← {' | '.join(otros)}" if otros else ""))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Importa las planillas antiguas a Finanzas.")
    p.add_argument("--cobrar", type=Path, help="planilla de cuentas por cobrar (.xlsx)")
    p.add_argument("--pagar", type=Path, help="planilla de cuentas por pagar (.xlsx)")
    p.add_argument("--aplicar", action="store_true", help="guardar de verdad (sin esto solo informa)")
    p.add_argument("--deshacer", action="store_true", help="sacar todo lo importado antes")
    args = p.parse_args(argv)

    if not (args.cobrar or args.pagar or args.deshacer):
        p.error("indica --cobrar y/o --pagar (o --deshacer)")
    for ruta in (args.cobrar, args.pagar):
        if ruta and not ruta.is_file():
            p.error(f"no existe el archivo: {ruta}")

    from src.database import SessionLocal

    with SessionLocal() as db:
        if args.deshacer:
            if not args.aplicar:
                print("Para confirmar el deshacer, agrega --aplicar.")
                return 0
            _respaldar()
            hechos = imp.deshacer(db)
            db.commit()
            print(f"Deshecho: {hechos['cuentas']} cuentas por cobrar ({hechos['pagos_cobro']} pagos) y "
                  f"{hechos['facturas']} facturas de proveedor ({hechos['pagos_proveedor']} pagos).")
            return 0

        plan_c = plan_p = None
        if args.cobrar:
            lectura = imp.leer_por_cobrar(args.cobrar)
            plan_c = imp.planificar_por_cobrar(db, lectura)
            informe_cobrar(lectura, plan_c)
        if args.pagar:
            lectura_p = imp.leer_por_pagar(args.pagar)
            plan_p = imp.planificar_por_pagar(db, lectura_p)
            informe_pagar(lectura_p, plan_p, lectura_p_nombres(lectura_p))

        if not args.aplicar:
            print("\nNo se guardó nada. Si el informe está bien, repite el comando con --aplicar.")
            return 0

        _respaldar()
        try:
            resumen = []
            if plan_c:
                resumen.append(f"{imp.aplicar_por_cobrar(db, plan_c)} cuentas por cobrar")
            if plan_p:
                facturas, proveedores = imp.aplicar_por_pagar(db, plan_p)
                resumen.append(f"{facturas} facturas de proveedor ({proveedores} proveedores nuevos)")
            db.commit()
        except Exception:
            db.rollback()
            print("\nError: no se guardó nada.")
            raise
        print("\nGuardado: " + " y ".join(resumen) + ".")
    return 0


def lectura_p_nombres(lectura: imp.Lectura) -> dict[str, str]:
    """Nombre en la planilla → nombre unificado, de las facturas leídas."""
    return {f.proveedor_planilla: f.proveedor for f in lectura.items}


def _respaldar() -> None:
    from scripts.respaldar import respaldar

    try:
        archivo = respaldar()
    except BaseException as e:  # sin respaldo no se toca la base
        raise SystemExit(f"No se pudo hacer el respaldo previo ({e}). No se guardó nada.")
    print(f"\nRespaldo previo: {archivo}")


if __name__ == "__main__":
    sys.exit(main())

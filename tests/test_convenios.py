"""Sin base de datos: qué entra en cada convenio. Los nombres son de la planilla
del sistema antiguo."""
from src.convenios import descuento, recategorizar


def test_cada_convenio_descuenta_solo_lo_suyo():
    """Gremio: aceite de motor y filtros de aceite, aire y polen. Flyer: eso más
    los de combustible. El servicio va sin categoría y no entra en ninguno."""
    orden = [("Aceite motor", 40000), ("Filtro aceite", 10000), ("Filtro Petroleo", 20000),
             ("FILTRO", 5000), (None, 15000), ("Plumillas", 8000)]
    assert descuento("GREMIO", orden) == 7500      # 15 % de 50.000
    assert descuento("FLYER", orden) == 7500       # 10 % de 75.000
    assert descuento("FLYER", [(None, 15000)]) == 0


def test_la_categoria_generica_se_saca_del_nombre():
    assert recategorizar("FILTRO", "F. Polen Kia Morning 1.0/1.2 CU 18009") == "Filtro Polen"
    assert recategorizar("FILTRO", "Filtro de Aire SCT C 2324") == "Filtro aire"
    assert recategorizar("FILTRO", "Filtro Aceite OS 2120 (W 7041 - W 713/1)") == "Filtro aceite"
    assert recategorizar("FILTRO", "FILTRO PETROLEO WK 854/6 - WK 854/4") == "Filtro Petroleo"
    assert recategorizar("ACEITES", "Aceite 5w30 Senfineco 4Lts") == "Aceite motor"
    assert recategorizar("ACEITES", "SAE 40 A GRANEL TAMBOR 205L") == "Aceite motor"

    # Sin tipo en el nombre, o con dos, se deja: adivinar es peor que no saber.
    assert recategorizar("FILTRO", "Filtro Combustible WK 818/80") is None
    assert recategorizar("FILTRO", "Pack Filtros Nissan NP300 2.3 Diesel 2016 - 2024") is None
    # 75W90 tiene forma de viscosidad de motor, pero es de caja.
    assert recategorizar("ACEITES", "ACEITE  75w90 GL4-GL5 LS GEARPLUS") is None
    assert recategorizar("ACEITES", "MULTI ATF MOTUL 1L 100% Sintetico") is None
    # Una categoría que ya es específica no se toca.
    assert recategorizar("Filtro aire", "Filtro Polen CU 24027") is None

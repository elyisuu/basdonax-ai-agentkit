"""Pruebas de textos_panel.py — los textos fijos de /estadisticas y
/reservas/{accion} en los tres idiomas de IDIOMA_PANEL. No gastan un solo
token ni salen a internet.

    pytest
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agente.config import IDIOMAS_PANEL  # noqa: E402
from agente.web.textos_panel import TEXTOS, t  # noqa: E402


def test_los_tres_idiomas_de_config_tienen_diccionario_de_textos():
    assert set(IDIOMAS_PANEL) == set(TEXTOS.keys())


def test_los_tres_idiomas_tienen_exactamente_las_mismas_claves():
    """Si se agrega una clave nueva a un idioma y no a los otros dos, la
    página no revienta (t() cae a español) pero queda mostrando español a
    medias en un panel que se pidió en otro idioma — mejor que este test
    lo marque enseguida."""
    claves_es = set(TEXTOS["es"].keys())
    for idioma in IDIOMAS_PANEL:
        assert set(TEXTOS[idioma].keys()) == claves_es, (
            f"'{idioma}' tiene claves distintas de 'es'"
        )


def test_ninguna_traduccion_queda_vacia():
    for idioma, textos in TEXTOS.items():
        for clave, texto in textos.items():
            assert texto.strip(), f"'{clave}' en '{idioma}' está vacío"


def test_t_devuelve_el_texto_del_idioma_pedido():
    assert t("pt", "listo_titulo") == "Pronto"
    assert t("en", "listo_titulo") == "Done"
    assert t("es", "listo_titulo") == "Listo"


def test_t_con_idioma_desconocido_cae_a_espanol():
    assert t("fr", "listo_titulo") == t("es", "listo_titulo")


def test_t_formatea_los_placeholders():
    assert t("es", "ayuda_detalle", n=7) == "Últimos 7 turnos, el más reciente primero."
    assert t("en", "algo_fallo", detalle="boom") == "Something went wrong: boom"

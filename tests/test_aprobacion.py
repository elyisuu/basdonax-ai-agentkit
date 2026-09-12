"""Pruebas de los links de aprobar/rechazar una reserva. No salen a internet.

    pytest
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agente import aprobacion  # noqa: E402


def test_el_link_trae_conversacion_evento_y_token():
    url = aprobacion.link("https://negocio.com", "42", "evento-1", "secreto", "aprobar")

    assert url.startswith("https://negocio.com/reservas/aprobar/42/evento-1?token=")


def test_la_barra_final_de_url_publica_no_se_duplica():
    url = aprobacion.link("https://negocio.com/", "42", "evento-1", "secreto", "aprobar")
    assert "//reservas" not in url


def test_una_accion_que_no_existe_explota():
    with pytest.raises(ValueError, match="aprobar"):
        aprobacion.link("https://negocio.com", "42", "evento-1", "secreto", "borrar")


def test_el_token_del_link_es_valido():
    url = aprobacion.link("https://negocio.com", "42", "evento-1", "secreto", "aprobar")
    token = url.rsplit("token=", 1)[1]

    assert aprobacion.valido("secreto", "42", "evento-1", token) is True


def test_un_token_de_otra_reserva_no_sirve():
    """La firma es por reserva puntual: no vale para aprobar cualquier otra."""
    url = aprobacion.link("https://negocio.com", "42", "evento-1", "secreto", "aprobar")
    token = url.rsplit("token=", 1)[1]

    assert aprobacion.valido("secreto", "42", "evento-2", token) is False
    assert aprobacion.valido("secreto", "99", "evento-1", token) is False


def test_un_secreto_equivocado_no_sirve():
    url = aprobacion.link("https://negocio.com", "42", "evento-1", "secreto", "aprobar")
    token = url.rsplit("token=", 1)[1]

    assert aprobacion.valido("otro-secreto", "42", "evento-1", token) is False


def test_sin_secreto_o_sin_token_nunca_es_valido():
    assert aprobacion.valido("", "42", "evento-1", "cualquier-cosa") is False
    assert aprobacion.valido("secreto", "42", "evento-1", "") is False


# -- Varios profesionales: el link también firma el profesional ---------------------
#
# Fase 4 (ver AGENTS.md, "Varios profesionales"): con PROFESIONALES
# configurado, la ruta de aprobación necesita saber en qué agenda buscar el
# evento — nadie puede tomar un link válido y cambiarle el profesional de
# la URL para que apunte a otra agenda.


def test_el_link_con_profesional_lo_suma_a_la_url():
    url = aprobacion.link(
        "https://negocio.com", "42", "evento-1", "secreto", "aprobar", "Dra. García"
    )

    assert "/reservas/aprobar/42/evento-1?token=" in url
    assert "profesional=Dra" in url  # urllib.parse.quote codifica el resto


def test_el_link_sin_profesional_no_suma_el_parametro():
    """Un solo profesional (o ninguno): el link es idéntico al de siempre."""
    url = aprobacion.link("https://negocio.com", "42", "evento-1", "secreto", "aprobar")

    assert "profesional=" not in url


def test_el_token_incluye_el_profesional_en_la_firma():
    """El mismo secreto/conversación/evento, con otro profesional, firma
    distinto — así no se puede cambiar el profesional en la URL de un link
    ya emitido."""
    token_garcia = aprobacion.firmar("secreto", "42", "evento-1", "Dra. García")
    token_perez = aprobacion.firmar("secreto", "42", "evento-1", "Dr. Pérez")
    token_legacy = aprobacion.firmar("secreto", "42", "evento-1")

    assert token_garcia != token_perez != token_legacy


def test_valido_exige_el_mismo_profesional_con_el_que_se_firmo():
    token = aprobacion.firmar("secreto", "42", "evento-1", "Dra. García")

    assert aprobacion.valido("secreto", "42", "evento-1", token, "Dra. García") is True
    assert aprobacion.valido("secreto", "42", "evento-1", token, "Dr. Pérez") is False
    assert aprobacion.valido("secreto", "42", "evento-1", token) is False, (
        "sin profesional en la validación es un profesional distinto (vacío), "
        "no tiene que colar"
    )

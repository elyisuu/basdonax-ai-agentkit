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

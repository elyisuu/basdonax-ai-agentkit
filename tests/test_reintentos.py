"""Pruebas de los reintentos con backoff. No salen a internet ni esperan de
verdad (se pisa time.sleep).

    pytest
"""

from __future__ import annotations

import io
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agente import reintentos  # noqa: E402


@pytest.fixture(autouse=True)
def _sin_esperar(monkeypatch):
    """Los tests no tienen por qué tardar lo que tardaría el backoff real."""
    monkeypatch.setattr(reintentos.time, "sleep", lambda segundos: None)


def _http_error(codigo: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "url", codigo, "mensaje", hdrs=None, fp=io.BytesIO(b"{}")
    )


def test_si_funciona_a_la_primera_no_reintenta():
    llamadas = []

    def llamada():
        llamadas.append(1)
        return "ok"

    assert reintentos.con_reintentos(llamada) == "ok"
    assert len(llamadas) == 1


def test_un_error_de_red_se_reintenta_hasta_que_funciona():
    llamadas = []

    def llamada():
        llamadas.append(1)
        if len(llamadas) < 3:
            raise urllib.error.URLError("conexión rechazada")
        return "ok"

    assert reintentos.con_reintentos(llamada) == "ok"
    assert len(llamadas) == 3


def test_un_500_se_reintenta():
    llamadas = []

    def llamada():
        llamadas.append(1)
        if len(llamadas) < 2:
            raise _http_error(500)
        return "ok"

    assert reintentos.con_reintentos(llamada) == "ok"
    assert len(llamadas) == 2


def test_un_404_no_se_reintenta():
    """Un 4xx da el mismo error las tres veces: insistir no lo arregla."""
    llamadas = []

    def llamada():
        llamadas.append(1)
        raise _http_error(404)

    with pytest.raises(urllib.error.HTTPError) as info:
        reintentos.con_reintentos(llamada)

    assert info.value.code == 404
    assert len(llamadas) == 1, "un 4xx no se reintenta"


def test_si_se_agotan_los_intentos_sube_el_ultimo_error():
    llamadas = []

    def llamada():
        llamadas.append(1)
        raise urllib.error.URLError("conexión rechazada")

    with pytest.raises(urllib.error.URLError):
        reintentos.con_reintentos(llamada)

    assert len(llamadas) == reintentos.INTENTOS


def test_el_backoff_se_va_duplicando(monkeypatch):
    esperas = []
    monkeypatch.setattr(reintentos.time, "sleep", lambda segundos: esperas.append(segundos))

    def llamada():
        raise urllib.error.URLError("conexión rechazada")

    with pytest.raises(urllib.error.URLError):
        reintentos.con_reintentos(llamada)

    assert esperas == [
        reintentos.ESPERA_INICIAL,
        reintentos.ESPERA_INICIAL * 2,
    ]

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


def _http_error(codigo: int, cuerpo: bytes = b"{}") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "url", codigo, "mensaje", hdrs=None, fp=io.BytesIO(cuerpo)
    )


def _cuerpo_de_cuota(razon: str) -> bytes:
    """El formato real que devolvió Google Calendar (ver reintentos.py)."""
    return (
        b'{"error": {"errors": [{"domain": "usageLimits", "reason": "'
        + razon.encode()
        + b'", "message": "Rate Limit Exceeded"}], "code": 403}}'
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


def test_un_403_de_rate_limit_de_google_se_reintenta():
    """Reproducido en producción: Calendar devolvió justo este 403 al
    aprobar una reserva por link. Es un 4xx, pero para ESTE motivo Google
    pide reintentar con backoff — ver el docstring de reintentos.py."""
    llamadas = []

    def llamada():
        llamadas.append(1)
        if len(llamadas) < 2:
            raise _http_error(403, _cuerpo_de_cuota("rateLimitExceeded"))
        return "ok"

    assert reintentos.con_reintentos(llamada) == "ok"
    assert len(llamadas) == 2


def test_un_403_de_user_rate_limit_tambien_se_reintenta():
    llamadas = []

    def llamada():
        llamadas.append(1)
        if len(llamadas) < 2:
            raise _http_error(403, _cuerpo_de_cuota("userRateLimitExceeded"))
        return "ok"

    assert reintentos.con_reintentos(llamada) == "ok"
    assert len(llamadas) == 2


def test_un_403_que_no_es_de_cuota_no_se_reintenta():
    """Permisos, cuenta de servicio sin acceso, etc.: insistir no arregla nada."""
    llamadas = []

    def llamada():
        llamadas.append(1)
        raise _http_error(
            403,
            b'{"error": {"errors": [{"domain": "global", "reason": '
            b'"insufficientPermissions", "message": "no autorizado"}]}}',
        )

    with pytest.raises(urllib.error.HTTPError) as info:
        reintentos.con_reintentos(llamada)

    assert info.value.code == 403
    assert len(llamadas) == 1


def test_un_403_sin_cuerpo_json_no_se_reintenta():
    """Un 403 de una API que no habla el formato de error de Google (por
    ejemplo Chatwoot) no debe reintentarse solo porque es un 403."""
    llamadas = []

    def llamada():
        llamadas.append(1)
        raise _http_error(403, b"no autorizado")

    with pytest.raises(urllib.error.HTTPError):
        reintentos.con_reintentos(llamada)

    assert len(llamadas) == 1


def test_el_cuerpo_del_error_se_puede_seguir_leyendo_despues(monkeypatch):
    """calendario.py y chatwoot.py hacen `e.read()` en su propio except para
    armar el mensaje de error — tiene que seguir funcionando después de que
    con_reintentos ya miró el cuerpo para decidir si reintentar."""

    def llamada():
        raise _http_error(404, b'{"detalle": "no existe"}')

    with pytest.raises(urllib.error.HTTPError) as info:
        reintentos.con_reintentos(llamada)

    assert info.value.read() == b'{"detalle": "no existe"}'


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

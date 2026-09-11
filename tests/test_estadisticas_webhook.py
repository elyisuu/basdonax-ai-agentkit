"""Pruebas de /estadisticas: el link con estadísticas para el dueño del
negocio (turnos por mes, nuevos vs. recurrentes). No salen a internet ni
gastan tokens.

    pytest
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agente.web import webhook as webhook_modulo  # noqa: E402

from test_agente import agente_falso  # noqa: E402
from test_chatwoot import ChatwootFalso, cliente  # noqa: E402


def _armar(dashboard_secreto="shhh-stats"):
    canal = ChatwootFalso()
    agente = agente_falso(["no debería usarse"])
    agente.config.dashboard_secreto = dashboard_secreto

    web = cliente(canal, agente)
    return web, agente


def test_sin_token_da_404():
    web, _ = _armar()

    with web as w:
        respuesta = w.get("/estadisticas")

    assert respuesta.status_code == 404


def test_con_token_equivocado_da_404():
    web, _ = _armar()

    with web as w:
        respuesta = w.get("/estadisticas?token=no-es-este")

    assert respuesta.status_code == 404


def test_sin_dashboard_secreto_configurado_da_404():
    """Aunque alguien adivine un token, sin DASHBOARD_SECRETO puesto no hay
    nada que pueda coincidir — mismo criterio que /reservas sin RESERVA_SECRETO."""
    web, _ = _armar(dashboard_secreto="")

    with web as w:
        respuesta = w.get("/estadisticas?token=")

    assert respuesta.status_code == 404


def test_con_token_correcto_y_sin_datos_lo_avisa(monkeypatch):
    web, _ = _armar()
    monkeypatch.setattr(webhook_modulo.visitas, "resumen_mensual", lambda dsn: [])

    with web as w:
        respuesta = w.get("/estadisticas?token=shhh-stats")

    assert respuesta.status_code == 200
    assert "Todavía no hay turnos" in respuesta.text


def test_con_token_correcto_muestra_las_filas(monkeypatch):
    web, _ = _armar()
    monkeypatch.setattr(
        webhook_modulo.visitas,
        "resumen_mensual",
        lambda dsn: [
            {"mes": "2026-09", "turnos": 12, "nuevos": 5, "recurrentes": 7},
            {"mes": "2026-08", "turnos": 8, "nuevos": 3, "recurrentes": 5},
        ],
    )

    with web as w:
        respuesta = w.get("/estadisticas?token=shhh-stats")

    assert respuesta.status_code == 200
    assert "2026-09" in respuesta.text
    assert "<td>12</td>" in respuesta.text
    assert "2026-08" in respuesta.text


def test_si_la_consulta_falla_muestra_el_error_en_vez_de_reventar(monkeypatch):
    def _explota(dsn):
        raise RuntimeError("Postgres no contesta")

    web, _ = _armar()
    monkeypatch.setattr(webhook_modulo.visitas, "resumen_mensual", _explota)

    with web as w:
        respuesta = w.get("/estadisticas?token=shhh-stats")

    assert respuesta.status_code == 500
    assert "RuntimeError" in respuesta.text

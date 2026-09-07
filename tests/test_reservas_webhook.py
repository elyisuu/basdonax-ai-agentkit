"""Pruebas de /reservas/{aprobar|rechazar}: el link que abre el negocio para
resolver una reserva "tentative" (RESERVA_REQUIERE_APROBACION). No salen a
internet ni gastan tokens.

    pytest
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agente import aprobacion  # noqa: E402

from test_agente import agente_falso  # noqa: E402
from test_chatwoot import ChatwootFalso, cliente  # noqa: E402


class _CalendarioDeMentira:
    """Alcanza con estos dos métodos: son los únicos que usa la ruta."""

    def __init__(self) -> None:
        self.aprobados: list[str] = []
        self.cancelados: list[str] = []

    def aprobar_evento(self, evento_id):
        self.aprobados.append(evento_id)

    def cancelar_evento(self, evento_id):
        self.cancelados.append(evento_id)


def _armar(secreto="shhh"):
    """Un cliente de pruebas con Chatwoot y calendario de mentira adentro."""
    canal = ChatwootFalso()
    calendario = _CalendarioDeMentira()
    agente = agente_falso(["no debería usarse"])
    agente.config.reserva_secreto = secreto

    web = cliente(canal, agente, calendario=calendario)
    return web, canal, calendario


def _etiqueta_puesta(canal) -> str | None:
    """La última etiqueta que se mandó a poner (el POST a /labels)."""
    pedidos = [
        l["datos"]["labels"]
        for l in canal.llamadas
        if l["camino"].endswith("/labels") and l["metodo"] == "POST"
    ]
    return pedidos[-1][0] if pedidos else None


def test_aprobar_con_token_valido_confirma_y_avisa():
    web, canal, calendario = _armar()
    token = aprobacion.firmar("shhh", "42", "evento-1")

    with web as w:
        respuesta = w.get(f"/reservas/aprobar/42/evento-1?token={token}")

    assert respuesta.status_code == 200
    assert calendario.aprobados == ["evento-1"]
    assert "confirmado" in canal.envios()[0].lower()
    assert _etiqueta_puesta(canal) == "reserva-confirmada"


def test_rechazar_con_token_valido_cancela_y_avisa():
    web, canal, calendario = _armar()
    token = aprobacion.firmar("shhh", "42", "evento-1")

    with web as w:
        respuesta = w.get(f"/reservas/rechazar/42/evento-1?token={token}")

    assert respuesta.status_code == 200
    assert calendario.cancelados == ["evento-1"]
    assert "no vamos a poder" in canal.envios()[0].lower()
    assert _etiqueta_puesta(canal) == "reserva-rechazada"


def test_token_invalido_no_hace_nada():
    web, canal, calendario = _armar()

    with web as w:
        respuesta = w.get("/reservas/aprobar/42/evento-1?token=cualquier-cosa")

    assert respuesta.status_code == 403
    assert calendario.aprobados == []
    assert canal.envios() == []


def test_token_de_otra_reserva_no_sirve():
    """La firma es por reserva puntual, no genérica."""
    web, canal, calendario = _armar()
    token = aprobacion.firmar("shhh", "42", "evento-1")

    with web as w:
        respuesta = w.get(f"/reservas/aprobar/42/evento-2?token={token}")

    assert respuesta.status_code == 403
    assert calendario.aprobados == []


def test_accion_desconocida_da_404():
    web, canal, calendario = _armar()
    token = aprobacion.firmar("shhh", "42", "evento-1")

    with web as w:
        respuesta = w.get(f"/reservas/borrar/42/evento-1?token={token}")

    assert respuesta.status_code == 404


def test_sin_calendario_conectado_da_404():
    canal = ChatwootFalso()
    agente = agente_falso(["no debería usarse"])
    agente.config.reserva_secreto = "shhh"

    with cliente(canal, agente, calendario=None) as w:
        token = aprobacion.firmar("shhh", "42", "evento-1")
        respuesta = w.get(f"/reservas/aprobar/42/evento-1?token={token}")

    assert respuesta.status_code == 404


def test_sin_reserva_secreto_configurado_da_404():
    web, canal, calendario = _armar(secreto="")

    with web as w:
        respuesta = w.get("/reservas/aprobar/42/evento-1?token=algo")

    assert respuesta.status_code == 404
    assert calendario.aprobados == []

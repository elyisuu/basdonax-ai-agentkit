"""Pruebas de la lógica de recordatorios.py (las funciones puras, sin tocar
Calendar ni Chatwoot de verdad).

    pytest
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from recordatorios import conversacion_del_evento, deberia_avisar  # noqa: E402


def _evento(status="confirmed", descripcion="Nombre: Juan\nConversación: 42", recordado=False):
    evento = {"status": status, "description": descripcion}
    if recordado:
        evento["extendedProperties"] = {"private": {"recordatorio_enviado": "true"}}
    return evento


# -- conversacion_del_evento ---------------------------------------------------------


def test_conversacion_del_evento_la_encuentra():
    assert conversacion_del_evento(_evento()) == "42"


def test_conversacion_del_evento_no_le_importa_la_tilde():
    assert conversacion_del_evento({"description": "Conversacion: 7"}) == "7"


def test_conversacion_del_evento_sin_esa_linea_es_none():
    assert conversacion_del_evento({"description": "Nombre: Juan"}) is None


def test_conversacion_del_evento_sin_descripcion_es_none():
    assert conversacion_del_evento({}) is None


# -- deberia_avisar -------------------------------------------------------------------


def test_deberia_avisar_un_turno_confirmado_sin_avisar():
    assert deberia_avisar(_evento()) is True


def test_no_deberia_avisar_un_turno_tentative():
    """Todavía puede rechazarse — avisarle a la persona sería confuso."""
    assert deberia_avisar(_evento(status="tentative")) is False


def test_no_deberia_avisar_dos_veces():
    assert deberia_avisar(_evento(recordado=True)) is False


def test_no_deberia_avisar_sin_conversacion():
    """Un turno cargado a mano en Calendar, sin la línea que deja anotar_reserva()."""
    assert deberia_avisar(_evento(descripcion="Nombre: Juan")) is False

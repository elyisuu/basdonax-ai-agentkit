"""Pruebas de la lógica de recordatorios.py (las funciones puras, sin tocar
Calendar ni Chatwoot de verdad).

    pytest
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import recordatorios  # noqa: E402
from agente.config import Config  # noqa: E402
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


# -- _calendarios: varios profesionales, cada uno con su propia agenda --------------
#
# Fase 3 (ver AGENTS.md, "Varios profesionales"): antes, este programa solo
# barría GOOGLE_CALENDAR_ID. `Calendario` de verdad necesita una clave RSA
# real en credencial_json (firma el JWT al construirse) — se reemplaza acá
# por una clase de mentira que solo anota con qué se la construyó, mismo
# criterio que _construir_calendario en test_herramientas.py.


class _CalendarioDeMentira:
    def __init__(self, calendario_id, credencial_json, zona_horaria) -> None:
        self.calendario_id = calendario_id
        self.credencial_json = credencial_json
        self.zona_horaria = zona_horaria


def _config(**cambios) -> Config:
    """Un Config real, con los campos obligatorios (los del modelo, que acá
    no importan para nada) rellenados con cualquier cosa."""
    return Config(
        proveedor="claude",
        modelo="modelo-de-prueba",
        api_key="no-hace-falta",
        max_tokens=1024,
        memoria_mensajes=20,
        prompt_sistema=Path("prompts/sistema.md"),
        **cambios,
    )


def test_calendarios_sin_credencial_da_lista_vacia(monkeypatch):
    monkeypatch.setattr(recordatorios, "Calendario", _CalendarioDeMentira)
    config = _config(google_calendar_id="abc", google_service_account_json="")

    assert recordatorios._calendarios(config) == []


def test_calendarios_sin_profesionales_ni_calendar_id_da_lista_vacia(monkeypatch):
    monkeypatch.setattr(recordatorios, "Calendario", _CalendarioDeMentira)
    config = _config(google_service_account_json="cuenta-de-mentira")

    assert recordatorios._calendarios(config) == []


def test_calendarios_sin_profesionales_usa_google_calendar_id(monkeypatch):
    monkeypatch.setattr(recordatorios, "Calendario", _CalendarioDeMentira)
    config = _config(
        google_calendar_id="abc@group.calendar.google.com",
        google_service_account_json="cuenta-de-mentira",
    )

    resultado = recordatorios._calendarios(config)

    assert [c.calendario_id for c in resultado] == ["abc@group.calendar.google.com"]


def test_calendarios_con_profesionales_arma_uno_por_cada_agenda(monkeypatch):
    monkeypatch.setattr(recordatorios, "Calendario", _CalendarioDeMentira)
    config = _config(
        profesionales={"Dra. García": "cal-garcia", "Dr. Pérez": "cal-perez"},
        google_service_account_json="cuenta-de-mentira",
        zona_horaria="Europe/Lisbon",
    )

    resultado = recordatorios._calendarios(config)

    assert [c.calendario_id for c in resultado] == ["cal-garcia", "cal-perez"]
    assert all(c.zona_horaria == "Europe/Lisbon" for c in resultado)

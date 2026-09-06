"""Pruebas de la elección de modelo. No tocan internet."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agente.modelos import _tope_de  # noqa: E402

LISTA = [
    {"id": "claude-opus-5", "max_salida": 128000},
    {"id": "claude-haiku-4-5-20251001", "max_salida": 64000},
    {"id": "gpt-5", "max_salida": None},
]


def test_encuentra_el_tope_exacto():
    assert _tope_de(LISTA, "claude-opus-5") == 128000


def test_encuentra_el_tope_del_alias_corto():
    """El .env dice el alias; el proveedor publica el id con fecha."""
    assert _tope_de(LISTA, "claude-haiku-4-5") == 64000


def test_encuentra_el_tope_del_id_con_fecha():
    assert _tope_de(LISTA, "claude-haiku-4-5-20251001") == 64000


def test_sin_tope_informado_devuelve_none():
    assert _tope_de(LISTA, "gpt-5") is None


def test_modelo_desconocido_devuelve_none():
    assert _tope_de(LISTA, "un-modelo-que-no-existe") is None


def test_claude_pide_que_se_tiren_los_bloques_de_pensamiento_viejos(monkeypatch):
    """Sin esto, cambiar HERRAMIENTAS rompe para siempre cualquier
    conversación vieja: Anthropic firma el `thinking` contra la lista de
    herramientas del momento, y al cambiar esa lista el próximo mensaje
    devuelve un 400 ("Invalid signature... tools list differs") en vez de
    contestar. `drop_block` es el arreglo que sugiere el propio error."""
    import agente.modelos as m

    monkeypatch.setattr(m, "listar_modelos", lambda p, k: [])

    modelo = m.crear_modelo("claude", "clave-falsa", "claude-fable-5-1", 4096)

    assert modelo.thinking["block_binding"]["prefix_mismatch_behavior"] == "drop_block"
    assert "thinking-binding-controls-2026-08-01" in modelo.betas


def test_limitar_recorta_solo_si_hace_falta(monkeypatch):
    import agente.modelos as m

    monkeypatch.setattr(m, "listar_modelos", lambda p, k: LISTA)

    # Se pasa del tope: recorta
    assert m.limitar_max_tokens("claude", "x", "claude-haiku-4-5", 128000) == 64000
    # Entra holgado: lo deja
    assert m.limitar_max_tokens("claude", "x", "claude-haiku-4-5", 2048) == 2048
    # El proveedor no informa el tope: lo deja
    assert m.limitar_max_tokens("claude", "x", "gpt-5", 999999) == 999999

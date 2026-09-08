"""Pruebas de las alertas al dueño del bot. No salen a internet.

    pytest
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agente import alertas  # noqa: E402


def test_sin_token_no_hace_nada(monkeypatch):
    llamado = []
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: llamado.append(1))

    alertas.avisar("", "123", "clave", "texto")
    alertas.avisar("token", "", "clave", "texto")

    assert llamado == [], "sin las dos variables no tiene que pegarle a Telegram"


def test_con_las_dos_manda_el_mensaje(monkeypatch):
    pedidos = []

    def urlopen(pedido, timeout):
        pedidos.append(pedido)

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    alertas.avisar("token", "123", "clave-nueva", "algo se rompió")

    assert len(pedidos) == 1
    assert "token" in pedidos[0].full_url
    assert b"algo se rompi" in pedidos[0].data  # sin acentos: json.dumps escapa la o'


def test_la_misma_alerta_no_se_repite_antes_del_cooldown(monkeypatch):
    pedidos = []
    monkeypatch.setattr("urllib.request.urlopen", lambda p, timeout: pedidos.append(p))

    alertas.avisar("token", "123", "clave-repetida", "primera")
    alertas.avisar("token", "123", "clave-repetida", "segunda, todavía en cooldown")

    assert len(pedidos) == 1, "la segunda tendría que haberse frenado por el cooldown"


def test_alertas_distintas_no_se_pisan(monkeypatch):
    pedidos = []
    monkeypatch.setattr("urllib.request.urlopen", lambda p, timeout: pedidos.append(p))

    alertas.avisar("token", "123", "clave-a", "una falla")
    alertas.avisar("token", "123", "clave-b", "otra falla distinta")

    assert len(pedidos) == 2


def test_si_telegram_falla_no_revienta(monkeypatch):
    def explota(*a, **k):
        raise OSError("Telegram no contesta")

    monkeypatch.setattr("urllib.request.urlopen", explota)

    # No tiene que levantar nada: quien la llama (webhook.py) no puede
    # caerse porque la ALERTA falló, solo porque falló lo que la disparó.
    alertas.avisar("token", "123", "clave-que-explota", "texto")

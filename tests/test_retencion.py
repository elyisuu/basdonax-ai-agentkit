"""Pruebas de retencion.py — el borrado por política de retención (2 años
por default). No sale a internet, no gasta tokens, no toca ninguna
Postgres ni Chatwoot de verdad: todo lo que habla con esos dos se
reemplaza por versiones de mentira.

    pytest
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import retencion  # noqa: E402
from agente.config import Config  # noqa: E402


def _config(**cambios) -> Config:
    """Un Config real con los campos obligatorios (los del modelo, que acá
    no importan) rellenados con cualquier cosa."""
    return Config(
        proveedor="claude",
        modelo="modelo-de-prueba",
        api_key="no-hace-falta",
        max_tokens=1024,
        memoria_mensajes=20,
        prompt_sistema=Path("prompts/sistema.md"),
        **cambios,
    )


AHORA = datetime(2026, 9, 12, tzinfo=timezone.utc)
CORTE = AHORA - timedelta(days=retencion.RETENCION_DIAS)


def _hace(dias: int) -> str:
    """Un timestamp ISO de hace `dias` días, para armar checkpoints de
    prueba viejos o nuevos relativo al corte."""
    return (AHORA - timedelta(days=dias)).isoformat()


# -- _fecha_de_nota -------------------------------------------------------------


def test_fecha_de_nota_desde_timestamp_unix():
    fecha = retencion._fecha_de_nota({"created_at": 1700000000})
    assert fecha == datetime.fromtimestamp(1700000000, tz=timezone.utc)


def test_fecha_de_nota_desde_iso_string():
    fecha = retencion._fecha_de_nota({"created_at": "2024-01-15T10:00:00Z"})
    assert fecha == datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)


def test_fecha_de_nota_sin_created_at_es_none():
    assert retencion._fecha_de_nota({}) is None


def test_fecha_de_nota_valor_invalido_es_none():
    assert retencion._fecha_de_nota({"created_at": "esto no es una fecha"}) is None


# -- _conversaciones (memoria de LangGraph) --------------------------------------


class _SaverDeMentira:
    """Se hace pasar por el PostgresSaver que arma memoria.postgres()."""

    def __init__(self, tuplas: list) -> None:
        self._tuplas = tuplas
        self.hilos_borrados: list[str] = []
        self.conn = SimpleNamespace(close=lambda: setattr(self, "cerrado", True))
        self.cerrado = False

    def list(self, config):
        return iter(self._tuplas)

    def delete_thread(self, thread_id: str) -> None:
        self.hilos_borrados.append(thread_id)


def _tupla(thread_id: str, ts: str):
    return SimpleNamespace(config={"configurable": {"thread_id": thread_id}}, checkpoint={"ts": ts})


def test_conversaciones_sin_dsn_no_hace_nada(monkeypatch, capsys):
    llamado = []
    monkeypatch.setattr(retencion.memoria, "postgres", lambda dsn: llamado.append(dsn))

    retencion._conversaciones(_config(), CORTE.isoformat(), aplicar=True)

    assert llamado == []


def test_conversaciones_modo_de_prueba_no_borra_nada(monkeypatch):
    saver = _SaverDeMentira([_tupla("1", _hace(800))])  # vencida (más de 730 días)
    monkeypatch.setattr(retencion.memoria, "postgres", lambda dsn: saver)

    retencion._conversaciones(_config(postgres_dsn="dsn-falso"), CORTE.isoformat(), aplicar=False)

    assert saver.hilos_borrados == []
    assert saver.cerrado is True, "el pool se cierra igual, aunque no se borre nada"


def test_conversaciones_aplicar_borra_solo_las_vencidas(monkeypatch):
    saver = _SaverDeMentira(
        [
            _tupla("vieja", _hace(800)),  # vencida
            _tupla("nueva", _hace(10)),  # vigente
        ]
    )
    monkeypatch.setattr(retencion.memoria, "postgres", lambda dsn: saver)

    retencion._conversaciones(_config(postgres_dsn="dsn-falso"), CORTE.isoformat(), aplicar=True)

    assert saver.hilos_borrados == ["vieja"]


def test_conversaciones_usa_el_checkpoint_mas_reciente_por_hilo(monkeypatch):
    """Un hilo con un checkpoint viejo Y uno nuevo no está vencido — lo que
    importa es la ÚLTIMA actividad, no la primera."""
    saver = _SaverDeMentira(
        [
            _tupla("1", _hace(800)),  # el primer checkpoint, viejo
            _tupla("1", _hace(5)),  # el último, reciente
        ]
    )
    monkeypatch.setattr(retencion.memoria, "postgres", lambda dsn: saver)

    retencion._conversaciones(_config(postgres_dsn="dsn-falso"), CORTE.isoformat(), aplicar=True)

    assert saver.hilos_borrados == []


# -- _visitas ---------------------------------------------------------------------


def test_visitas_sin_dsn_no_hace_nada(monkeypatch):
    llamado = []
    monkeypatch.setattr(retencion.visitas, "borrar_visitas_viejas", lambda *a: llamado.append(a))

    retencion._visitas(_config(), CORTE.date().isoformat(), aplicar=True)

    assert llamado == []


def test_visitas_modo_de_prueba_no_borra_nada(monkeypatch):
    llamado = []
    monkeypatch.setattr(retencion.visitas, "borrar_visitas_viejas", lambda *a: llamado.append(a))

    retencion._visitas(_config(postgres_dsn="dsn-falso"), CORTE.date().isoformat(), aplicar=False)

    assert llamado == []


def test_visitas_aplicar_llama_al_borrado_con_la_fecha_de_corte(monkeypatch):
    llamado = []
    monkeypatch.setattr(
        retencion.visitas, "borrar_visitas_viejas", lambda dsn, corte: llamado.append((dsn, corte))
    )

    retencion._visitas(_config(postgres_dsn="dsn-falso"), "2024-09-12", aplicar=True)

    assert llamado == [("dsn-falso", "2024-09-12")]


# -- _notas_de_contacto -------------------------------------------------------------


class _ChatwootDeMentira:
    def __init__(self, url, token, cuenta_id) -> None:
        self.borradas: list[tuple] = []
        self._contactos_por_pagina = {1: [{"id": "7"}, {"id": "8"}]}
        self._notas_por_contacto = {}

    def listar_contactos(self, pagina):
        return self._contactos_por_pagina.get(pagina, [])

    def listar_notas_contacto(self, contacto_id):
        return self._notas_por_contacto.get(contacto_id, [])

    def borrar_nota_contacto(self, contacto_id, nota_id):
        self.borradas.append((contacto_id, nota_id))


def test_notas_de_contacto_sin_chatwoot_no_hace_nada(monkeypatch):
    llamado = []
    monkeypatch.setattr(retencion, "Chatwoot", lambda **k: llamado.append(k))

    retencion._notas_de_contacto(_config(), CORTE, aplicar=True)

    assert llamado == []


def test_notas_de_contacto_recorre_todos_los_contactos_y_pagina(monkeypatch):
    class ChatwootDeVariasPaginas(_ChatwootDeMentira):
        def __init__(self, url, token, cuenta_id):
            super().__init__(url, token, cuenta_id)
            self._contactos_por_pagina = {1: [{"id": "7"}], 2: [{"id": "8"}], 3: []}
            self._notas_por_contacto = {
                "7": [{"id": "n1", "created_at": _hace(800)}],  # vencida
                "8": [{"id": "n2", "created_at": _hace(5)}],  # vigente
            }

    fake = ChatwootDeVariasPaginas("url", "token", "1")
    monkeypatch.setattr(retencion, "Chatwoot", lambda **k: fake)

    retencion._notas_de_contacto(
        _config(chatwoot_url="https://x.com", chatwoot_token="t"), CORTE, aplicar=True
    )

    assert fake.borradas == [("7", "n1")]


def test_notas_de_contacto_modo_de_prueba_no_borra_nada(monkeypatch):
    fake = _ChatwootDeMentira("url", "token", "1")
    fake._notas_por_contacto = {"7": [{"id": "n1", "created_at": _hace(800)}]}
    monkeypatch.setattr(retencion, "Chatwoot", lambda **k: fake)

    retencion._notas_de_contacto(
        _config(chatwoot_url="https://x.com", chatwoot_token="t"), CORTE, aplicar=False
    )

    assert fake.borradas == []


def test_notas_de_contacto_un_contacto_que_falla_no_corta_el_resto(monkeypatch):
    class ChatwootConUnoRoto(_ChatwootDeMentira):
        def __init__(self, url, token, cuenta_id):
            super().__init__(url, token, cuenta_id)
            self._contactos_por_pagina = {1: [{"id": "7"}, {"id": "8"}]}
            self._notas_por_contacto = {"8": [{"id": "n2", "created_at": _hace(800)}]}

        def listar_notas_contacto(self, contacto_id):
            if contacto_id == "7":
                raise RuntimeError("Chatwoot no contesta")
            return super().listar_notas_contacto(contacto_id)

    fake = ChatwootConUnoRoto("url", "token", "1")
    monkeypatch.setattr(retencion, "Chatwoot", lambda **k: fake)

    retencion._notas_de_contacto(
        _config(chatwoot_url="https://x.com", chatwoot_token="t"), CORTE, aplicar=True
    )

    assert fake.borradas == [("8", "n2")], "el contacto 7 falló, pero el 8 se procesó igual"

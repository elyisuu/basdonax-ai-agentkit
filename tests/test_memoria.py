"""Pruebas de memoria.verificar() — el chequeo real que usa /salud.

No hace falta una Postgres de verdad: se prueba contra una conexión de
mentira, con la misma forma que psycopg_pool.ConnectionPool (un
`.connection(timeout=...)` que es un context manager).

    pytest
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agente.memoria import ram, verificar  # noqa: E402


class _ConexionFalsaSana:
    def execute(self, sql):
        pass


class _PoolFalso:
    """Se hace pasar por psycopg_pool.ConnectionPool: `.connection()` es
    el context manager que entrega una conexión (o revienta, si Postgres
    está inalcanzable — el caso que este chequeo existe para agarrar)."""

    def __init__(self, rompe: bool = False):
        self._rompe = rompe

    def connection(self, timeout=None):
        if self._rompe:
            raise RuntimeError(
                "consuming input failed: server closed the connection unexpectedly"
            )
        return self

    def __enter__(self):
        return _ConexionFalsaSana()

    def __exit__(self, *a):
        return False


class _CheckpointerFalso:
    """`verificar()` decide si hay algo que chequear mirando el módulo de
    la clase — así no hace falta psycopg instalado para probar el caso
    "no es Postgres" (MODO=test, sin esa dependencia)."""

    def __init__(self, pool):
        self.conn = pool


_CheckpointerFalso.__module__ = "langgraph.checkpoint.postgres"


def test_a_una_memoria_que_no_es_postgres_no_le_pregunta_nada():
    """RAM, SQLite: son locales, si el proceso está vivo funcionan."""
    assert verificar(ram()) is None


def test_ok_cuando_la_conexion_funciona():
    assert verificar(_CheckpointerFalso(_PoolFalso(rompe=False))) is None


def test_devuelve_el_motivo_cuando_la_conexion_esta_rota():
    """El caso real de producción: Postgres sano, la conexión cortada."""
    error = verificar(_CheckpointerFalso(_PoolFalso(rompe=True)))

    assert error is not None
    assert "RuntimeError" in error
    assert "server closed the connection" in error

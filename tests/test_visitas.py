"""Pruebas de visitas.py — el registro de turnos confirmados para las
estadísticas del negocio. No hace falta psycopg instalado (se reemplaza
el módulo entero en sys.modules, mismo espíritu que test_memoria.py) ni
una Postgres de verdad, ni sale a internet ni gasta tokens.

    pytest
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agente import visitas  # noqa: E402


class _CursorDeMentira:
    """Lo que devuelve `.execute(...)`: alcanza con `.fetchall()`."""

    def __init__(self, filas: list[tuple]) -> None:
        self._filas = filas

    def fetchall(self):
        return self._filas


class _ConexionDeMentira:
    """Se hace pasar por una conexión de psycopg: `with psycopg.connect(...)`
    entrega esto, y `.execute(sql, params)` anota lo que le pidieron y
    devuelve `filas_a_devolver` (para las consultas que hacen `.fetchall()`,
    como `resumen_mensual`)."""

    def __init__(self, rompe: bool = False, filas_a_devolver: list[tuple] | None = None) -> None:
        self.ejecutados: list[tuple[str, tuple | None]] = []
        self._rompe = rompe
        self._filas = filas_a_devolver or []

    def execute(self, sql, params=None):
        if self._rompe:
            raise RuntimeError("Postgres no contesta")
        self.ejecutados.append((sql, params))
        return _CursorDeMentira(self._filas)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _psycopg_falso(monkeypatch, conexion):
    """Reemplaza sys.modules["psycopg"] por uno de mentira cuyo connect()
    devuelve `conexion` siempre — así `import psycopg` (adentro de
    visitas.py) no necesita el paquete real instalado."""
    modulo = types.SimpleNamespace(connect=lambda dsn, autocommit=True: conexion)
    monkeypatch.setitem(sys.modules, "psycopg", modulo)


# -- Sin DSN: no hace nada, no revienta ----------------------------------------


def test_preparar_sin_dsn_no_hace_nada():
    visitas.preparar("")  # no explota, y no necesita psycopg importable


def test_registrar_sin_dsn_no_hace_nada():
    assert visitas.registrar_visita("", "7", "2026-09-14", "10:00") is False


def test_registrar_sin_contacto_id_no_hace_nada(monkeypatch):
    conexion = _ConexionDeMentira()
    _psycopg_falso(monkeypatch, conexion)

    assert visitas.registrar_visita("dsn-falso", "", "2026-09-14", "10:00") is False
    assert conexion.ejecutados == []  # ni se conectó


# -- Preparar la tabla ----------------------------------------------------------


def test_preparar_crea_la_tabla_y_el_indice(monkeypatch):
    conexion = _ConexionDeMentira()
    _psycopg_falso(monkeypatch, conexion)

    visitas.preparar("dsn-falso")

    assert len(conexion.ejecutados) == 2
    assert "CREATE TABLE" in conexion.ejecutados[0][0]
    assert "visitas" in conexion.ejecutados[0][0]
    assert "CREATE INDEX" in conexion.ejecutados[1][0]


# -- Registrar una visita --------------------------------------------------------


def test_registrar_ejecuta_el_insert_con_los_datos(monkeypatch):
    conexion = _ConexionDeMentira()
    _psycopg_falso(monkeypatch, conexion)

    ok = visitas.registrar_visita(
        "dsn-falso", "7", "2026-09-14", "10:00", telefono="+351900000000", nombre="Ana"
    )

    assert ok is True
    assert len(conexion.ejecutados) == 1
    sql, params = conexion.ejecutados[0]
    assert "INSERT INTO visitas" in sql
    assert params == ("7", "+351900000000", "Ana", "2026-09-14", "10:00")


def test_registrar_sin_telefono_ni_nombre_manda_vacio(monkeypatch):
    conexion = _ConexionDeMentira()
    _psycopg_falso(monkeypatch, conexion)

    visitas.registrar_visita("dsn-falso", "7", "2026-09-14", "10:00")

    _, params = conexion.ejecutados[0]
    assert params == ("7", "", "", "2026-09-14", "10:00")


def test_registrar_si_la_conexion_falla_no_revienta(monkeypatch):
    conexion = _ConexionDeMentira(rompe=True)
    _psycopg_falso(monkeypatch, conexion)

    ok = visitas.registrar_visita("dsn-falso", "7", "2026-09-14", "10:00")

    assert ok is False


# -- El resumen mensual (para /estadisticas) -------------------------------------


def test_resumen_sin_dsn_devuelve_lista_vacia():
    assert visitas.resumen_mensual("") == []


def test_resumen_arma_los_diccionarios_con_las_filas(monkeypatch):
    conexion = _ConexionDeMentira(
        filas_a_devolver=[
            ("2026-09", 12, 5, 7),
            ("2026-08", 8, 3, 5),
        ]
    )
    _psycopg_falso(monkeypatch, conexion)

    resumen = visitas.resumen_mensual("dsn-falso")

    assert resumen == [
        {"mes": "2026-09", "turnos": 12, "nuevos": 5, "recurrentes": 7},
        {"mes": "2026-08", "turnos": 8, "nuevos": 3, "recurrentes": 5},
    ]


def test_resumen_sin_visitas_devuelve_lista_vacia(monkeypatch):
    conexion = _ConexionDeMentira(filas_a_devolver=[])
    _psycopg_falso(monkeypatch, conexion)

    assert visitas.resumen_mensual("dsn-falso") == []


def test_resumen_deja_subir_el_error_de_conexion(monkeypatch):
    """A diferencia de registrar_visita: acá no hay una reserva real que
    proteger, así que /estadisticas puede mostrar el problema."""
    conexion = _ConexionDeMentira(rompe=True)
    _psycopg_falso(monkeypatch, conexion)

    try:
        visitas.resumen_mensual("dsn-falso")
        assert False, "tendría que haber subido la excepción"
    except RuntimeError:
        pass

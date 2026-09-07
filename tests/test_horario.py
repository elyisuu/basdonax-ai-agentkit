"""Pruebas del horario de atención. No salen a internet ni gastan tokens.

    pytest
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agente import horario  # noqa: E402


def test_sin_nada_configurado_no_valida_nada():
    """El default: ningún negocio con horario puesto queda restringido."""
    horario.validar("2026-09-13", "03:00", "", "", "")  # domingo, 3 de la mañana


def test_dias_cerrados_reconoce_nombres_en_castellano():
    assert horario.dias_cerrados("domingo") == {6}
    assert horario.dias_cerrados("lunes, domingo") == {0, 6}
    assert horario.dias_cerrados("Domingo") == {6}, "no distingue mayúsculas"


def test_dias_cerrados_ignora_nombres_que_no_reconoce():
    """Mejor aceptar de más que romper el arranque por un typo en el .env."""
    assert horario.dias_cerrados("lunes, marciano") == {0}
    assert horario.dias_cerrados("") == set()


def test_un_dia_cerrado_explota():
    # 2026-09-13 es domingo.
    with pytest.raises(horario.ErrorDeHorario, match="cerrado"):
        horario.validar("2026-09-13", "12:00", "", "", "domingo")


def test_un_dia_no_cerrado_no_explota():
    # 2026-09-12 es sábado.
    horario.validar("2026-09-12", "12:00", "", "", "domingo")


def test_antes_del_horario_explota():
    with pytest.raises(horario.ErrorDeHorario, match="desde las 09:00"):
        horario.validar("2026-09-12", "08:00", "09:00", "20:00", "")


def test_despues_del_horario_explota():
    with pytest.raises(horario.ErrorDeHorario, match="hasta las 20:00"):
        horario.validar("2026-09-12", "20:30", "09:00", "20:00", "")


def test_justo_en_los_bordes_no_explota():
    horario.validar("2026-09-12", "09:00", "09:00", "20:00", "")
    horario.validar("2026-09-12", "20:00", "09:00", "20:00", "")


def test_solo_desde_sin_hasta():
    horario.validar("2026-09-12", "23:00", "09:00", "", "")

    with pytest.raises(horario.ErrorDeHorario):
        horario.validar("2026-09-12", "05:00", "09:00", "", "")


def test_solo_hasta_sin_desde():
    horario.validar("2026-09-12", "05:00", "", "20:00", "")

    with pytest.raises(horario.ErrorDeHorario):
        horario.validar("2026-09-12", "23:00", "", "20:00", "")

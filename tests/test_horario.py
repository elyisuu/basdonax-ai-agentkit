"""Pruebas del horario de atención. No salen a internet ni gastan tokens.

    pytest
"""

from __future__ import annotations

import sys
from datetime import datetime, time
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


# -- Fecha/hora ya pasada ------------------------------------------------------------


def test_sin_ahora_no_valida_fecha_pasada():
    """El default (ahora=None): nadie lo llamaba con esto hasta ahora, así
    que ningún caller existente empieza a validar esto sin pedirlo."""
    horario.validar("2020-01-01", "10:00")


def test_fecha_pasada_explota():
    ahora = datetime(2026, 9, 12, 10, 0)
    with pytest.raises(horario.ErrorDeHorario, match="ya pasó"):
        horario.validar("2026-09-11", "10:00", ahora=ahora)


def test_hora_pasada_el_mismo_dia_explota():
    ahora = datetime(2026, 9, 12, 10, 0)
    with pytest.raises(horario.ErrorDeHorario, match="ya pasó"):
        horario.validar("2026-09-12", "09:00", ahora=ahora)


def test_hora_futura_el_mismo_dia_no_explota():
    ahora = datetime(2026, 9, 12, 10, 0)
    horario.validar("2026-09-12", "11:00", ahora=ahora)


def test_fecha_futura_no_explota():
    ahora = datetime(2026, 9, 12, 10, 0)
    horario.validar("2026-09-13", "00:00", ahora=ahora)


def test_fecha_pasada_no_le_importa_si_hay_horario_configurado():
    """Rechazar el pasado no depende de HORARIO_DESDE/HASTA: es una regla
    aparte, no una preferencia del negocio."""
    ahora = datetime(2026, 9, 12, 10, 0)
    with pytest.raises(horario.ErrorDeHorario, match="ya pasó"):
        horario.validar("2026-09-11", "12:00", desde="09:00", hasta="20:00", ahora=ahora)


# -- Horario partido (franjas) ------------------------------------------------------


def test_franjas_de_parsea_pares_separados_por_coma():
    assert horario.franjas_de("09:00-15:00, 18:00-23:00") == [
        (time(9, 0), time(15, 0)),
        (time(18, 0), time(23, 0)),
    ]


def test_franjas_de_ignora_lo_que_no_entiende():
    """Mejor una franja menos que romper el arranque por un typo."""
    assert horario.franjas_de("09:00-15:00, esto no es una franja") == [
        (time(9, 0), time(15, 0))
    ]
    assert horario.franjas_de("") == []


def test_dentro_de_alguna_franja_no_explota():
    horario.validar("2026-09-12", "12:00", franjas="09:00-15:00, 18:00-23:00")
    horario.validar("2026-09-12", "20:00", franjas="09:00-15:00, 18:00-23:00")


def test_en_el_corte_entre_franjas_explota():
    with pytest.raises(horario.ErrorDeHorario, match="09:00 a 15:00"):
        horario.validar("2026-09-12", "16:30", franjas="09:00-15:00, 18:00-23:00")


def test_dia_cerrado_reconoce_el_dia():
    # 2026-09-13 es domingo.
    assert horario.dia_cerrado("2026-09-13", "domingo") is True
    assert horario.dia_cerrado("2026-09-12", "domingo") is False


def test_dia_cerrado_sin_nada_configurado():
    assert horario.dia_cerrado("2026-09-13", "") is False


def test_descripcion_con_franjas():
    assert horario.descripcion("", "", "09:00-15:00,18:00-23:00") == (
        "Atiende de 09:00 a 15:00 y 18:00 a 23:00."
    )


def test_descripcion_con_desde_y_hasta():
    assert horario.descripcion("10:00", "22:00", "") == "Atiende de 10:00 a 22:00."


def test_descripcion_solo_desde():
    assert horario.descripcion("10:00", "", "") == "Atiende desde las 10:00."


def test_descripcion_solo_hasta():
    assert horario.descripcion("", "22:00", "") == "Atiende hasta las 22:00."


def test_descripcion_vacia_sin_nada_configurado():
    assert horario.descripcion("", "", "") == ""


def test_franjas_manda_por_sobre_desde_hasta():
    """Si hay franjas puestas, un desde/hasta viejo no interfiere."""
    horario.validar(
        "2026-09-12",
        "20:00",
        desde="00:00",
        hasta="01:00",  # esto solo, sin franjas, rechazaría las 20:00
        franjas="09:00-15:00, 18:00-23:00",
    )

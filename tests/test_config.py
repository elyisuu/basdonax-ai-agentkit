"""Pruebas de config.py — por ahora, solo _profesionales_de(): el parser de
PROFESIONALES (varios profesionales, cada uno con su propia agenda). No
sale a internet ni gasta tokens.

    pytest
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agente.config import _profesionales_de  # noqa: E402


def test_vacio_no_hay_profesionales():
    assert _profesionales_de("") == {}
    assert _profesionales_de("   ") == {}


def test_uno_solo():
    assert _profesionales_de("Dra. García:abc@group.calendar.google.com") == {
        "Dra. García": "abc@group.calendar.google.com"
    }


def test_varios_separados_por_coma():
    texto = "Dra. García:abc@group.calendar.google.com,Dr. Pérez:xyz@group.calendar.google.com"
    assert _profesionales_de(texto) == {
        "Dra. García": "abc@group.calendar.google.com",
        "Dr. Pérez": "xyz@group.calendar.google.com",
    }


def test_espacios_de_mas_no_rompen_nada():
    texto = " Dra. García : abc@group.calendar.google.com , Dr. Pérez:xyz@group.calendar.google.com "
    assert _profesionales_de(texto) == {
        "Dra. García": "abc@group.calendar.google.com",
        "Dr. Pérez": "xyz@group.calendar.google.com",
    }


def test_una_parte_sin_dos_puntos_se_ignora_sin_romper_el_resto():
    """Un typo en una sola entrada no puede tirar abajo el arranque de
    todo el agente — se ignora esa entrada nomás."""
    texto = "Dra. García:abc@group.calendar.google.com,esto-esta-mal,Dr. Pérez:xyz@group.calendar.google.com"
    assert _profesionales_de(texto) == {
        "Dra. García": "abc@group.calendar.google.com",
        "Dr. Pérez": "xyz@group.calendar.google.com",
    }


def test_comas_de_sobra_se_ignoran():
    texto = "Dra. García:abc@group.calendar.google.com,,,"
    assert _profesionales_de(texto) == {"Dra. García": "abc@group.calendar.google.com"}

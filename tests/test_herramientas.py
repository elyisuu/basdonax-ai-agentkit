"""Pruebas de las herramientas. No salen a internet ni gastan tokens.

Open-Meteo se reemplaza por datos escritos a mano: lo que se prueba es lo
nuestro (cómo se arma el texto, qué pasa cuando algo falla), no que la API
de ellos ande.

    pytest
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agente import herramientas  # noqa: E402
from agente.canales.chatwoot import ErrorDeChatwoot  # noqa: E402
from agente.herramientas import HERRAMIENTAS, anotar_reserva, clima  # noqa: E402

ROSARIO = {
    "nombre": "Rosario",
    "provincia": "Provincia de Santa Fe",
    "pais": "Argentina",
    "latitud": -32.94682,
    "longitud": -60.63932,
}

MEDICION = {
    "current": {
        "time": "2026-07-28T14:30",
        "temperature_2m": 19.1,
        "relative_humidity_2m": 83,
        "apparent_temperature": 18.4,
        "weather_code": 3,
        "wind_speed_10m": 13.8,
    }
}


def sin_internet(monkeypatch, lugar=ROSARIO, medicion=MEDICION) -> None:
    """Deja la herramienta andando con datos inventados, sin tocar la red."""
    monkeypatch.setattr(herramientas, "_buscar_lugar", lambda nombre: lugar)
    monkeypatch.setattr(
        herramientas, "_pedir_el_clima", lambda latitud, longitud: medicion
    )


def test_el_clima_sale_en_castellano_y_con_los_datos(monkeypatch):
    sin_internet(monkeypatch)

    texto = clima.invoke({"lugar": "Rosario"})

    assert "Rosario, Provincia de Santa Fe, Argentina" in texto
    assert "19.1 °C" in texto
    assert "nublado" in texto, "el código 3 del WMO es cielo nublado"
    assert "83 %" in texto
    assert "13.8 km/h" in texto
    assert "14:30" in texto


def test_traduce_los_codigos_del_cielo():
    assert herramientas._describir_cielo(0) == "despejado"
    assert herramientas._describir_cielo(95) == "con tormenta"
    assert herramientas._describir_cielo(None) == "sin datos"
    # Un código que no está en la tabla no puede romper: se informa el número.
    assert "444" in herramientas._describir_cielo(444)


def test_si_falta_un_dato_no_se_rompe(monkeypatch):
    """Open-Meteo no siempre manda todo. Lo que falta se omite, no explota."""
    sin_internet(monkeypatch, medicion={"current": {"temperature_2m": 7.0}})

    texto = clima.invoke({"lugar": "Rosario"})

    assert "7.0 °C" in texto
    assert "Humedad" not in texto, "lo que no vino no se inventa ni se muestra vacío"


def test_si_no_existe_la_ciudad_lo_dice(monkeypatch):
    monkeypatch.setattr(herramientas, "_buscar_lugar", lambda nombre: None)

    texto = clima.invoke({"lugar": "Ciudad Gótica"})

    assert "Ciudad Gótica" in texto
    assert "no encontré" in texto.lower()


def test_si_se_cae_la_api_la_charla_sigue(monkeypatch):
    """Una herramienta que levanta una excepción corta toda la respuesta.

    Devolviendo el problema como texto, el modelo lo lee y se lo explica a la
    persona en vez de que la conversación se caiga con un error crudo.
    """

    def explota(nombre):
        raise TimeoutError("tardó demasiado")

    monkeypatch.setattr(herramientas, "_buscar_lugar", explota)

    texto = clima.invoke({"lugar": "Rosario"})

    assert "TimeoutError" in texto
    assert "tardó demasiado" in texto


def test_el_nombre_completo_no_deja_comas_sueltas():
    """Cuando no hay provincia, no puede quedar "Madrid, , España"."""
    solo = {"nombre": "Madrid", "provincia": "", "pais": "España"}

    assert herramientas._nombre_completo(solo) == "Madrid, España"


def test_la_herramienta_esta_en_la_lista_que_mira_el_grafo():
    """Si no está acá, el modelo no se entera de que existe."""
    assert clima in HERRAMIENTAS


def test_el_modelo_recibe_una_descripcion_util():
    """El docstring no es decorativo: es lo único que el modelo lee para
    decidir si la herramienta le sirve."""
    assert clima.name == "clima"
    assert "clima" in clima.description.lower()
    assert "lugar" in clima.args


# -- anotar_reserva ------------------------------------------------------------
#
# No se prueba contra un Chatwoot de verdad: se reemplaza `_chatwoot_del_config`
# por uno de mentira que anota lo que se le pidió, igual que hace
# test_chatwoot.py con la API. `config` se arma a mano, con la misma forma que
# le pasa Agente._config_hilo(): {"configurable": {"thread_id": ...}}.


class _ChatwootDeMentira:
    def __init__(self) -> None:
        self.notas: list[tuple[str, str]] = []
        self.etiquetas: list[tuple[str, str]] = []

    def anotar(self, conversacion, texto):
        self.notas.append((conversacion, texto))

    def etiquetar(self, conversacion, etiqueta):
        self.etiquetas.append((conversacion, etiqueta))


def _config(thread_id="42") -> dict:
    return {"configurable": {"thread_id": thread_id}}


def test_anota_la_reserva_y_etiqueta_la_conversacion(monkeypatch):
    falso = _ChatwootDeMentira()
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: falso)

    resultado = anotar_reserva.invoke(
        {"nombre": "Juan", "personas": 4, "fecha": "sábado", "hora": "21hs"},
        config=_config(),
    )

    assert "pendiente" in resultado.lower()
    assert falso.notas[0][0] == "42"
    assert "Juan" in falso.notas[0][1]
    assert "4" in falso.notas[0][1]
    assert falso.etiquetas == [("42", herramientas.ETIQUETA_RESERVA)]


def test_los_datos_opcionales_solo_aparecen_si_se_dieron(monkeypatch):
    falso = _ChatwootDeMentira()
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: falso)

    anotar_reserva.invoke(
        {"nombre": "Ana", "personas": 2, "fecha": "hoy", "hora": "20hs"},
        config=_config(),
    )

    assert "Teléfono" not in falso.notas[0][1]
    assert "Aclaración" not in falso.notas[0][1]


def test_sin_chatwoot_configurado_no_intenta_nada(monkeypatch):
    """En Telegram o en la plataforma de pruebas no hay dónde anotar la reserva."""
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: None)

    resultado = anotar_reserva.invoke(
        {"nombre": "Juan", "personas": 2, "fecha": "hoy", "hora": "20hs"},
        config=_config(),
    )

    assert "chatwoot" in resultado.lower()


def test_si_falla_chatwoot_la_charla_sigue(monkeypatch):
    """Una herramienta que levanta una excepción corta toda la respuesta."""

    class _Explota:
        def anotar(self, *a, **k):
            raise ErrorDeChatwoot("Chatwoot devolvió 404 en conversations/42")

    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: _Explota())

    resultado = anotar_reserva.invoke(
        {"nombre": "Juan", "personas": 2, "fecha": "hoy", "hora": "20hs"},
        config=_config(),
    )

    assert "ErrorDeChatwoot" in resultado
    assert "404" in resultado


def test_anotar_reserva_esta_en_la_lista():
    assert anotar_reserva in HERRAMIENTAS


def test_el_modelo_recibe_una_descripcion_util_de_la_reserva():
    assert anotar_reserva.name == "anotar_reserva"
    assert "reserva" in anotar_reserva.description.lower()
    assert "nombre" in anotar_reserva.args
    assert "config" not in anotar_reserva.args, (
        "el thread_id se inyecta solo (RunnableConfig); "
        "el modelo no lo tiene que mandar ni saber que existe"
    )

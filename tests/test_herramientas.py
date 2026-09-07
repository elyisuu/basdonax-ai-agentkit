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
from agente.calendario import ErrorDeCalendario  # noqa: E402
from agente.canales.chatwoot import ErrorDeChatwoot  # noqa: E402
from agente.herramientas import (  # noqa: E402
    HERRAMIENTAS,
    anotar_reserva,
    clima,
    franjas_ocupadas,
)

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


# -- Reservas: franjas_ocupadas y anotar_reserva --------------------------------
#
# No se prueba contra Chatwoot ni Google Calendar de verdad: se reemplazan
# `_chatwoot_del_config` y `_calendario_del_config` por versiones de
# mentira que anotan lo que se les pidió, mismo criterio que test_chatwoot.py
# y test_calendario.py con sus respectivas API. `config` se arma a mano, con
# la misma forma que le pasa Agente._config_hilo(): {"configurable":
# {"thread_id": ...}}.
#
# Cada test deja explícito qué hay conectado y qué no (aunque sea None):
# así ningún test depende de lo que diga el .env de verdad de esta máquina.


class _ChatwootDeMentira:
    def __init__(self) -> None:
        self.notas: list[tuple[str, str]] = []
        self.etiquetas: list[tuple[str, str]] = []

    def anotar(self, conversacion, texto):
        self.notas.append((conversacion, texto))

    def etiquetar(self, conversacion, etiqueta):
        self.etiquetas.append((conversacion, etiqueta))


class _CalendarioDeMentira:
    def __init__(self, ocupado=None, libre=True) -> None:
        self._ocupado = ocupado or []
        self._libre = libre
        self.eventos: list[dict] = []
        self.aprobados: list[str] = []
        self.cancelados: list[str] = []

    def ocupado(self, fecha):
        return self._ocupado

    def rango(self, fecha, hora, duracion_minutos):
        return (f"{fecha} {hora} inicio", f"{fecha} {hora} +{duracion_minutos}min")

    def se_superpone(self, inicio, fin):
        return not self._libre

    def crear_evento(self, titulo, descripcion, inicio, fin, estado="confirmed"):
        evento = {
            "id": f"evento-{len(self.eventos) + 1}",
            "titulo": titulo,
            "descripcion": descripcion,
            "estado": estado,
        }
        self.eventos.append(evento)
        return evento

    def aprobar_evento(self, evento_id):
        self.aprobados.append(evento_id)

    def cancelar_evento(self, evento_id):
        self.cancelados.append(evento_id)


def _config(thread_id="42") -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _sin_nada(monkeypatch) -> None:
    """Ni Chatwoot ni calendario conectados — el caso de Telegram, por ejemplo."""
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: None)
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: None)


class _AjustesDeMentira:
    """Ídem Config, pero solo los campos que anotar_reserva mira de acá."""

    def __init__(
        self,
        reserva_requiere_aprobacion=False,
        url_publica="",
        reserva_secreto="",
    ) -> None:
        self.reserva_requiere_aprobacion = reserva_requiere_aprobacion
        self.url_publica = url_publica
        self.reserva_secreto = reserva_secreto


def _sin_aprobacion(monkeypatch) -> None:
    """RESERVA_REQUIERE_APROBACION en false — el caso normal (Nivel 2).

    Hace falta en cualquier test que llegue a crear el evento en el
    calendario: sin esto, anotar_reserva llamaría a la Config de verdad y
    el test dependería del .env de esta máquina.
    """
    monkeypatch.setattr(
        herramientas, "_ajustes_del_config", lambda config: _AjustesDeMentira()
    )


def _con_aprobacion(monkeypatch, url_publica="", reserva_secreto="") -> None:
    monkeypatch.setattr(
        herramientas,
        "_ajustes_del_config",
        lambda config: _AjustesDeMentira(
            reserva_requiere_aprobacion=True,
            url_publica=url_publica,
            reserva_secreto=reserva_secreto,
        ),
    )


# -- Nivel 1: solo Chatwoot, sin calendario --------------------------------------


def test_sin_calendario_solo_anota_y_queda_pendiente(monkeypatch):
    falso = _ChatwootDeMentira()
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: falso)
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: None)

    resultado = anotar_reserva.invoke(
        {"nombre": "Juan", "personas": 4, "fecha": "2026-09-12", "hora": "21:00"},
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
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: None)

    anotar_reserva.invoke(
        {"nombre": "Ana", "personas": 2, "fecha": "2026-09-12", "hora": "20:00"},
        config=_config(),
    )

    assert "Teléfono" not in falso.notas[0][1]
    assert "Aclaración" not in falso.notas[0][1]


def test_sin_nada_conectado_no_intenta_nada(monkeypatch):
    """En Telegram o en la plataforma de pruebas no hay dónde guardar la reserva."""
    _sin_nada(monkeypatch)

    resultado = anotar_reserva.invoke(
        {"nombre": "Juan", "personas": 2, "fecha": "2026-09-12", "hora": "20:00"},
        config=_config(),
    )

    assert "chatwoot" in resultado.lower()
    assert "calendar" in resultado.lower()


def test_si_falla_chatwoot_y_no_hay_calendario_se_avisa_del_error(monkeypatch):
    """Sin calendario, Chatwoot es la ÚNICA constancia: si falla, no se
    puede decir "reserva anotada" — se perdió de verdad."""

    class _Explota:
        def anotar(self, *a, **k):
            raise ErrorDeChatwoot("Chatwoot devolvió 404 en conversations/42")

    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: _Explota())
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: None)

    resultado = anotar_reserva.invoke(
        {"nombre": "Juan", "personas": 2, "fecha": "2026-09-12", "hora": "20:00"},
        config=_config(),
    )

    assert "ErrorDeChatwoot" in resultado
    assert "404" in resultado


# -- Nivel 2: con calendario conectado -------------------------------------------


def test_con_calendario_libre_confirma_el_turno(monkeypatch):
    cal = _CalendarioDeMentira(libre=True)
    chatwoot = _ChatwootDeMentira()
    _sin_aprobacion(monkeypatch)
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)

    resultado = anotar_reserva.invoke(
        {"nombre": "Ana", "personas": 1, "fecha": "2026-09-12", "hora": "10:00"},
        config=_config(),
    )

    assert "confirmado" in resultado.lower()
    assert cal.eventos, "tendría que haber creado el evento"
    assert cal.eventos[0]["titulo"] == "Ana (1p)"
    # También le queda una constancia al equipo en la bandeja de Chatwoot.
    assert chatwoot.etiquetas == [("42", herramientas.ETIQUETA_RESERVA)]


def test_con_calendario_ocupado_no_confirma_y_no_crea_el_evento(monkeypatch):
    cal = _CalendarioDeMentira(libre=False)
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: None)

    resultado = anotar_reserva.invoke(
        {"nombre": "Ana", "personas": 1, "fecha": "2026-09-12", "hora": "10:00"},
        config=_config(),
    )

    assert "ocupado" in resultado.lower()
    assert not cal.eventos, "no tiene que crear nada si el horario está tomado"


def test_si_falla_el_calendario_no_se_avisa_reserva_pendiente(monkeypatch):
    """Si el calendario explota, no hay que decir "quedó anotada": ni el
    calendario ni (en este test) Chatwoot tienen la reserva."""

    class _Explota:
        def rango(self, *a, **k):
            raise ErrorDeCalendario("Google Calendar devolvió 500")

    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: _Explota())
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: None)

    resultado = anotar_reserva.invoke(
        {"nombre": "Ana", "personas": 1, "fecha": "2026-09-12", "hora": "10:00"},
        config=_config(),
    )

    assert "ErrorDeCalendario" in resultado
    assert "500" in resultado


def test_si_falla_chatwoot_pero_el_calendario_ya_confirmo_no_se_pierde_el_turno(monkeypatch):
    """El calendario es la fuente de la verdad acá: un aviso que no salió a
    la bandeja no puede tirar abajo un turno que sí quedó guardado."""
    cal = _CalendarioDeMentira(libre=True)

    class _Explota:
        def anotar(self, *a, **k):
            raise ErrorDeChatwoot("Chatwoot devolvió 500")

    _sin_aprobacion(monkeypatch)
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: _Explota())

    resultado = anotar_reserva.invoke(
        {"nombre": "Ana", "personas": 1, "fecha": "2026-09-12", "hora": "10:00"},
        config=_config(),
    )

    assert "confirmado" in resultado.lower()
    assert cal.eventos, "el turno se creó igual"


# -- Nivel 1.5: calendario conectado, pero con aprobación manual ----------------


def test_con_aprobacion_el_evento_queda_tentative_y_no_confirmado(monkeypatch):
    cal = _CalendarioDeMentira(libre=True)
    chatwoot = _ChatwootDeMentira()
    _con_aprobacion(monkeypatch)
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)

    resultado = anotar_reserva.invoke(
        {"nombre": "Ana", "personas": 2, "fecha": "2026-09-12", "hora": "20:00"},
        config=_config(),
    )

    assert cal.eventos, "el horario tiene que quedar tomado en el calendario"
    assert cal.eventos[0]["estado"] == "tentative"
    assert "confirmado" not in resultado.lower()
    assert "espera" in resultado.lower() or "aprueb" in resultado.lower()


def test_con_aprobacion_la_etiqueta_es_distinta_de_la_normal(monkeypatch):
    cal = _CalendarioDeMentira(libre=True)
    chatwoot = _ChatwootDeMentira()
    _con_aprobacion(monkeypatch)
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)

    anotar_reserva.invoke(
        {"nombre": "Ana", "personas": 2, "fecha": "2026-09-12", "hora": "20:00"},
        config=_config(),
    )

    assert chatwoot.etiquetas == [("42", herramientas.ETIQUETA_RESERVA_PENDIENTE)]
    assert herramientas.ETIQUETA_RESERVA_PENDIENTE != herramientas.ETIQUETA_RESERVA


def test_con_aprobacion_sin_url_publica_avisa_que_hay_que_ir_al_calendario(monkeypatch):
    """Sin URL_PUBLICA/RESERVA_SECRETO no hay links, pero el turno igual
    queda tomado — no puede fallar la reserva por esto."""
    cal = _CalendarioDeMentira(libre=True)
    chatwoot = _ChatwootDeMentira()
    _con_aprobacion(monkeypatch)  # sin url_publica ni reserva_secreto
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)

    anotar_reserva.invoke(
        {"nombre": "Ana", "personas": 2, "fecha": "2026-09-12", "hora": "20:00"},
        config=_config(),
    )

    nota = chatwoot.notas[0][1]
    assert "google calendar" in nota.lower()
    assert "http" not in nota


def test_con_aprobacion_con_url_publica_suma_los_dos_links(monkeypatch):
    cal = _CalendarioDeMentira(libre=True)
    chatwoot = _ChatwootDeMentira()
    _con_aprobacion(
        monkeypatch, url_publica="https://negocio.com", reserva_secreto="shhh"
    )
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)

    anotar_reserva.invoke(
        {"nombre": "Ana", "personas": 2, "fecha": "2026-09-12", "hora": "20:00"},
        config=_config(),
    )

    nota = chatwoot.notas[0][1]
    assert "https://negocio.com/reservas/aprobar/42/evento-1?token=" in nota
    assert "https://negocio.com/reservas/rechazar/42/evento-1?token=" in nota


def test_con_aprobacion_y_horario_ocupado_no_crea_nada(monkeypatch):
    """El chequeo de disponibilidad es el mismo de siempre, con o sin
    aprobación manual."""
    cal = _CalendarioDeMentira(libre=False)
    _con_aprobacion(monkeypatch)
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: None)

    resultado = anotar_reserva.invoke(
        {"nombre": "Ana", "personas": 1, "fecha": "2026-09-12", "hora": "10:00"},
        config=_config(),
    )

    assert "ocupado" in resultado.lower()
    assert not cal.eventos


# -- franjas_ocupadas -------------------------------------------------------------


def test_franjas_ocupadas_lista_lo_que_ya_esta_tomado(monkeypatch):
    cal = _CalendarioDeMentira(ocupado=[("10:00", "11:00"), ("15:00", "16:00")])
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)

    resultado = franjas_ocupadas.invoke({"fecha": "2026-09-12"}, config=_config())

    assert "10:00" in resultado and "11:00" in resultado
    assert "15:00" in resultado and "16:00" in resultado


def test_franjas_ocupadas_sin_calendario_configurado(monkeypatch):
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: None)

    resultado = franjas_ocupadas.invoke({"fecha": "2026-09-12"}, config=_config())

    assert "no tiene un calendario conectado" in resultado.lower()


def test_si_falla_el_calendario_al_consultar_la_charla_sigue(monkeypatch):
    class _Explota:
        def ocupado(self, fecha):
            raise ErrorDeCalendario("Google Calendar devolvió 500")

    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: _Explota())

    resultado = franjas_ocupadas.invoke({"fecha": "2026-09-12"}, config=_config())

    assert "ErrorDeCalendario" in resultado
    assert "500" in resultado


def test_franjas_ocupadas_esta_en_la_lista():
    assert franjas_ocupadas in HERRAMIENTAS


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


def test_el_modelo_recibe_una_descripcion_util_de_franjas_ocupadas():
    assert franjas_ocupadas.name == "franjas_ocupadas"
    assert "calendario" in franjas_ocupadas.description.lower()
    assert "fecha" in franjas_ocupadas.args
    assert "config" not in franjas_ocupadas.args

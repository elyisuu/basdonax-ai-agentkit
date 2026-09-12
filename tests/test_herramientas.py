"""Pruebas de las herramientas. No salen a internet ni gastan tokens.

Open-Meteo se reemplaza por datos escritos a mano: lo que se prueba es lo
nuestro (cómo se arma el texto, qué pasa cuando algo falla), no que la API
de ellos ande.

    pytest
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agente import herramientas  # noqa: E402
from agente.calendario import ErrorDeCalendario  # noqa: E402
from agente.canales.chatwoot import ErrorDeChatwoot  # noqa: E402
from agente.herramientas import (  # noqa: E402
    HERRAMIENTAS,
    actualizar_ficha_cliente,
    anotar_lista_espera,
    anotar_reserva,
    cancelar_mi_reserva,
    clima,
    derivar_a_persona,
    franjas_ocupadas,
    reprogramar_mi_reserva,
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
    def __init__(self, contacto_id="7") -> None:
        self.notas: list[tuple[str, str]] = []
        self.etiquetas: list[tuple[str, str]] = []
        self._contacto_id = contacto_id
        self.nombres_puestos: list[tuple[str, str]] = []
        self.notas_de_contacto: list[tuple[str, str]] = []

    def anotar(self, conversacion, texto):
        self.notas.append((conversacion, texto))

    def etiquetar(self, conversacion, etiqueta):
        self.etiquetas.append((conversacion, etiqueta))

    def contacto_de(self, conversacion):
        return self._contacto_id

    def actualizar_nombre_contacto(self, contacto_id, nombre):
        self.nombres_puestos.append((contacto_id, nombre))

    def agregar_nota_contacto(self, contacto_id, texto):
        self.notas_de_contacto.append((contacto_id, texto))


class _CalendarioDeMentira:
    def __init__(self, ocupado=None, libre=True) -> None:
        self._ocupado = ocupado or []
        self._libre = libre
        self.eventos: list[dict] = []  # solo los "vivos" (no cancelados)
        self.aprobados: list[str] = []
        self.cancelados: list[str] = []

    def ocupado(self, fecha):
        return self._ocupado

    def rango(self, fecha, hora, duracion_minutos):
        inicio = datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H:%M")
        return inicio, inicio + timedelta(minutes=duracion_minutos)

    def se_superpone(self, inicio, fin):
        return not self._libre

    def crear_evento(self, titulo, descripcion, inicio, fin, estado="confirmed"):
        evento = {
            "id": f"evento-{len(self.eventos) + 1}",
            # Nombres viejos (los usan los tests de Nivel 2/1.5 de arriba)
            # y los nombres reales de la API de Google (los usa
            # evento_en/_duracion_minutos), a propósito duplicados.
            "titulo": titulo,
            "descripcion": descripcion,
            "estado": estado,
            "summary": titulo,
            "description": descripcion,
            "status": estado,
            "start": {"dateTime": inicio.isoformat()},
            "end": {"dateTime": fin.isoformat()},
        }
        self.eventos.append(evento)
        return evento

    def aprobar_evento(self, evento_id):
        self.aprobados.append(evento_id)
        for e in self.eventos:
            if e["id"] == evento_id:
                e["estado"] = e["status"] = "confirmed"

    def cancelar_evento(self, evento_id):
        self.cancelados.append(evento_id)
        self.eventos = [e for e in self.eventos if e["id"] != evento_id]

    def evento_en(self, inicio):
        for e in self.eventos:
            e_inicio = datetime.fromisoformat(e["start"]["dateTime"])
            e_fin = datetime.fromisoformat(e["end"]["dateTime"])
            if e_inicio <= inicio < e_fin:
                return e
        return None


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
        horario_desde="",
        horario_hasta="",
        horario_franjas="",
        dias_cerrados="",
        cancelacion_horas_minimas=0,
        chatwoot_etiqueta_humano="humano",
        alerta_telegram_token="",
        alerta_telegram_chat_id="",
        zona_horaria="UTC",
        postgres_dsn="",
        profesionales=None,
        google_service_account_json="cuenta-de-servicio-de-mentira",
    ) -> None:
        self.reserva_requiere_aprobacion = reserva_requiere_aprobacion
        self.url_publica = url_publica
        self.reserva_secreto = reserva_secreto
        self.horario_desde = horario_desde
        self.horario_hasta = horario_hasta
        self.horario_franjas = horario_franjas
        self.dias_cerrados = dias_cerrados
        self.cancelacion_horas_minimas = cancelacion_horas_minimas
        self.chatwoot_etiqueta_humano = chatwoot_etiqueta_humano
        self.alerta_telegram_token = alerta_telegram_token
        self.alerta_telegram_chat_id = alerta_telegram_chat_id
        self.zona_horaria = zona_horaria
        self.profesionales = profesionales or {}
        self.google_service_account_json = google_service_account_json
        self.postgres_dsn = postgres_dsn


@pytest.fixture(autouse=True)
def _ajustes_por_defecto(monkeypatch):
    """anotar_reserva llama a _ajustes_del_config(config) para el chequeo
    de horario ANTES que nada más — sin este default, cualquier test que
    no lo pise a mano llamaría a la Config de verdad y dependería del .env
    de esta máquina. Los tests que necesitan otro valor (RESERVA_REQUIERE_
    APROBACION en true, un horario puesto) lo pisan después con
    _con_aprobacion() o monkeypatch.setattr directo."""
    monkeypatch.setattr(
        herramientas, "_ajustes_del_config", lambda config: _AjustesDeMentira()
    )
    # anotar_reserva también rechaza fecha/hora ya pasada, comparando
    # contra _ahora(ajustes) — sin fijarla acá, esta suite se rompería
    # sola el día que la fecha real pase las fechas de prueba de más
    # arriba (2026-09-12 y parecidas, usadas en tests que no tienen nada
    # que ver con esto). Los tests que sí prueban el rechazo por fecha
    # pasada la pisan de nuevo con algo más cercano a esas fechas.
    monkeypatch.setattr(herramientas, "_ahora", lambda ajustes: datetime(2020, 1, 1))


def _sin_aprobacion(monkeypatch) -> None:
    """RESERVA_REQUIERE_APROBACION en false — el caso normal (Nivel 2).

    Ya lo pone _ajustes_por_defecto solo; queda para que los tests
    existentes que lo llaman a mano sigan siendo explícitos.
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


def _con_cancelacion(monkeypatch, horas_minimas) -> None:
    monkeypatch.setattr(
        herramientas,
        "_ajustes_del_config",
        lambda config: _AjustesDeMentira(cancelacion_horas_minimas=horas_minimas),
    )


def _con_horario(monkeypatch, desde="", hasta="", cerrados="", franjas="") -> None:
    monkeypatch.setattr(
        herramientas,
        "_ajustes_del_config",
        lambda config: _AjustesDeMentira(
            horario_desde=desde,
            horario_hasta=hasta,
            dias_cerrados=cerrados,
            horario_franjas=franjas,
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


def test_confirmar_el_turno_registra_la_visita(monkeypatch):
    """A diferencia de actualizar_ficha_cliente, esto no depende de que el
    modelo decida llamar nada: anotar_reserva lo hace siempre que confirma."""
    cal = _CalendarioDeMentira(libre=True)
    chatwoot = _ChatwootDeMentira(contacto_id="99")
    monkeypatch.setattr(
        herramientas,
        "_ajustes_del_config",
        lambda config: _AjustesDeMentira(postgres_dsn="dsn-falso"),
    )
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)
    llamadas = []
    monkeypatch.setattr(
        herramientas.visitas,
        "registrar_visita",
        lambda dsn, contacto_id, fecha, hora, telefono="", nombre="", motivo="": llamadas.append(
            (dsn, contacto_id, fecha, hora, telefono, nombre, motivo)
        ),
    )

    anotar_reserva.invoke(
        {
            "nombre": "Ana",
            "personas": 1,
            "fecha": "2026-09-12",
            "hora": "10:00",
            "telefono": "+351900000000",
            "aclaracion": "Dolor de espalda",
        },
        config=_config(),
    )

    assert llamadas == [
        ("dsn-falso", "99", "2026-09-12", "10:00", "+351900000000", "Ana", "Dolor de espalda")
    ]


def test_una_reserva_pendiente_de_aprobacion_no_registra_visita_todavia(monkeypatch):
    """Contarla al crearla inflaría las estadísticas con turnos que después
    se rechazan — se registra recién cuando se aprueba (web/webhook.py)."""
    cal = _CalendarioDeMentira(libre=True)
    chatwoot = _ChatwootDeMentira(contacto_id="99")
    _con_aprobacion(monkeypatch)
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)
    llamadas = []
    monkeypatch.setattr(
        herramientas.visitas, "registrar_visita", lambda *a, **k: llamadas.append((a, k))
    )

    anotar_reserva.invoke(
        {"nombre": "Ana", "personas": 2, "fecha": "2026-09-12", "hora": "20:00"},
        config=_config(),
    )

    assert llamadas == []


def test_si_no_hay_contacto_no_registra_visita_pero_confirma_igual(monkeypatch):
    """Sin poder identificar a la persona no hay a quién atribuirle la
    visita — pero eso no puede voltear la reserva, que sí es real."""
    cal = _CalendarioDeMentira(libre=True)
    chatwoot = _ChatwootDeMentira(contacto_id=None)
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)
    llamadas = []
    monkeypatch.setattr(
        herramientas.visitas, "registrar_visita", lambda *a, **k: llamadas.append((a, k))
    )

    resultado = anotar_reserva.invoke(
        {"nombre": "Ana", "personas": 1, "fecha": "2026-09-12", "hora": "10:00"},
        config=_config(),
    )

    assert "confirmado" in resultado.lower()
    assert llamadas == []


def test_la_descripcion_del_calendario_lleva_la_conversacion(monkeypatch):
    """recordatorios.py la necesita para saber a quién avisarle — sin
    guardar esa relación en ningún otro lado."""
    cal = _CalendarioDeMentira(libre=True)
    chatwoot = _ChatwootDeMentira()
    _sin_aprobacion(monkeypatch)
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)

    anotar_reserva.invoke(
        {"nombre": "Ana", "personas": 1, "fecha": "2026-09-12", "hora": "10:00"},
        config=_config(thread_id="42"),
    )

    assert "Conversación: 42" in cal.eventos[0]["descripcion"]
    # La nota de Chatwoot es para una persona: no le suma nada este dato.
    assert "Conversación:" not in chatwoot.notas[0][1]


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


# -- Varios profesionales, cada uno con su propia agenda -------------------------
#
# Fase 1 (ver AGENTS.md): solo anotar_reserva y franjas_ocupadas. Sin
# PROFESIONALES configurado, cero cambio de comportamiento — por eso casi
# todos los tests de arriba de esta sección ni lo mencionan y siguen
# pasando: _AjustesDeMentira() por default trae profesionales={}.


def test_buscar_calendar_id_encuentra_sin_importar_mayusculas_ni_espacios():
    profesionales = {"Dra. García": "cal-garcia", "Dr. Pérez": "cal-perez"}
    assert herramientas._buscar_calendar_id(profesionales, "dra. garcía") == "cal-garcia"
    assert herramientas._buscar_calendar_id(profesionales, "  Dr. Pérez  ") == "cal-perez"


def test_buscar_calendar_id_none_si_no_esta():
    assert herramientas._buscar_calendar_id({"Ana": "cal-1"}, "Beto") is None


def test_error_profesional_sin_profesionales_configurados_nunca_frena():
    """Modo de siempre: un solo profesional (o ninguno) — profesional no
    se usa para nada, venga vacío o con cualquier cosa."""
    ajustes = _AjustesDeMentira()
    assert herramientas._error_profesional(ajustes, "") is None
    assert herramientas._error_profesional(ajustes, "cualquier cosa") is None


def test_error_profesional_sin_especificar_pide_elegir():
    ajustes = _AjustesDeMentira(profesionales={"Dra. García": "cal-1", "Dr. Pérez": "cal-2"})
    error = herramientas._error_profesional(ajustes, "")
    assert error is not None
    assert "Dra. García" in error
    assert "Dr. Pérez" in error


def test_error_profesional_que_no_coincide():
    ajustes = _AjustesDeMentira(profesionales={"Dra. García": "cal-1"})
    error = herramientas._error_profesional(ajustes, "Dr. Nadie")
    assert error is not None
    assert "Dr. Nadie" in error
    assert "Dra. García" in error


def test_error_profesional_que_coincide_no_frena():
    ajustes = _AjustesDeMentira(profesionales={"Dra. García": "cal-1"})
    assert herramientas._error_profesional(ajustes, "dra. garcía") is None


def test_calendario_de_sin_profesionales_delega_en_calendario_del_config(monkeypatch):
    cal = _CalendarioDeMentira(libre=True)
    monkeypatch.setattr(herramientas, "_ajustes_del_config", lambda config: _AjustesDeMentira())
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)

    assert herramientas._calendario_de(_config(), "") is cal


def test_calendario_de_con_profesionales_arma_el_calendario_de_ese_profesional(monkeypatch):
    ajustes = _AjustesDeMentira(
        profesionales={"Dra. García": "cal-garcia", "Dr. Pérez": "cal-perez"}
    )
    monkeypatch.setattr(herramientas, "_ajustes_del_config", lambda config: ajustes)
    llamadas = []
    cal = _CalendarioDeMentira(libre=True)
    monkeypatch.setattr(
        herramientas,
        "_construir_calendario",
        lambda calendar_id, ajustes: llamadas.append(calendar_id) or cal,
    )

    resultado = herramientas._calendario_de(_config(), "Dr. Pérez")

    assert resultado is cal
    assert llamadas == ["cal-perez"]


def test_calendario_de_con_profesionales_y_nombre_que_no_coincide_da_none(monkeypatch):
    ajustes = _AjustesDeMentira(profesionales={"Dra. García": "cal-garcia"})
    monkeypatch.setattr(herramientas, "_ajustes_del_config", lambda config: ajustes)

    assert herramientas._calendario_de(_config(), "Dr. Nadie") is None


def test_anotar_reserva_sin_elegir_profesional_pregunta_antes_de_tocar_nada(monkeypatch):
    """Ni Chatwoot ni el calendario se tocan hasta saber con quién."""
    monkeypatch.setattr(
        herramientas,
        "_ajustes_del_config",
        lambda config: _AjustesDeMentira(
            profesionales={"Dra. García": "cal-garcia", "Dr. Pérez": "cal-perez"}
        ),
    )
    cal = _CalendarioDeMentira(libre=True)
    chatwoot = _ChatwootDeMentira()
    monkeypatch.setattr(herramientas, "_construir_calendario", lambda calendar_id, ajustes: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)

    resultado = anotar_reserva.invoke(
        {"nombre": "Ana", "personas": 1, "fecha": "2026-09-12", "hora": "10:00"},
        config=_config(),
    )

    assert "Dra. García" in resultado
    assert "Dr. Pérez" in resultado
    assert not cal.eventos
    assert chatwoot.notas == []


def test_anotar_reserva_con_profesional_que_no_existe_avisa(monkeypatch):
    monkeypatch.setattr(
        herramientas,
        "_ajustes_del_config",
        lambda config: _AjustesDeMentira(profesionales={"Dra. García": "cal-garcia"}),
    )

    resultado = anotar_reserva.invoke(
        {
            "nombre": "Ana",
            "personas": 1,
            "fecha": "2026-09-12",
            "hora": "10:00",
            "profesional": "Dr. Inventado",
        },
        config=_config(),
    )

    assert "Dr. Inventado" in resultado
    assert "Dra. García" in resultado


def test_anotar_reserva_con_el_profesional_correcto_reserva_en_su_agenda(monkeypatch):
    monkeypatch.setattr(
        herramientas,
        "_ajustes_del_config",
        lambda config: _AjustesDeMentira(
            profesionales={"Dra. García": "cal-garcia", "Dr. Pérez": "cal-perez"}
        ),
    )
    cal_garcia = _CalendarioDeMentira(libre=True)
    cal_perez = _CalendarioDeMentira(libre=True)
    calendarios = {"cal-garcia": cal_garcia, "cal-perez": cal_perez}
    monkeypatch.setattr(
        herramientas,
        "_construir_calendario",
        lambda calendar_id, ajustes: calendarios[calendar_id],
    )
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: None)

    resultado = anotar_reserva.invoke(
        {
            "nombre": "Ana",
            "personas": 1,
            "fecha": "2026-09-12",
            "hora": "10:00",
            "profesional": "dr. pérez",  # minúsculas a propósito
        },
        config=_config(),
    )

    assert "confirmado" in resultado.lower()
    assert cal_perez.eventos, "el turno tenía que quedar en la agenda del Dr. Pérez"
    assert not cal_garcia.eventos, "y no en la de la Dra. García"


def test_franjas_ocupadas_sin_elegir_profesional_pregunta(monkeypatch):
    monkeypatch.setattr(
        herramientas,
        "_ajustes_del_config",
        lambda config: _AjustesDeMentira(
            profesionales={"Dra. García": "cal-garcia", "Dr. Pérez": "cal-perez"}
        ),
    )

    resultado = franjas_ocupadas.invoke({"fecha": "2026-09-12"}, config=_config())

    assert "Dra. García" in resultado
    assert "Dr. Pérez" in resultado


def test_franjas_ocupadas_con_profesional_correcto_consulta_su_agenda(monkeypatch):
    monkeypatch.setattr(
        herramientas,
        "_ajustes_del_config",
        lambda config: _AjustesDeMentira(
            profesionales={"Dra. García": "cal-garcia", "Dr. Pérez": "cal-perez"}
        ),
    )
    cal_perez = _CalendarioDeMentira(ocupado=[("10:00", "11:00")])
    monkeypatch.setattr(
        herramientas,
        "_construir_calendario",
        lambda calendar_id, ajustes: cal_perez if calendar_id == "cal-perez" else None,
    )

    resultado = franjas_ocupadas.invoke(
        {"fecha": "2026-09-12", "profesional": "Dr. Pérez"}, config=_config()
    )

    assert "10:00" in resultado and "11:00" in resultado


# -- Horario de atención -----------------------------------------------------------


def test_fuera_del_horario_no_confirma_ni_anota(monkeypatch):
    chatwoot = _ChatwootDeMentira()
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: None)
    _con_horario(monkeypatch, desde="09:00", hasta="20:00")

    resultado = anotar_reserva.invoke(
        {"nombre": "Juan", "personas": 2, "fecha": "2026-09-12", "hora": "22:00"},
        config=_config(),
    )

    assert "atiende hasta" in resultado.lower()
    assert chatwoot.notas == [], "no tiene que anotar nada fuera de horario"


def test_un_dia_cerrado_no_confirma_ni_anota(monkeypatch):
    chatwoot = _ChatwootDeMentira()
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: None)
    _con_horario(monkeypatch, cerrados="domingo")

    # 2026-09-13 es domingo.
    resultado = anotar_reserva.invoke(
        {"nombre": "Juan", "personas": 2, "fecha": "2026-09-13", "hora": "12:00"},
        config=_config(),
    )

    assert "cerrado" in resultado.lower()
    assert chatwoot.notas == []


def test_sin_horario_configurado_no_restringe_nada(monkeypatch):
    """El default (todo vacío) es el comportamiento de antes de este módulo."""
    chatwoot = _ChatwootDeMentira()
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: None)

    resultado = anotar_reserva.invoke(
        {"nombre": "Juan", "personas": 2, "fecha": "2026-09-12", "hora": "03:00"},
        config=_config(),
    )

    assert "pendiente" in resultado.lower()


def test_horario_partido_rechaza_el_corte_del_medio(monkeypatch):
    chatwoot = _ChatwootDeMentira()
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: None)
    _con_horario(monkeypatch, franjas="09:00-15:00, 18:00-23:00")

    resultado = anotar_reserva.invoke(
        {"nombre": "Juan", "personas": 2, "fecha": "2026-09-12", "hora": "16:00"},
        config=_config(),
    )

    assert "09:00 a 15:00" in resultado
    assert chatwoot.notas == []


def test_horario_partido_acepta_los_dos_turnos(monkeypatch):
    chatwoot = _ChatwootDeMentira()
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: None)
    _con_horario(monkeypatch, franjas="09:00-15:00, 18:00-23:00")

    for hora in ("10:00", "20:00"):
        resultado = anotar_reserva.invoke(
            {"nombre": "Juan", "personas": 2, "fecha": "2026-09-12", "hora": hora},
            config=_config(),
        )
        assert "pendiente" in resultado.lower()


def test_dentro_del_horario_sigue_andando(monkeypatch):
    chatwoot = _ChatwootDeMentira()
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: None)
    _con_horario(monkeypatch, desde="09:00", hasta="20:00")

    resultado = anotar_reserva.invoke(
        {"nombre": "Juan", "personas": 2, "fecha": "2026-09-12", "hora": "12:00"},
        config=_config(),
    )

    assert "pendiente" in resultado.lower()


def test_no_se_puede_reservar_una_fecha_ya_pasada(monkeypatch):
    """Reproducido: horario.validar() no chequeaba esto — se podía anotar
    un turno para una fecha que ya pasó, con horario configurado o sin
    configurar nada."""
    chatwoot = _ChatwootDeMentira()
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: None)
    monkeypatch.setattr(herramientas, "_ahora", lambda ajustes: datetime(2026, 9, 12, 10, 0))

    resultado = anotar_reserva.invoke(
        {"nombre": "Juan", "personas": 2, "fecha": "2026-09-12", "hora": "09:00"},
        config=_config(),
    )

    assert "ya pasó" in resultado.lower()
    assert chatwoot.notas == []


def test_se_puede_reservar_una_fecha_futura_con_ahora_fijo(monkeypatch):
    chatwoot = _ChatwootDeMentira()
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: None)
    monkeypatch.setattr(herramientas, "_ahora", lambda ajustes: datetime(2026, 9, 12, 10, 0))

    resultado = anotar_reserva.invoke(
        {"nombre": "Juan", "personas": 2, "fecha": "2026-09-12", "hora": "11:00"},
        config=_config(),
    )

    assert "pendiente" in resultado.lower()


def test_fecha_con_formato_invalido_no_revienta(monkeypatch):
    """Reproducido: día y mes invertidos (u otro formato que strptime no
    entiende) subía como ValueError sin controlar — la persona veía el
    mensaje genérico de error en vez de que el bot le pida la fecha de
    nuevo."""
    chatwoot = _ChatwootDeMentira()
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: None)

    resultado = anotar_reserva.invoke(
        {"nombre": "Juan", "personas": 2, "fecha": "12-09-2026", "hora": "12:00"},
        config=_config(),
    )

    assert "no entendí" in resultado.lower()
    assert chatwoot.notas == []


def test_fecha_inexistente_no_revienta(monkeypatch):
    """Un 30 de febrero: mismo caso que el formato inválido."""
    chatwoot = _ChatwootDeMentira()
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: None)

    resultado = anotar_reserva.invoke(
        {"nombre": "Juan", "personas": 2, "fecha": "2026-02-30", "hora": "12:00"},
        config=_config(),
    )

    assert "no entendí" in resultado.lower()


# -- Cancelar y reprogramar mi reserva -----------------------------------------------


def test_cancelar_mi_reserva_sin_calendario(monkeypatch):
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: None)

    resultado = cancelar_mi_reserva.invoke(
        {"fecha": "2026-09-12", "hora": "20:00"}, config=_config()
    )

    assert "calendar" in resultado.lower()


def test_cancelar_mi_reserva_que_no_existe(monkeypatch):
    cal = _CalendarioDeMentira()
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: None)

    resultado = cancelar_mi_reserva.invoke(
        {"fecha": "2026-09-12", "hora": "20:00"}, config=_config()
    )

    assert "no encontré" in resultado.lower()
    assert cal.cancelados == []


def test_cancelar_mi_reserva_la_encuentra_y_cancela(monkeypatch):
    cal = _CalendarioDeMentira()
    chatwoot = _ChatwootDeMentira()
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)

    inicio, fin = cal.rango("2026-09-12", "20:00", 60)
    cal.crear_evento("Juan (2p)", "Nombre: Juan", inicio, fin)

    resultado = cancelar_mi_reserva.invoke(
        {"fecha": "2026-09-12", "hora": "20:00"}, config=_config()
    )

    assert "cancelé" in resultado.lower()
    assert cal.cancelados == ["evento-1"]
    assert cal.eventos == [], "el evento tiene que quedar fuera del calendario"
    assert chatwoot.etiquetas == [("42", herramientas.ETIQUETA_RESERVA_CANCELADA)]


def test_cancelar_mi_reserva_no_toca_el_turno_de_otra_conversacion(monkeypatch):
    cal = _CalendarioDeMentira()
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: None)

    inicio, fin = cal.rango("2026-09-12", "20:00", 60)
    cal.crear_evento("Ana (2p)", "Nombre: Ana\nConversación: 99", inicio, fin)

    # config() usa thread_id="42" por defecto — distinto del dueño del turno.
    resultado = cancelar_mi_reserva.invoke(
        {"fecha": "2026-09-12", "hora": "20:00"}, config=_config()
    )

    assert "no está anotado en esta conversación" in resultado.lower()
    assert cal.cancelados == [], "no se puede cancelar el turno de otra persona"


def test_cancelar_mi_reserva_permite_su_propio_turno(monkeypatch):
    cal = _CalendarioDeMentira()
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: None)

    inicio, fin = cal.rango("2026-09-12", "20:00", 60)
    cal.crear_evento("Juan (2p)", "Nombre: Juan\nConversación: 42", inicio, fin)

    resultado = cancelar_mi_reserva.invoke(
        {"fecha": "2026-09-12", "hora": "20:00"}, config=_config(thread_id="42")
    )

    assert "cancelé" in resultado.lower()
    assert cal.cancelados == ["evento-1"]


def test_cancelar_mi_reserva_permite_turnos_sin_conversacion_guardada(monkeypatch):
    """Reservas de antes de esta protección (o cargadas a mano en Calendar)
    no tienen la línea "Conversación:" — no cortarlas de raíz."""
    cal = _CalendarioDeMentira()
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: None)

    inicio, fin = cal.rango("2026-09-12", "20:00", 60)
    cal.crear_evento("Juan (2p)", "Nombre: Juan", inicio, fin)  # sin "Conversación:"

    resultado = cancelar_mi_reserva.invoke(
        {"fecha": "2026-09-12", "hora": "20:00"}, config=_config()
    )

    assert "cancelé" in resultado.lower()
    assert cal.cancelados == ["evento-1"]


def test_cancelar_mi_reserva_rechaza_dentro_de_la_anticipacion_minima(monkeypatch):
    cal = _CalendarioDeMentira()
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: None)
    _con_cancelacion(monkeypatch, horas_minimas=24)
    monkeypatch.setattr(herramientas, "_horas_hasta_el_turno", lambda evento: 2.0)

    inicio, fin = cal.rango("2026-09-12", "20:00", 60)
    cal.crear_evento("Juan (2p)", "...", inicio, fin)

    resultado = cancelar_mi_reserva.invoke(
        {"fecha": "2026-09-12", "hora": "20:00"}, config=_config()
    )

    assert "menos de 24 horas" in resultado
    assert cal.cancelados == [], "no se puede cancelar dentro de la anticipación mínima"


def test_cancelar_mi_reserva_permite_fuera_de_la_anticipacion_minima(monkeypatch):
    cal = _CalendarioDeMentira()
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: None)
    _con_cancelacion(monkeypatch, horas_minimas=24)
    monkeypatch.setattr(herramientas, "_horas_hasta_el_turno", lambda evento: 48.0)

    inicio, fin = cal.rango("2026-09-12", "20:00", 60)
    cal.crear_evento("Juan (2p)", "...", inicio, fin)

    resultado = cancelar_mi_reserva.invoke(
        {"fecha": "2026-09-12", "hora": "20:00"}, config=_config()
    )

    assert "cancelé" in resultado.lower()
    assert cal.cancelados == ["evento-1"]


def test_cancelar_mi_reserva_sin_politica_no_chequea_nada(monkeypatch):
    """CANCELACION_HORAS_MINIMAS=0 (el default) es "sin restricción"."""
    cal = _CalendarioDeMentira()
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: None)

    def explota(evento):
        raise AssertionError("no debería calcularse nada con la política en 0")

    monkeypatch.setattr(herramientas, "_horas_hasta_el_turno", explota)

    inicio, fin = cal.rango("2026-09-12", "20:00", 60)
    cal.crear_evento("Juan (2p)", "...", inicio, fin)

    resultado = cancelar_mi_reserva.invoke(
        {"fecha": "2026-09-12", "hora": "20:00"}, config=_config()
    )

    assert "cancelé" in resultado.lower()


def test_cancelar_mi_reserva_no_falla_si_chatwoot_no_esta(monkeypatch):
    """El calendario ya es la fuente de la verdad acá: un aviso que no
    sale a la bandeja no puede voltear una cancelación que sí se hizo."""
    cal = _CalendarioDeMentira()

    class _Explota:
        def anotar(self, *a, **k):
            raise ErrorDeChatwoot("Chatwoot devolvió 500")

    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: _Explota())

    inicio, fin = cal.rango("2026-09-12", "20:00", 60)
    cal.crear_evento("Juan (2p)", "...", inicio, fin)

    resultado = cancelar_mi_reserva.invoke(
        {"fecha": "2026-09-12", "hora": "20:00"}, config=_config()
    )

    assert "cancelé" in resultado.lower()
    assert cal.cancelados == ["evento-1"]


def test_reprogramar_mi_reserva_sin_calendario(monkeypatch):
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: None)

    resultado = reprogramar_mi_reserva.invoke(
        {
            "fecha_actual": "2026-09-12",
            "hora_actual": "20:00",
            "fecha_nueva": "2026-09-13",
            "hora_nueva": "21:00",
        },
        config=_config(),
    )

    assert "calendar" in resultado.lower()


def test_reprogramar_mi_reserva_que_no_existe(monkeypatch):
    cal = _CalendarioDeMentira()
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: None)

    resultado = reprogramar_mi_reserva.invoke(
        {
            "fecha_actual": "2026-09-12",
            "hora_actual": "20:00",
            "fecha_nueva": "2026-09-13",
            "hora_nueva": "21:00",
        },
        config=_config(),
    )

    assert "no encontré" in resultado.lower()


def test_reprogramar_mi_reserva_no_toca_el_turno_de_otra_conversacion(monkeypatch):
    cal = _CalendarioDeMentira(libre=True)
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: None)

    inicio, fin = cal.rango("2026-09-12", "20:00", 60)
    cal.crear_evento("Ana (2p)", "Nombre: Ana\nConversación: 99", inicio, fin)

    resultado = reprogramar_mi_reserva.invoke(
        {
            "fecha_actual": "2026-09-12",
            "hora_actual": "20:00",
            "fecha_nueva": "2026-09-13",
            "hora_nueva": "21:00",
        },
        config=_config(),  # thread_id="42", distinto del dueño del turno
    )

    assert "no está anotado en esta conversación" in resultado.lower()
    assert cal.cancelados == [], "no se puede mover el turno de otra persona"


def test_reprogramar_mi_reserva_rechaza_dentro_de_la_anticipacion_minima(monkeypatch):
    cal = _CalendarioDeMentira(libre=True)
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: None)
    _con_cancelacion(monkeypatch, horas_minimas=24)
    monkeypatch.setattr(herramientas, "_horas_hasta_el_turno", lambda evento: 2.0)

    inicio, fin = cal.rango("2026-09-12", "20:00", 60)
    cal.crear_evento("Juan (2p)", "...", inicio, fin)

    resultado = reprogramar_mi_reserva.invoke(
        {
            "fecha_actual": "2026-09-12",
            "hora_actual": "20:00",
            "fecha_nueva": "2026-09-13",
            "hora_nueva": "21:00",
        },
        config=_config(),
    )

    assert "menos de 24 horas" in resultado
    assert cal.cancelados == [], "no se puede mover dentro de la anticipación mínima"


def test_reprogramar_mi_reserva_mueve_el_turno_y_conserva_los_datos(monkeypatch):
    cal = _CalendarioDeMentira(libre=True)
    chatwoot = _ChatwootDeMentira()
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)

    inicio, fin = cal.rango("2026-09-12", "20:00", 90)
    cal.crear_evento("Juan (2p)", "Nombre: Juan\nPersonas: 2", inicio, fin, estado="confirmed")

    resultado = reprogramar_mi_reserva.invoke(
        {
            "fecha_actual": "2026-09-12",
            "hora_actual": "20:00",
            "fecha_nueva": "2026-09-13",
            "hora_nueva": "21:00",
        },
        config=_config(),
    )

    assert "moví" in resultado.lower()
    assert cal.cancelados == ["evento-1"]
    assert len(cal.eventos) == 1, "el turno viejo se borró y quedó el nuevo"

    nuevo = cal.eventos[0]
    assert nuevo["titulo"] == "Juan (2p)", "se reusan los datos del turno original"
    assert nuevo["descripcion"] == "Nombre: Juan\nPersonas: 2"
    assert nuevo["estado"] == "confirmed"

    nuevo_inicio = datetime.fromisoformat(nuevo["start"]["dateTime"])
    nuevo_fin = datetime.fromisoformat(nuevo["end"]["dateTime"])
    assert (nuevo_fin - nuevo_inicio) == timedelta(minutes=90), "conserva la duración"


def test_reprogramar_mi_reserva_con_el_horario_nuevo_ocupado(monkeypatch):
    cal = _CalendarioDeMentira(libre=False)  # se_superpone siempre True
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: None)

    inicio, fin = cal.rango("2026-09-12", "20:00", 60)
    cal.crear_evento("Juan (2p)", "...", inicio, fin)

    resultado = reprogramar_mi_reserva.invoke(
        {
            "fecha_actual": "2026-09-12",
            "hora_actual": "20:00",
            "fecha_nueva": "2026-09-13",
            "hora_nueva": "21:00",
        },
        config=_config(),
    )

    assert "ocupado" in resultado.lower()
    assert cal.cancelados == [], "no se cancela el turno viejo si el nuevo no está libre"
    assert len(cal.eventos) == 1


# -- Lista de espera ----------------------------------------------------------------


def test_anotar_lista_espera_sin_chatwoot(monkeypatch):
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: None)

    resultado = anotar_lista_espera.invoke(
        {"nombre": "Juan", "personas": 2, "fecha": "2026-09-12", "hora": "20:00"},
        config=_config(),
    )

    assert "chatwoot" in resultado.lower()


def test_anotar_lista_espera_deja_nota_y_etiqueta(monkeypatch):
    chatwoot = _ChatwootDeMentira()
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)

    resultado = anotar_lista_espera.invoke(
        {"nombre": "Juan", "personas": 2, "fecha": "2026-09-12", "hora": "20:00"},
        config=_config(),
    )

    assert "anotado" in resultado.lower()
    assert "Juan" in chatwoot.notas[0][1]
    assert chatwoot.etiquetas == [("42", herramientas.ETIQUETA_LISTA_ESPERA)]


# -- derivar_a_persona ---------------------------------------------------------------


def test_derivar_a_persona_sin_chatwoot(monkeypatch):
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: None)

    resultado = derivar_a_persona.invoke(
        {"motivo": "quiere hablar con alguien"}, config=_config()
    )

    assert "chatwoot" in resultado.lower()


def test_derivar_a_persona_deja_nota_y_pone_la_etiqueta(monkeypatch):
    chatwoot = _ChatwootDeMentira()
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)

    resultado = derivar_a_persona.invoke(
        {"motivo": "se queja de un cobro"}, config=_config()
    )

    assert "persona" in resultado.lower()
    assert "se queja de un cobro" in chatwoot.notas[0][1]
    assert chatwoot.etiquetas == [("42", "humano")]


def test_derivar_a_persona_usa_la_etiqueta_configurada(monkeypatch):
    """Si el negocio cambió CHATWOOT_ETIQUETA_HUMANO en el .env, tiene que
    ser la MISMA que después revisa Chatwoot._la_atiende_una_persona() —
    si acá quedara un nombre fijo, el traspaso quedaría roto en silencio."""
    chatwoot = _ChatwootDeMentira()
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)
    monkeypatch.setattr(
        herramientas,
        "_ajustes_del_config",
        lambda config: _AjustesDeMentira(chatwoot_etiqueta_humano="atencion-humana"),
    )

    derivar_a_persona.invoke({"motivo": "algo"}, config=_config())

    assert chatwoot.etiquetas == [("42", "atencion-humana")]


def test_derivar_a_persona_avisa_por_telegram_si_esta_configurado(monkeypatch):
    chatwoot = _ChatwootDeMentira()
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)
    monkeypatch.setattr(
        herramientas,
        "_ajustes_del_config",
        lambda config: _AjustesDeMentira(
            alerta_telegram_token="tok", alerta_telegram_chat_id="123"
        ),
    )

    avisos = []
    monkeypatch.setattr(
        herramientas.alertas,
        "avisar",
        lambda token, chat_id, clave, texto: avisos.append((token, chat_id, clave, texto)),
    )

    derivar_a_persona.invoke({"motivo": "urgente"}, config=_config())

    assert len(avisos) == 1
    token, chat_id, clave, texto = avisos[0]
    assert (token, chat_id) == ("tok", "123")
    assert "urgente" in texto


def test_derivar_a_persona_sin_telegram_configurado_no_falla(monkeypatch):
    """alertas.avisar() ya no hace nada sin token/chat_id — esto solo
    confirma que derivar_a_persona no la rodea con nada que dependa de
    que esté configurado."""
    chatwoot = _ChatwootDeMentira()
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)

    resultado = derivar_a_persona.invoke({"motivo": "algo"}, config=_config())

    assert "persona" in resultado.lower()


def test_derivar_a_persona_si_chatwoot_falla_avisa_el_error(monkeypatch):
    class _Explota:
        def anotar(self, *a, **k):
            raise RuntimeError("Chatwoot no contestó")

    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: _Explota())

    resultado = derivar_a_persona.invoke({"motivo": "algo"}, config=_config())

    assert "no se pudo derivar" in resultado.lower()


def test_derivar_a_persona_esta_en_la_lista_de_herramientas():
    assert derivar_a_persona in HERRAMIENTAS


# -- actualizar_ficha_cliente ---------------------------------------------------------


def test_actualizar_ficha_sin_nada_nuevo_no_llama_a_chatwoot(monkeypatch):
    llamado = []
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: llamado.append(1))

    resultado = actualizar_ficha_cliente.invoke({"nombre": "", "nota": ""}, config=_config())

    assert "nada nuevo" in resultado.lower()
    assert llamado == []  # ni siquiera pidió el cliente de Chatwoot


def test_actualizar_ficha_sin_chatwoot(monkeypatch):
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: None)

    resultado = actualizar_ficha_cliente.invoke(
        {"nombre": "Jesús", "nota": ""}, config=_config()
    )

    assert "chatwoot" in resultado.lower()


def test_actualizar_ficha_pone_el_nombre_y_la_nota(monkeypatch):
    chatwoot = _ChatwootDeMentira(contacto_id="7")
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)

    resultado = actualizar_ficha_cliente.invoke(
        {"nombre": "Jesús", "nota": "prefiere portugués"}, config=_config()
    )

    assert "guardado" in resultado.lower()
    assert chatwoot.nombres_puestos == [("7", "Jesús")]
    assert chatwoot.notas_de_contacto == [("7", "prefiere portugués")]


def test_actualizar_ficha_solo_nombre_no_agrega_nota_vacia(monkeypatch):
    chatwoot = _ChatwootDeMentira(contacto_id="7")
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)

    actualizar_ficha_cliente.invoke({"nombre": "Jesús", "nota": ""}, config=_config())

    assert chatwoot.nombres_puestos == [("7", "Jesús")]
    assert chatwoot.notas_de_contacto == []


def test_actualizar_ficha_sin_encontrar_el_contacto(monkeypatch):
    chatwoot = _ChatwootDeMentira(contacto_id=None)
    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: chatwoot)

    resultado = actualizar_ficha_cliente.invoke(
        {"nombre": "Jesús", "nota": ""}, config=_config()
    )

    assert "no encontré" in resultado.lower()
    assert chatwoot.nombres_puestos == []


def test_actualizar_ficha_si_chatwoot_falla_avisa_el_error(monkeypatch):
    class _Explota(_ChatwootDeMentira):
        def actualizar_nombre_contacto(self, contacto_id, nombre):
            raise RuntimeError("Chatwoot no contestó")

    monkeypatch.setattr(herramientas, "_chatwoot_del_config", lambda config: _Explota())

    resultado = actualizar_ficha_cliente.invoke(
        {"nombre": "Jesús", "nota": ""}, config=_config()
    )

    assert "no se pudo guardar" in resultado.lower()


def test_actualizar_ficha_esta_en_la_lista_de_herramientas():
    assert actualizar_ficha_cliente in HERRAMIENTAS


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


def test_franjas_ocupadas_un_dia_cerrado_no_consulta_el_calendario(monkeypatch):
    """Antes de esto, el modelo se enteraba de que el día estaba cerrado
    recién al intentar anotar_reserva — acá se lo decimos de una."""
    cal = _CalendarioDeMentira()
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    _con_horario(monkeypatch, cerrados="domingo")

    # 2026-09-13 es domingo.
    resultado = franjas_ocupadas.invoke({"fecha": "2026-09-13"}, config=_config())

    assert "cerrado" in resultado.lower()


def test_franjas_ocupadas_avisa_el_horario_de_atencion(monkeypatch):
    """Sin este aviso, el modelo puede ofrecer un horario que el calendario
    tiene libre pero que cae fuera de atención (el corte de un horario
    partido, por ejemplo)."""
    cal = _CalendarioDeMentira(ocupado=[])
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)
    _con_horario(monkeypatch, franjas="09:00-15:00,18:00-23:00")

    resultado = franjas_ocupadas.invoke({"fecha": "2026-09-12"}, config=_config())

    assert "09:00 a 15:00" in resultado
    assert "18:00 a 23:00" in resultado


def test_franjas_ocupadas_sin_horario_configurado_no_agrega_nada_de_mas(monkeypatch):
    cal = _CalendarioDeMentira(ocupado=[])
    monkeypatch.setattr(herramientas, "_calendario_del_config", lambda config: cal)

    resultado = franjas_ocupadas.invoke({"fecha": "2026-09-12"}, config=_config())

    assert resultado == "No hay nada ocupado en el calendario el 2026-09-12."


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

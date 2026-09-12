"""Pruebas de /reservas/{aprobar|rechazar}: el link que abre el negocio para
resolver una reserva "tentative" (RESERVA_REQUIERE_APROBACION). No salen a
internet ni gastan tokens.

    pytest
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agente import aprobacion  # noqa: E402
from agente.calendario import ErrorDeCalendario  # noqa: E402
from agente.web import webhook as webhook_modulo  # noqa: E402

from test_agente import agente_falso  # noqa: E402
from test_chatwoot import ChatwootFalso, cliente  # noqa: E402


class _CalendarioDeMentira:
    """Alcanza con estos métodos: son los únicos que usa la ruta.

    `eventos` empieza con todo en "tentative" (el estado normal de una
    reserva a la espera de aprobación) para que los tests que no les
    importa este detalle no tengan que armarlo a mano.
    """

    def __init__(self) -> None:
        self.aprobados: list[str] = []
        self.cancelados: list[str] = []
        self.eventos: dict[str, dict] = {}

    def obtener_evento(self, evento_id):
        if evento_id not in self.eventos:
            self.eventos[evento_id] = {"status": "tentative"}
        if self.eventos[evento_id] is None:
            # Simula el 404/410 de Calendar para un evento ya borrado.
            raise ErrorDeCalendario("no existe", codigo=404)
        return self.eventos[evento_id]

    def aprobar_evento(self, evento_id):
        self.aprobados.append(evento_id)
        self.eventos[evento_id] = {"status": "confirmed"}

    def cancelar_evento(self, evento_id):
        self.cancelados.append(evento_id)
        self.eventos[evento_id] = None


class _CalendarioLenta(_CalendarioDeMentira):
    """Igual que la de mentira, pero `aprobar_evento`/`cancelar_evento`
    tardan un poco — como el PATCH/DELETE real contra la API de Calendar.

    A propósito, para agrandar la ventana de la carrera en
    test_dos_aprobar_casi_simultaneos_no_repiten_el_whatsapp. La demora
    tiene que estar ACÁ, no en `obtener_evento`: el momento vulnerable es
    entre "leí tentative" y "ya escribí confirmed" — demorar la LECTURA
    solo demuestra que dos lecturas pueden ser concurrentes, no que el
    candado hace falta (verificado a mano: con la demora en la lectura, la
    escritura de la primera solicitud termina tan rápido que la segunda
    nunca alcanza a leer el estado viejo, y el test "pasa" sin que el
    candado haga nada — un falso negativo).
    """

    def aprobar_evento(self, evento_id):
        time.sleep(0.1)
        super().aprobar_evento(evento_id)

    def cancelar_evento(self, evento_id):
        time.sleep(0.1)
        super().cancelar_evento(evento_id)


def _armar(secreto="shhh"):
    """Un cliente de pruebas con Chatwoot y calendario de mentira adentro."""
    canal = ChatwootFalso()
    calendario = _CalendarioDeMentira()
    agente = agente_falso(["no debería usarse"])
    agente.config.reserva_secreto = secreto

    web = cliente(canal, agente, calendario=calendario)
    return web, canal, calendario


def _etiqueta_puesta(canal) -> str | None:
    """La última etiqueta que se mandó a poner (el POST a /labels)."""
    pedidos = [
        l["datos"]["labels"]
        for l in canal.llamadas
        if l["camino"].endswith("/labels") and l["metodo"] == "POST"
    ]
    return pedidos[-1][0] if pedidos else None


def test_aprobar_con_token_valido_confirma_y_avisa():
    web, canal, calendario = _armar()
    token = aprobacion.firmar("shhh", "42", "evento-1")

    with web as w:
        respuesta = w.get(f"/reservas/aprobar/42/evento-1?token={token}")

    assert respuesta.status_code == 200
    assert calendario.aprobados == ["evento-1"]
    assert "confirmado" in canal.envios()[0].lower()
    assert _etiqueta_puesta(canal) == "reserva-confirmada"


def test_aprobar_registra_la_visita(monkeypatch):
    """Recién ACÁ se registra la visita para las estadísticas — no cuando
    se creó la reserva "tentative" (ver herramientas.py, anotar_reserva)."""
    canal = ChatwootFalso(contacto_id="99")
    calendario = _CalendarioDeMentira()
    calendario.eventos["evento-1"] = {
        "status": "tentative",
        "summary": "Ana (1p)",
        "description": (
            "Nombre: Ana\nPersonas: 1\nFecha: 2026-09-14\nHora: 09:00\n"
            "Teléfono: +351900000000\nAclaración: Dolor de espalda\n"
            "Conversación: 42"
        ),
        "start": {"dateTime": "2026-09-14T09:00:00+01:00"},
    }
    agente = agente_falso(["no debería usarse"])
    agente.config.reserva_secreto = "shhh"
    web = cliente(canal, agente, calendario=calendario)

    llamadas = []
    monkeypatch.setattr(
        webhook_modulo.visitas,
        "registrar_visita",
        lambda *a, **k: llamadas.append((a, k)),
    )

    token = aprobacion.firmar("shhh", "42", "evento-1")
    with web as w:
        w.get(f"/reservas/aprobar/42/evento-1?token={token}")

    assert len(llamadas) == 1
    args, kwargs = llamadas[0]
    assert args[:4] == (agente.config.postgres_dsn, "99", "2026-09-14", "09:00")
    assert kwargs.get("nombre") == "Ana"
    assert kwargs.get("telefono") == "+351900000000"
    assert kwargs.get("motivo") == "Dolor de espalda"


def test_aprobar_sin_telefono_ni_aclaracion_los_manda_vacios(monkeypatch):
    """La descripción del turno no siempre tiene esas líneas — son
    opcionales en anotar_reserva()."""
    canal = ChatwootFalso(contacto_id="99")
    calendario = _CalendarioDeMentira()
    calendario.eventos["evento-1"] = {
        "status": "tentative",
        "summary": "Ana (1p)",
        "description": "Nombre: Ana\nPersonas: 1\nFecha: 2026-09-14\nHora: 09:00",
        "start": {"dateTime": "2026-09-14T09:00:00+01:00"},
    }
    agente = agente_falso(["no debería usarse"])
    agente.config.reserva_secreto = "shhh"
    web = cliente(canal, agente, calendario=calendario)

    llamadas = []
    monkeypatch.setattr(
        webhook_modulo.visitas,
        "registrar_visita",
        lambda *a, **k: llamadas.append((a, k)),
    )

    token = aprobacion.firmar("shhh", "42", "evento-1")
    with web as w:
        w.get(f"/reservas/aprobar/42/evento-1?token={token}")

    _, kwargs = llamadas[0]
    assert kwargs.get("telefono") == ""
    assert kwargs.get("motivo") == ""


def test_rechazar_no_registra_ninguna_visita(monkeypatch):
    canal = ChatwootFalso(contacto_id="99")
    calendario = _CalendarioDeMentira()
    calendario.eventos["evento-1"] = {
        "status": "tentative",
        "summary": "Ana (1p)",
        "start": {"dateTime": "2026-09-14T09:00:00+01:00"},
    }
    agente = agente_falso(["no debería usarse"])
    agente.config.reserva_secreto = "shhh"
    web = cliente(canal, agente, calendario=calendario)

    llamadas = []
    monkeypatch.setattr(
        webhook_modulo.visitas,
        "registrar_visita",
        lambda *a, **k: llamadas.append((a, k)),
    )

    token = aprobacion.firmar("shhh", "42", "evento-1")
    with web as w:
        w.get(f"/reservas/rechazar/42/evento-1?token={token}")

    assert llamadas == []


def test_rechazar_con_token_valido_cancela_y_avisa():
    web, canal, calendario = _armar()
    token = aprobacion.firmar("shhh", "42", "evento-1")

    with web as w:
        respuesta = w.get(f"/reservas/rechazar/42/evento-1?token={token}")

    assert respuesta.status_code == 200
    assert calendario.cancelados == ["evento-1"]
    assert "no vamos a poder" in canal.envios()[0].lower()
    assert _etiqueta_puesta(canal) == "reserva-rechazada"


def test_token_invalido_no_hace_nada():
    web, canal, calendario = _armar()

    with web as w:
        respuesta = w.get("/reservas/aprobar/42/evento-1?token=cualquier-cosa")

    assert respuesta.status_code == 403
    assert calendario.aprobados == []
    assert canal.envios() == []


def test_token_de_otra_reserva_no_sirve():
    """La firma es por reserva puntual, no genérica."""
    web, canal, calendario = _armar()
    token = aprobacion.firmar("shhh", "42", "evento-1")

    with web as w:
        respuesta = w.get(f"/reservas/aprobar/42/evento-2?token={token}")

    assert respuesta.status_code == 403
    assert calendario.aprobados == []


def test_aprobar_dos_veces_no_repite_el_whatsapp():
    """Reproducido en producción: Chatwoot en iPhone precarga el link para
    armar una vista previa (un GET sin que la persona lo haya tocado) y
    aprueba solo; el clic real de la persona era el segundo GET, sobre un
    evento que ya no estaba "tentative"."""
    web, canal, calendario = _armar()
    token = aprobacion.firmar("shhh", "42", "evento-1")

    with web as w:
        primera = w.get(f"/reservas/aprobar/42/evento-1?token={token}")
        segunda = w.get(f"/reservas/aprobar/42/evento-1?token={token}")

    assert primera.status_code == 200
    assert segunda.status_code == 200
    assert "ya estaba aprobada" in segunda.text.lower()
    assert calendario.aprobados == ["evento-1"], "no se vuelve a aprobar"
    assert len(canal.envios()) == 1, "no se manda el WhatsApp dos veces"


def test_dos_aprobar_casi_simultaneos_no_repiten_el_whatsapp():
    """Reproducido en vivo: un solo clic en el link desde la app de Chatwoot
    en el celular, y llegaron DOS avisos de "tu turno quedó confirmado" —
    dos GET casi al mismo tiempo (la vista previa del link que arma la app +
    el clic real de la persona) pasaron el chequeo de "¿ya está confirmado?"
    antes de que cualquiera de los dos terminara de escribirlo.
    `test_aprobar_dos_veces_no_repite_el_whatsapp` ya cubre el caso
    SECUENCIAL (un clic después del otro); este cubre el caso simultáneo, que
    es el que de verdad pasó — por eso `_CalendarioLenta`, para agrandar a
    propósito la ventana de la carrera y que el test falle de verdad si el
    candado se saca alguna vez."""
    import httpx

    from agente.web.webhook import crear_app

    canal = ChatwootFalso()
    calendario = _CalendarioLenta()
    agente = agente_falso(["no debería usarse"])
    agente.config.reserva_secreto = "shhh"

    app = crear_app(agente.config, agente=agente, canal=canal, calendario=calendario)
    token = aprobacion.firmar("shhh", "42", "evento-1")
    url = f"/reservas/aprobar/42/evento-1?token={token}"

    async def correr():
        transporte = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transporte, base_url="http://test") as c:
            return await asyncio.gather(c.get(url), c.get(url))

    respuestas = asyncio.run(correr())

    assert [r.status_code for r in respuestas] == [200, 200]
    assert calendario.aprobados == ["evento-1"], "no se aprueba dos veces"
    assert len(canal.envios()) == 1, "no se manda el WhatsApp dos veces"


def test_rechazar_dos_veces_no_repite_el_whatsapp():
    web, canal, calendario = _armar()
    token = aprobacion.firmar("shhh", "42", "evento-1")

    with web as w:
        primera = w.get(f"/reservas/rechazar/42/evento-1?token={token}")
        segunda = w.get(f"/reservas/rechazar/42/evento-1?token={token}")

    assert primera.status_code == 200
    assert segunda.status_code == 200
    assert "ya había sido rechazada" in segunda.text.lower()
    assert calendario.cancelados == ["evento-1"]
    assert len(canal.envios()) == 1


def test_aprobar_algo_ya_rechazado_no_lo_revive():
    web, canal, calendario = _armar()
    token_rechazar = aprobacion.firmar("shhh", "42", "evento-1")
    token_aprobar = aprobacion.firmar("shhh", "42", "evento-1")

    with web as w:
        w.get(f"/reservas/rechazar/42/evento-1?token={token_rechazar}")
        respuesta = w.get(f"/reservas/aprobar/42/evento-1?token={token_aprobar}")

    assert respuesta.status_code == 200
    assert "ya no existe" in respuesta.text.lower()
    assert calendario.aprobados == []
    assert len(canal.envios()) == 1, "solo el aviso del rechazo"


def test_accion_desconocida_da_404():
    web, canal, calendario = _armar()
    token = aprobacion.firmar("shhh", "42", "evento-1")

    with web as w:
        respuesta = w.get(f"/reservas/borrar/42/evento-1?token={token}")

    assert respuesta.status_code == 404


def test_sin_calendario_conectado_da_404():
    canal = ChatwootFalso()
    agente = agente_falso(["no debería usarse"])
    agente.config.reserva_secreto = "shhh"

    with cliente(canal, agente, calendario=None) as w:
        token = aprobacion.firmar("shhh", "42", "evento-1")
        respuesta = w.get(f"/reservas/aprobar/42/evento-1?token={token}")

    assert respuesta.status_code == 404


def test_sin_reserva_secreto_configurado_da_404():
    web, canal, calendario = _armar(secreto="")

    with web as w:
        respuesta = w.get("/reservas/aprobar/42/evento-1?token=algo")

    assert respuesta.status_code == 404
    assert calendario.aprobados == []


# -- _campo_de_descripcion -------------------------------------------------------


def test_campo_de_descripcion_encuentra_la_linea():
    descripcion = "Nombre: Ana\nTeléfono: +351900000000\nAclaración: Dolor"
    assert webhook_modulo._campo_de_descripcion(descripcion, "Teléfono") == "+351900000000"
    assert webhook_modulo._campo_de_descripcion(descripcion, "Aclaración") == "Dolor"


def test_campo_de_descripcion_vacio_si_no_esta():
    assert webhook_modulo._campo_de_descripcion("Nombre: Ana", "Teléfono") == ""


# -- Varios profesionales: _calendario_para_aprobacion ---------------------------
#
# Fase 4 (ver AGENTS.md, "Varios profesionales"). `Calendario` de verdad
# necesita una clave RSA real en credencial_json — se reemplaza acá por una
# clase de mentira que solo anota con qué se la construyó, mismo criterio
# que test_recordatorios.py y _construir_calendario en test_herramientas.py.


class _CalendarioConstruido:
    def __init__(self, calendario_id, credencial_json, zona_horaria) -> None:
        self.calendario_id = calendario_id
        self.credencial_json = credencial_json
        self.zona_horaria = zona_horaria


def test_calendario_para_aprobacion_sin_profesionales_usa_el_legacy(monkeypatch):
    legacy = object()
    config = agente_falso(["no debería usarse"]).config

    assert webhook_modulo._calendario_para_aprobacion(config, legacy, "") is legacy


def test_calendario_para_aprobacion_con_profesionales_arma_el_de_ese_nombre(monkeypatch):
    monkeypatch.setattr(webhook_modulo, "Calendario", _CalendarioConstruido)
    agente = agente_falso(["no debería usarse"])
    agente.config.profesionales = {"Dra. García": "cal-garcia", "Dr. Pérez": "cal-perez"}
    agente.config.google_service_account_json = "cuenta-de-mentira"

    resultado = webhook_modulo._calendario_para_aprobacion(
        agente.config, None, "dra. garcía"  # sin importar mayúsculas ni espacios
    )

    assert isinstance(resultado, _CalendarioConstruido)
    assert resultado.calendario_id == "cal-garcia"


def test_calendario_para_aprobacion_con_profesionales_y_nombre_que_no_coincide():
    agente = agente_falso(["no debería usarse"])
    agente.config.profesionales = {"Dra. García": "cal-garcia"}
    agente.config.google_service_account_json = "cuenta-de-mentira"

    assert webhook_modulo._calendario_para_aprobacion(agente.config, None, "Dr. Nadie") is None


def test_calendario_para_aprobacion_con_profesionales_sin_credencial():
    agente = agente_falso(["no debería usarse"])
    agente.config.profesionales = {"Dra. García": "cal-garcia"}
    agente.config.google_service_account_json = ""

    assert webhook_modulo._calendario_para_aprobacion(agente.config, None, "Dra. García") is None


# -- Varios profesionales: la ruta entera, con la agenda correcta según el link ------


def test_aprobar_con_profesional_usa_la_agenda_correcta(monkeypatch):
    canal = ChatwootFalso()
    agente = agente_falso(["no debería usarse"])
    agente.config.reserva_secreto = "shhh"
    agente.config.profesionales = {"Dra. García": "cal-garcia", "Dr. Pérez": "cal-perez"}

    cal_garcia = _CalendarioDeMentira()
    cal_perez = _CalendarioDeMentira()
    monkeypatch.setattr(
        webhook_modulo,
        "_calendario_para_aprobacion",
        lambda config, legacy, profesional: {
            "Dra. García": cal_garcia,
            "Dr. Pérez": cal_perez,
        }.get(profesional),
    )

    web = cliente(canal, agente, calendario=None)
    token = aprobacion.firmar("shhh", "42", "evento-1", "Dra. García")

    with web as w:
        respuesta = w.get(
            f"/reservas/aprobar/42/evento-1?token={token}&profesional=Dra.%20Garc%C3%ADa"
        )

    assert respuesta.status_code == 200
    assert cal_garcia.aprobados == ["evento-1"]
    assert cal_perez.aprobados == [], "no se toca la agenda del otro profesional"


def test_aprobar_con_profesional_equivocado_en_la_url_da_403(monkeypatch):
    """El profesional viaja en la firma: cambiarlo en la URL invalida el token."""
    canal = ChatwootFalso()
    agente = agente_falso(["no debería usarse"])
    agente.config.reserva_secreto = "shhh"
    agente.config.profesionales = {"Dra. García": "cal-garcia", "Dr. Pérez": "cal-perez"}

    cal_garcia = _CalendarioDeMentira()
    cal_perez = _CalendarioDeMentira()
    monkeypatch.setattr(
        webhook_modulo,
        "_calendario_para_aprobacion",
        lambda config, legacy, profesional: {
            "Dra. García": cal_garcia,
            "Dr. Pérez": cal_perez,
        }.get(profesional),
    )

    web = cliente(canal, agente, calendario=None)
    # Firmado para la Dra. García, pero la URL pide con el Dr. Pérez.
    token = aprobacion.firmar("shhh", "42", "evento-1", "Dra. García")

    with web as w:
        respuesta = w.get(f"/reservas/aprobar/42/evento-1?token={token}&profesional=Dr.%20P%C3%A9rez")

    assert respuesta.status_code == 403
    assert cal_perez.aprobados == []


def test_aprobar_con_profesionales_y_nombre_que_no_coincide_da_404(monkeypatch):
    canal = ChatwootFalso()
    agente = agente_falso(["no debería usarse"])
    agente.config.reserva_secreto = "shhh"
    agente.config.profesionales = {"Dra. García": "cal-garcia"}

    monkeypatch.setattr(
        webhook_modulo, "_calendario_para_aprobacion", lambda config, legacy, profesional: None
    )

    web = cliente(canal, agente, calendario=None)
    token = aprobacion.firmar("shhh", "42", "evento-1", "Dr. Nadie")

    with web as w:
        respuesta = w.get(f"/reservas/aprobar/42/evento-1?token={token}&profesional=Dr.%20Nadie")

    assert respuesta.status_code == 404


# -- _mensaje_en_idioma_de_conversacion -------------------------------------------
#
# El bug real: una conversación entera en portugués, y el aviso de "tu turno
# quedó confirmado" salía en español — porque ese aviso no pasa por el
# agente, es un texto fijo que dispara /reservas/{accion} directo.


def test_mensaje_en_idioma_sin_historial_devuelve_el_texto_tal_cual():
    """Conversación que nunca le habló al agente (no debería pasar en la
    práctica, pero el helper no tiene por qué explotar): sin nada de
    historial no hay de dónde sacar el idioma, así que se manda el texto
    fijo tal cual viene — y sin gastar un llamado al modelo (la respuesta
    "no debería usarse" no se toca)."""
    agente = agente_falso(["no debería usarse"])

    resultado = webhook_modulo._mensaje_en_idioma_de_conversacion(
        agente, "sin-historial", "Tu turno quedó confirmado."
    )

    assert resultado == "Tu turno quedó confirmado."


def test_mensaje_en_idioma_traduce_usando_el_historial_de_la_conversacion():
    """Con historial en portugués, el helper le pide al modelo que traduzca
    — y devuelve lo que el modelo conteste, sin tocar la memoria real de la
    conversación (agente.modelo, no agente.grafo)."""
    agente = agente_falso(
        ["Claro, deixe-me ver os horários disponíveis.", "O seu turno ficou confirmado!"]
    )
    agente.responder("Ola, queria marcar uma consulta", "42")

    resultado = webhook_modulo._mensaje_en_idioma_de_conversacion(
        agente, "42", "Tu turno quedó confirmado."
    )

    assert resultado == "O seu turno ficou confirmado!"


def test_mensaje_en_idioma_si_el_modelo_falla_devuelve_el_texto_tal_cual():
    """Sin internet, sin cupo, lo que sea: mejor mandar el aviso en español
    que no mandar nada."""
    agente = agente_falso(["Claro, deixe-me ver os horários disponíveis."])
    agente.responder("Ola, queria marcar uma consulta", "42")  # consume la única respuesta

    resultado = webhook_modulo._mensaje_en_idioma_de_conversacion(
        agente, "42", "Tu turno quedó confirmado."
    )

    assert resultado == "Tu turno quedó confirmado."

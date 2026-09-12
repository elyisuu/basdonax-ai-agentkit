"""Pruebas del canal de Chatwoot. No salen a internet ni gastan tokens.

La API de Chatwoot se reemplaza por una de mentira que anota lo que se le
pidió. Lo que se prueba es lo nuestro: qué mensajes se contestan, cuáles no,
cómo se junta una ráfaga y qué sale para el otro lado.

El test más importante de este archivo es
`test_no_se_contesta_a_si_mismo`: sin ese filtro, cada respuesta del agente
vuelve como un mensaje nuevo y el bot se responde solo para siempre,
gastando tokens en cada vuelta.

    pytest
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agente.canales import chatwoot as chatwoot_modulo  # noqa: E402
from agente.canales.buffer import BufferDeMensajes  # noqa: E402
from agente.canales.chatwoot import Chatwoot, ErrorDeChatwoot, _tipo_de_mensaje  # noqa: E402


@pytest.fixture(autouse=True)
def _sin_pausas_reales(monkeypatch):
    """enviar() espera de verdad (time.sleep) entre globo y globo — acá se
    saltea para no frenar la suite en cada test que manda más de uno."""
    monkeypatch.setattr(chatwoot_modulo.time, "sleep", lambda segundos: None)


def evento(
    texto="hola",
    conversacion=12,
    id_mensaje=1,
    tipo="incoming",
    privado=False,
    etiquetas=None,
    nombre="message_created",
    adjuntos=None,
) -> dict:
    """Un mensaje como lo manda el webhook de Chatwoot.

    `adjuntos`: para simular un audio, una foto o un documento. Alcanza con
    que la lista no esté vacía — no nos importa el contenido real.
    """
    cuerpo = {
        "event": nombre,
        "id": id_mensaje,
        "content": texto,
        "message_type": tipo,
        "private": privado,
        "conversation": {
            "id": conversacion,
            "status": "open",
            "labels": [] if etiquetas is None else etiquetas,
        },
        "account": {"id": 1},
        "inbox": {"id": 6, "name": "YT"},
    }
    if adjuntos is not None:
        cuerpo["attachments"] = adjuntos
    return cuerpo


class ChatwootFalso(Chatwoot):
    """El canal, pero con la API de mentira. Anota todo lo que se mandó."""

    def __init__(self, etiqueta_humano="humano", etiquetas_remotas=None, contacto_id=None):
        super().__init__(
            url="https://chatwoot.ejemplo.com/",
            token="token-falso",
            cuenta_id=1,
            etiqueta_humano=etiqueta_humano,
        )
        self.llamadas: list[dict] = []
        self._etiquetas_remotas = etiquetas_remotas or []
        self._contacto_id = contacto_id

    def _api(self, metodo, camino, datos=None):
        self.llamadas.append({"metodo": metodo, "camino": camino, "datos": datos})

        if camino.endswith("/labels"):
            return {"payload": self._etiquetas_remotas}
        if metodo == "GET" and camino.startswith("conversations/"):
            if self._contacto_id is None:
                return {}
            return {"meta": {"sender": {"id": self._contacto_id}}}
        return {"id": 99}

    def envios(self) -> list[str]:
        """Solo los mensajes que salieron para la persona."""
        return [
            l["datos"]["content"]
            for l in self.llamadas
            if l["camino"].endswith("/messages") and l["datos"]
        ]


# -- Traducir lo que llega ----------------------------------------------------


def test_traduce_un_mensaje_normal():
    entrante = ChatwootFalso().traducir(evento("¿que clima hace?", conversacion=77, id_mensaje=42))

    assert entrante is not None
    assert entrante.texto == "¿que clima hace?"
    assert entrante.conversacion == "77", "el id de conversación es el thread_id"
    assert entrante.identificador == "42"


def test_el_id_de_conversacion_va_como_texto():
    """Es el thread_id de LangGraph, y ahí un 12 y un "12" no son lo mismo."""
    entrante = ChatwootFalso().traducir(evento(conversacion=12))
    assert isinstance(entrante.conversacion, str)


@pytest.mark.parametrize(
    "nombre",
    ["conversation_created", "conversation_status_changed", "webwidget_triggered"],
)
def test_los_otros_eventos_se_dejan_pasar(nombre):
    """Chatwoot manda muchas cosas por el mismo webhook, no solo mensajes."""
    assert ChatwootFalso().traducir(evento(nombre=nombre)) is None


def test_un_mensaje_sin_texto_ni_adjunto_se_deja_pasar():
    """Sin texto y sin adjunto no hay nada que contestar — pasa un evento
    vacío de verdad, no un audio o una foto (ver el test de abajo)."""
    assert ChatwootFalso().traducir(evento(texto="")) is None
    assert ChatwootFalso().traducir(evento(texto="   ")) is None


def test_un_adjunto_sin_texto_se_traduce_para_contestar_algo():
    """Un audio, una foto, un documento sin nada escrito: el modelo no
    puede leer eso, pero la persona espera que le contesten igual (ver
    MENSAJE_ADJUNTO_SIN_TEXTO en webhook.py) — antes esto se tiraba como
    si nunca hubiera llegado nada."""
    entrante = ChatwootFalso().traducir(evento(texto="", adjuntos=[{"file_type": "audio"}]))

    assert entrante is not None
    assert entrante.texto == ""
    assert entrante.es_adjunto_sin_texto is True


def test_una_foto_con_epigrafe_es_un_mensaje_normal():
    """Si mandó texto junto con la foto, hay algo real que leer — no es el
    caso del adjunto mudo."""
    entrante = ChatwootFalso().traducir(
        evento(texto="¿este ejercicio es para la espalda?", adjuntos=[{"file_type": "image"}])
    )

    assert entrante.es_adjunto_sin_texto is False
    assert entrante.texto == "¿este ejercicio es para la espalda?"


# -- Qué se contesta y qué no -------------------------------------------------


def test_no_se_contesta_a_si_mismo():
    """EL test de este archivo.

    Cada respuesta que manda el agente vuelve por el webhook como un evento
    nuevo, pero marcada como `outgoing`. Sin este filtro el agente la lee, la
    contesta, esa respuesta vuelve otra vez… y así para siempre, gastando
    tokens en cada vuelta.
    """
    canal = ChatwootFalso()
    entrante = canal.traducir(evento("mi propia respuesta", tipo="outgoing"))

    assert canal.deberia_responder(entrante) is False


def test_no_contesta_las_notas_privadas():
    """Una nota privada es para el equipo. Contestar ahí la manda al cliente."""
    canal = ChatwootFalso()
    entrante = canal.traducir(evento("ojo con este cliente", privado=True))

    assert canal.deberia_responder(entrante) is False


def test_no_contesta_dos_veces_el_mismo_mensaje():
    """Chatwoot reintenta el webhook si no le contestamos a tiempo."""
    canal = ChatwootFalso()
    entrante = canal.traducir(evento(id_mensaje=7))

    assert canal.deberia_responder(entrante) is True
    assert canal.deberia_responder(entrante) is False, "la segunda vez ya no"


def test_la_etiqueta_apaga_el_bot():
    """El traspaso a una persona: se pone la etiqueta y el bot se calla."""
    canal = ChatwootFalso()
    entrante = canal.traducir(evento(etiquetas=["humano"]))

    assert canal.deberia_responder(entrante) is False


def test_la_etiqueta_no_distingue_mayusculas():
    canal = ChatwootFalso()
    assert canal.deberia_responder(canal.traducir(evento(etiquetas=["Humano"]))) is False


def test_otras_etiquetas_no_lo_apagan():
    canal = ChatwootFalso()
    entrante = canal.traducir(evento(etiquetas=["ventas", "urgente"]))

    assert canal.deberia_responder(entrante) is True


def test_si_el_evento_no_trae_etiquetas_se_las_pregunta():
    """Dar por hecho que no hay ninguna sería hablar arriba de una persona."""
    canal = ChatwootFalso(etiquetas_remotas=["humano"])
    crudo = evento()
    del crudo["conversation"]["labels"]

    assert canal.deberia_responder(canal.traducir(crudo)) is False
    assert any(l["camino"].endswith("/labels") for l in canal.llamadas)


def test_un_mensaje_normal_se_contesta():
    canal = ChatwootFalso()
    assert canal.deberia_responder(canal.traducir(evento())) is True


@pytest.mark.parametrize(
    "crudo,esperado",
    [({"message_type": 0}, "incoming"), ({"message_type": 1}, "outgoing")],
)
def test_el_tipo_tambien_se_entiende_como_numero(crudo, esperado):
    """Según la versión, Chatwoot lo manda como texto o como número."""
    assert _tipo_de_mensaje(crudo) == esperado


# -- Notas y etiquetas propias (no las de deberia_responder) -----------------


def test_anotar_deja_una_nota_privada():
    canal = ChatwootFalso()

    canal.anotar("12", "Reserva nueva")

    nota = [l for l in canal.llamadas if l["camino"].endswith("/messages")][0]
    assert nota["camino"] == "conversations/12/messages"
    assert nota["datos"]["content"] == "Reserva nueva"
    assert nota["datos"]["private"] is True, "si no, la nota le llega al cliente"
    assert nota["datos"]["message_type"] == "outgoing"


def test_etiquetar_no_pisa_las_etiquetas_que_ya_habia():
    """La API de Chatwoot reemplaza todo el conjunto: hay que mandar la unión."""
    canal = ChatwootFalso(etiquetas_remotas=["vip"])

    canal.etiquetar("12", "reserva-nueva")

    # La primera llamada a /labels es el GET que pregunta cuáles ya tenía
    # (_etiquetas_de); la que importa acá es el POST que las reemplaza.
    pedido = [
        l for l in canal.llamadas if l["camino"].endswith("/labels") and l["metodo"] == "POST"
    ][0]
    assert sorted(pedido["datos"]["labels"]) == ["reserva-nueva", "vip"]


def test_etiquetar_no_le_importan_las_mayusculas():
    canal = ChatwootFalso(etiquetas_remotas=["Vip"])

    canal.etiquetar("12", "Reserva-Nueva")

    pedido = [
        l for l in canal.llamadas if l["camino"].endswith("/labels") and l["metodo"] == "POST"
    ][0]
    assert sorted(pedido["datos"]["labels"]) == ["reserva-nueva", "vip"]


# -- La ficha del contacto -----------------------------------------------------


def test_contacto_de_lee_el_sender_de_la_conversacion():
    canal = ChatwootFalso(contacto_id=42)

    assert canal.contacto_de("12") == "42"


def test_contacto_de_none_si_no_hay_sender():
    canal = ChatwootFalso()  # sin contacto_id: la API de mentira no trae "meta"

    assert canal.contacto_de("12") is None


def test_contacto_de_none_si_la_api_revienta():
    class ChatwootQueRevienta(ChatwootFalso):
        def _api(self, metodo, camino, datos=None):
            raise ErrorDeChatwoot("Chatwoot no contesta")

    assert ChatwootQueRevienta().contacto_de("12") is None


def test_actualizar_nombre_contacto():
    canal = ChatwootFalso()

    canal.actualizar_nombre_contacto("42", "Jesús")

    pedido = canal.llamadas[-1]
    assert pedido == {"metodo": "PATCH", "camino": "contacts/42", "datos": {"name": "Jesús"}}


def test_agregar_nota_contacto():
    canal = ChatwootFalso()

    canal.agregar_nota_contacto("42", "Prefiere que le escriban en portugués")

    pedido = canal.llamadas[-1]
    assert pedido == {
        "metodo": "POST",
        "camino": "contacts/42/notes",
        "datos": {"content": "Prefiere que le escriban en portugués"},
    }


# -- Retención de datos (retencion.py): listar y borrar notas de contacto -----


def test_listar_notas_contacto_devuelve_el_payload():
    class ChatwootConNotas(ChatwootFalso):
        def _api(self, metodo, camino, datos=None):
            super()._api(metodo, camino, datos)
            return {"payload": [{"id": 1, "created_at": 123}, {"id": 2, "created_at": 456}]}

    notas = ChatwootConNotas().listar_notas_contacto("42")

    assert notas == [{"id": 1, "created_at": 123}, {"id": 2, "created_at": 456}]


def test_listar_notas_contacto_sin_payload_es_lista_vacia():
    canal = ChatwootFalso()  # _api de mentira devuelve {"id": 99}, sin "payload"

    assert canal.listar_notas_contacto("42") == []


def test_borrar_nota_contacto():
    canal = ChatwootFalso()

    canal.borrar_nota_contacto("42", 7)

    pedido = canal.llamadas[-1]
    assert pedido == {"metodo": "DELETE", "camino": "contacts/42/notes/7", "datos": None}


def test_listar_contactos_devuelve_el_payload():
    class ChatwootConContactos(ChatwootFalso):
        def _api(self, metodo, camino, datos=None):
            super()._api(metodo, camino, datos)
            return {"payload": [{"id": 1}, {"id": 2}]}

    contactos = ChatwootConContactos().listar_contactos(1)

    assert contactos == [{"id": 1}, {"id": 2}]


def test_listar_contactos_manda_la_pagina_pedida():
    canal = ChatwootFalso()

    canal.listar_contactos(3)

    pedido = canal.llamadas[-1]
    assert pedido == {"metodo": "GET", "camino": "contacts?page=3", "datos": None}


def test_listar_contactos_sin_payload_es_lista_vacia():
    canal = ChatwootFalso()

    assert canal.listar_contactos(1) == []


# -- Lo que sale --------------------------------------------------------------


def test_envia_cada_mensaje_por_separado():
    canal = ChatwootFalso()

    canal.enviar("12", ["primero", "segundo"])

    assert canal.envios() == ["primero", "segundo"]


def test_lo_que_sale_va_marcado_como_outgoing():
    """Si no, Chatwoot no lo empuja a WhatsApp y queda solo en la bandeja."""
    canal = ChatwootFalso()

    canal.enviar("12", ["hola"])

    envio = [l for l in canal.llamadas if l["camino"].endswith("/messages")][0]
    assert envio["datos"]["message_type"] == "outgoing"
    assert envio["camino"] == "conversations/12/messages"


def test_no_manda_mensajes_vacios():
    canal = ChatwootFalso()

    canal.enviar("12", ["hola", "   ", ""])

    assert canal.envios() == ["hola"]


def test_pausa_entre_globos_pero_no_antes_ni_despues(monkeypatch):
    """Sin esto WhatsApp puede entregar los globos desordenados — pasó de
    verdad (ver AGENTS.md). La pausa va SOLO entre mensajes."""
    canal = ChatwootFalso()
    pausas = []
    monkeypatch.setattr(chatwoot_modulo.time, "sleep", lambda segundos: pausas.append(segundos))

    canal.enviar("12", ["primero", "segundo", "tercero"])

    assert pausas == [chatwoot_modulo.PAUSA_ENTRE_GLOBOS, chatwoot_modulo.PAUSA_ENTRE_GLOBOS]


def test_un_solo_mensaje_no_espera_nada(monkeypatch):
    canal = ChatwootFalso()
    pausas = []
    monkeypatch.setattr(chatwoot_modulo.time, "sleep", lambda segundos: pausas.append(segundos))

    canal.enviar("12", ["el único"])

    assert pausas == []


def test_los_mensajes_vacios_no_cuentan_para_la_pausa(monkeypatch):
    """Dos mensajes con contenido real y uno vacío en el medio: sigue
    siendo una sola pausa, no dos — el vacío ni se manda."""
    canal = ChatwootFalso()
    pausas = []
    monkeypatch.setattr(chatwoot_modulo.time, "sleep", lambda segundos: pausas.append(segundos))

    canal.enviar("12", ["primero", "   ", "segundo"])

    assert pausas == [chatwoot_modulo.PAUSA_ENTRE_GLOBOS]


def test_la_barra_final_de_la_url_no_se_duplica():
    """Con "...com//api/v1" Chatwoot devuelve 404 y no se entiende por qué."""
    canal = ChatwootFalso()
    assert canal.url == "https://chatwoot.ejemplo.com"


def test_el_escribiendo_no_voltea_la_respuesta(monkeypatch):
    """Es cosmético: si falla, la respuesta tiene que salir igual."""
    canal = ChatwootFalso()

    def explota(*a, **k):
        raise ConnectionError("se cayó")

    monkeypatch.setattr(canal, "_api", explota)
    canal.escribiendo("12")  # no tiene que levantar nada


def test_sin_datos_avisa_que_faltan():
    with pytest.raises(ValueError, match="CHATWOOT_URL"):
        Chatwoot(url="", token="", cuenta_id=1)


def test_un_timeout_pasajero_se_reintenta_y_funciona(monkeypatch):
    """La red falla una vez y anda a la segunda: la nota tiene que salir
    igual, sin que el aviso de la reserva se pierda por eso."""
    import io
    import urllib.error
    import urllib.request

    canal = Chatwoot(url="https://chatwoot.ejemplo.com", token="t", cuenta_id=1)
    monkeypatch.setattr("agente.reintentos.time.sleep", lambda segundos: None)

    intentos = []

    class _Respuesta(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(pedido, timeout):
        intentos.append(1)
        if len(intentos) == 1:
            raise urllib.error.URLError("conexión rechazada")
        return _Respuesta(b'{"id": 99}')

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    assert canal._api("POST", "conversations/1/messages", {"content": "hola"}) == {"id": 99}
    assert len(intentos) == 2


# -- Juntar la ráfaga ---------------------------------------------------------


def juntar(buffer: BufferDeMensajes, mensajes, conversacion="12", entre=0.0):
    """Manda varios mensajes seguidos y espera a que el buffer los suelte."""

    async def correr():
        for texto in mensajes:
            await buffer.agregar(conversacion, texto)
            if entre:
                await asyncio.sleep(entre)
        # Un rato más que la espera del buffer, para que llegue a soltar.
        await asyncio.sleep(buffer.segundos + 0.15)

    asyncio.run(correr())


def test_tres_mensajes_seguidos_son_una_sola_respuesta():
    """El caso de todos los días: "hola" / "una consulta" / "por el precio"."""
    sueltos = []
    buffer = BufferDeMensajes(
        0.05, lambda c, t: _anotar(sueltos, c, t)
    )

    juntar(buffer, ["hola", "una consulta", "por el precio"])

    assert len(sueltos) == 1, "tendría que haber contestado una sola vez"
    assert sueltos[0] == ("12", "hola\nuna consulta\npor el precio")


def test_cada_conversacion_junta_la_suya():
    """Si se mezclaran, una persona recibiría el mensaje de otra."""
    sueltos = []
    buffer = BufferDeMensajes(0.05, lambda c, t: _anotar(sueltos, c, t))

    async def correr():
        await buffer.agregar("111", "soy uno")
        await buffer.agregar("222", "soy dos")
        await asyncio.sleep(0.25)

    asyncio.run(correr())

    assert sorted(sueltos) == [("111", "soy uno"), ("222", "soy dos")]


def test_sin_espera_contesta_derecho():
    """BUFFER_SEGUNDOS=0 apaga el buffer."""
    sueltos = []
    buffer = BufferDeMensajes(0, lambda c, t: _anotar(sueltos, c, t))

    asyncio.run(buffer.agregar("12", "hola"))

    assert sueltos == [("12", "hola")]


def test_el_tope_corta_la_espera_infinita():
    """Sin tope, alguien que escribe de a poco no recibe respuesta nunca.

    Cada mensaje reinicia el reloj. Si la persona manda uno justo antes de
    que se cumpla la espera, y otro, y otro, el agente se quedaría esperando
    para siempre. El tope obliga a contestar igual.
    """
    sueltos = []
    buffer = BufferDeMensajes(
        0.20, lambda c, t: _anotar(sueltos, c, t), tope=0.30
    )

    # Seis mensajes cada 0,1s = 0,6s de charla. Con la espera de 0,2s
    # reiniciándose cada vez, sin tope no soltaría hasta el final.
    juntar(buffer, ["a", "b", "c", "d", "e", "f"], entre=0.1)

    assert sueltos, "el tope tendría que haber forzado la respuesta"
    assert len(sueltos[0][1].split("\n")) < 6, "soltó antes de que terminara"


def test_al_apagar_no_se_pierde_lo_que_estaba_esperando():
    """Un deploy justo en esos segundos dejaría a alguien sin respuesta."""
    sueltos = []
    buffer = BufferDeMensajes(30, lambda c, t: _anotar(sueltos, c, t))

    async def correr():
        await buffer.agregar("12", "hola")
        assert buffer.pendientes("12") == 1
        await buffer.vaciar()

    asyncio.run(correr())

    assert sueltos == [("12", "hola")]


async def _anotar(donde, conversacion, texto):
    donde.append((conversacion, texto))


# -- El webhook entero, de punta a punta --------------------------------------
#
# Acá se pegan todas las piezas: llega el pedido de Chatwoot, contesta el
# agente, sale la respuesta. Con un canal de mentira y un modelo de mentira,
# así que no toca la red ni gasta un token.

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def cliente(canal, agente, token="secreto", buffer_segundos=0, calendario=None):
    """Levanta el webhook con las piezas de mentira adentro."""
    pytest.importorskip("httpx", reason="TestClient de FastAPI necesita httpx")
    from fastapi.testclient import TestClient

    from agente.web.webhook import crear_app

    from test_agente import agente_falso  # noqa: F401  (deja src en sys.path)

    config = agente.config
    config.chatwoot_webhook_token = token
    config.buffer_segundos = buffer_segundos

    return TestClient(crear_app(config, agente=agente, canal=canal, calendario=calendario))


def test_el_mensaje_da_la_vuelta_completa():
    from test_agente import agente_falso

    canal = ChatwootFalso()
    agente = agente_falso(["¡Buenas! ¿En qué te ayudo?"])

    with cliente(canal, agente) as web:
        respuesta = web.post("/chatwoot/secreto", json=evento("hola", conversacion=55))

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "recibido"
    assert canal.envios() == ["¡Buenas! ¿En qué te ayudo?"]


def test_un_audio_se_contesta_sin_pasar_por_el_modelo():
    """De punta a punta: antes esto quedaba en silencio total."""
    from agente.canales.chatwoot import MENSAJE_ADJUNTO_SIN_TEXTO
    from test_agente import agente_falso

    canal = ChatwootFalso()
    # Sin respuestas cargadas: si esto tocara el modelo, revienta el test.
    agente = agente_falso([])

    with cliente(canal, agente) as web:
        respuesta = web.post(
            "/chatwoot/secreto",
            json=evento(texto="", conversacion=55, adjuntos=[{"file_type": "audio"}]),
        )

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "recibido"
    assert canal.envios() == [MENSAJE_ADJUNTO_SIN_TEXTO]


def test_con_el_token_equivocado_no_entra():
    """Es lo único que separa a Chatwoot de cualquiera que sepa el dominio."""
    from test_agente import agente_falso

    canal = ChatwootFalso()

    with cliente(canal, agente_falso(["hola"])) as web:
        respuesta = web.post("/chatwoot/no-es-este", json=evento())

    assert respuesta.status_code == 401
    assert canal.envios() == [], "no tiene que haber contestado nada"


def test_su_propia_respuesta_no_dispara_otra():
    """El ida y vuelta infinito, probado de punta a punta."""
    from test_agente import agente_falso

    canal = ChatwootFalso()
    agente = agente_falso(["no debería usarse"])

    with cliente(canal, agente) as web:
        respuesta = web.post("/chatwoot/secreto", json=evento(tipo="outgoing"))

    assert respuesta.json()["estado"] == "ignorado"
    assert canal.envios() == []


def test_si_el_modelo_falla_se_le_avisa_a_la_persona():
    """Un error con una persona no puede dejarla esperando en silencio."""
    from test_agente import agente_falso

    canal = ChatwootFalso()
    agente = agente_falso([])  # sin respuestas: el modelo falso revienta

    with cliente(canal, agente) as web:
        web.post("/chatwoot/secreto", json=evento("hola"))

    assert len(canal.envios()) == 1
    assert "rompió" in canal.envios()[0]


def test_el_error_generico_se_traduce_al_idioma_de_la_conversacion(monkeypatch):
    """MENSAJE_ERROR_GENERICO no pasa por el agente (es un aviso fijo, se
    dispara desde el except) — sin esto siempre salía en el idioma en que
    está escrito el código, sin importar el de la persona. Reproducido en
    vivo: una conversación entera en portugués, aviso de error en
    español. Acá se prueba el mecanismo (que responder() llama al
    traductor con el aviso correcto) sin repetir las pruebas del
    traductor en sí, que ya están en test_reservas_webhook.py."""
    from agente.web import webhook as webhook_modulo
    from test_agente import agente_falso

    llamadas = []

    def _traductor_falso(agente, conversacion, texto):
        llamadas.append((conversacion, texto))
        return "Aviso traducido"

    monkeypatch.setattr(
        webhook_modulo, "_mensaje_en_idioma_de_conversacion", _traductor_falso
    )

    canal = ChatwootFalso()
    agente = agente_falso([])  # sin respuestas: el modelo falso revienta

    with cliente(canal, agente) as web:
        web.post("/chatwoot/secreto", json=evento("hola"))

    assert canal.envios() == ["Aviso traducido"]
    assert llamadas == [("12", webhook_modulo.MENSAJE_ERROR_GENERICO)]


def test_el_error_que_ve_la_persona_no_es_el_crudo():
    """Un cliente de WhatsApp no tiene que ver un stack trace de Python.

    Antes esto mandaba el error tal cual (regla general del proyecto para
    servidor.py/chat.py); en el webhook de producción es al cliente de una
    empresa a quien le llega, así que va un mensaje genérico. El detalle
    real se sigue logueando (ver AGENTS.md)."""
    from test_agente import agente_falso

    canal = ChatwootFalso()
    agente = agente_falso([])  # sin respuestas: el modelo falso revienta

    with cliente(canal, agente) as web:
        web.post("/chatwoot/secreto", json=evento("hola"))

    assert "StopIteration" not in canal.envios()[0]


def test_una_falla_dispara_una_alerta(monkeypatch):
    """El dueño del bot se tiene que enterar antes que el cliente le avise."""
    from test_agente import agente_falso

    avisos = []
    monkeypatch.setattr(
        "agente.web.webhook.alertas.avisar",
        lambda *a: avisos.append(a),
    )

    canal = ChatwootFalso()
    agente = agente_falso([])
    agente.config.alerta_telegram_token = "token-de-prueba"
    agente.config.alerta_telegram_chat_id = "123"

    with cliente(canal, agente) as web:
        web.post("/chatwoot/secreto", json=evento("hola"))

    assert len(avisos) == 1
    assert avisos[0][0] == "token-de-prueba"
    assert avisos[0][1] == "123"


def test_el_salud_contesta():
    """Coolify le pega a esto; si no contesta, reinicia el contenedor."""
    from test_agente import agente_falso

    with cliente(ChatwootFalso(), agente_falso(["hola"])) as web:
        respuesta = web.get("/salud")

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "ok"


def test_el_salud_avisa_si_la_memoria_esta_caida(monkeypatch):
    """El caso que motivó este chequeo: el proceso vivo, Postgres no.

    Antes /salud contestaba "ok" sin tocar la base, así que Coolify no se
    enteraba de esto — el bot quedaba "sano" y mudo hasta que alguien
    reiniciaba a mano."""
    from test_agente import agente_falso

    monkeypatch.setattr(
        "agente.web.webhook.verificar_memoria",
        lambda checkpointer: "OperationalError: consuming input failed",
    )

    with cliente(ChatwootFalso(), agente_falso(["hola"])) as web:
        respuesta = web.get("/salud")

    assert respuesta.status_code == 503
    assert respuesta.json()["estado"] == "error"
    assert "OperationalError" in respuesta.json()["error_memoria"]

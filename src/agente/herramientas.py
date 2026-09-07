"""Las herramientas: lo que el agente puede hacer además de conversar.

Una herramienta es una función común de Python que el modelo puede decidir
llamar. El modelo no la ejecuta: dice "quiero llamar a clima con lugar=Rosario"
y LangGraph la corre y le devuelve el resultado. Por eso el **docstring importa
tanto como el código**: es literalmente lo único que el modelo lee para decidir
si esta herramienta le sirve y qué mandarle.

Son seis:

  · `clima`                  → no necesita nada del canal, funciona en
                                cualquiera.
  · `franjas_ocupadas`       → lee Google Calendar. Sirve solo si el
                                negocio conectó un calendario.
  · `anotar_reserva`         → guarda el turno. Si hay calendario
                                conectado, lo confirma de una (chequea el
                                horario y crea el evento); si no, deja una
                                nota en Chatwoot pendiente de que alguien
                                la confirme a mano. Con
                                RESERVA_REQUIERE_APROBACION, un tercer
                                modo: calendario conectado pero el turno
                                queda "tentative" hasta que alguien del
                                negocio lo aprueba con un link. Antes de
                                todo esto, valida HORARIO_DESDE/HASTA y
                                DIAS_CERRADOS si están puestos. Sirve con
                                cualquiera de calendario/Chatwoot, con los
                                dos, o con ninguno — en ese último caso
                                avisa que no puede tomar reservas en ese
                                canal, en vez de fallar.
  · `cancelar_mi_reserva`    → cancela un turno ya anotado en ESTA
                                conversación. Necesita calendario conectado
                                (busca el evento por horario, no guarda su
                                id en ningún lado).
  · `reprogramar_mi_reserva` → mueve un turno ya anotado a otro día u
                                horario. Mismo requisito que la anterior.
  · `anotar_lista_espera`    → cuando el horario pedido está ocupado y la
                                persona prefiere esperar a que se libere en
                                vez de elegir otro. Deja una nota en
                                Chatwoot para que el equipo avise a mano si
                                se libera — no hay re-aviso automático.

`clima` usa **Open-Meteo** (https://open-meteo.com), que es gratis, no pide
registro y no usa clave de API. Eso es a propósito: este repo es para probar
y no queremos que arrancarlo dependa de sacar una credencial más. El uso no
comercial no tiene costo ni tarjeta.

Son dos consultas encadenadas, porque la API del clima habla en coordenadas y
las personas hablan en nombres de ciudades:

    1. Geocoding  → "Rosario"        se convierte en  (-32.94, -60.63)
    2. Pronóstico → (-32.94, -60.63) se convierte en  19 °C y nublado

Se usa `urllib`, de la biblioteca estándar, para no sumar una dependencia al
requirements.txt por dos pedidos HTTP.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from . import aprobacion, horario
from .calendario import Calendario, conversacion_del_evento
from .canales.chatwoot import Chatwoot
from .config import Config

GEOCODING = "https://geocoding-api.open-meteo.com/v1/search"
PRONOSTICO = "https://api.open-meteo.com/v1/forecast"

# Si Open-Meteo no contesta en este tiempo, cortamos. Sin un tope, una consulta
# colgada deja al agente mudo en la mitad de la conversación.
ESPERA = 15

# Open-Meteo devuelve el estado del cielo como un número (el código WMO, un
# estándar meteorológico). Esta es la traducción a algo que una persona lea.
CIELO = {
    0: "despejado",
    1: "casi despejado",
    2: "parcialmente nublado",
    3: "nublado",
    45: "con niebla",
    48: "con niebla que escarcha",
    51: "con llovizna suave",
    53: "con llovizna",
    55: "con llovizna fuerte",
    56: "con llovizna helada",
    57: "con llovizna helada fuerte",
    61: "con lluvia suave",
    63: "con lluvia",
    65: "con lluvia fuerte",
    66: "con lluvia helada",
    67: "con lluvia helada fuerte",
    71: "con nevada suave",
    73: "con nevada",
    75: "con nevada fuerte",
    77: "con granizo fino",
    80: "con chaparrones",
    81: "con chaparrones fuertes",
    82: "con chaparrones muy fuertes",
    85: "con chaparrones de nieve",
    86: "con chaparrones de nieve fuertes",
    95: "con tormenta",
    96: "con tormenta y algo de granizo",
    99: "con tormenta y granizo",
}


@tool
def clima(lugar: str) -> str:
    """Dice el clima que hace ahora mismo en una ciudad.

    Usala cuando te pregunten por el clima, la temperatura, si llueve, si hace
    frío o calor, o si conviene salir con abrigo o paraguas.

    Args:
        lugar: La ciudad, en lo posible con el país. Por ejemplo "Rosario",
            "Buenos Aires, Argentina" o "Madrid". Si hay varias ciudades con
            el mismo nombre, se toma la más conocida.
    """
    # Por qué la herramienta devuelve el error en vez de levantarlo (esta es la
    # cuarta falla que se traga el proyecto, y va con el motivo escrito al lado,
    # como pide AGENTS.md): si una herramienta explota, LangGraph corta toda la
    # respuesta y la persona ve un error crudo. Devolviéndolo como texto, el
    # resultado le llega al modelo, que lo cuenta con sus palabras y la
    # conversación sigue. Ojo con la diferencia: acá no se esconde nada, el
    # problema igual termina en la pantalla — pero explicado y sin voltear la
    # charla. Los errores del *proveedor* siguen saliendo tal cual: esto es
    # una consulta a Open-Meteo, no al modelo.
    try:
        encontrado = _buscar_lugar(lugar)
    except Exception as e:
        return f"No se pudo consultar el clima de '{lugar}': {type(e).__name__}: {e}"

    if encontrado is None:
        return (
            f"No encontré ninguna ciudad que se llame '{lugar}'. "
            "Puede estar mal escrita, o convenir agregarle el país."
        )

    try:
        datos = _pedir_el_clima(encontrado["latitud"], encontrado["longitud"])
    except Exception as e:
        return f"No se pudo consultar el clima de '{lugar}': {type(e).__name__}: {e}"

    return _redactar(encontrado, datos)


# La etiqueta que le pone Chatwoot a una conversación con una reserva
# anotada. Sirve para filtrar la bandeja; no tiene nada que ver con
# CHATWOOT_ETIQUETA_HUMANO (esa apaga al bot, esta no).
ETIQUETA_RESERVA = "reserva-nueva"

# La etiqueta de una reserva "tentative" en el calendario, a la espera de
# que alguien del negocio la apruebe (RESERVA_REQUIERE_APROBACION). Distinta
# de ETIQUETA_RESERVA para que el equipo pueda filtrar en la bandeja
# "qué me falta aprobar" de "qué ya quedó firme".
ETIQUETA_RESERVA_PENDIENTE = "reserva-pendiente-aprobacion"

# Cuando la propia persona cancela su turno por chat (cancelar_mi_reserva).
ETIQUETA_RESERVA_CANCELADA = "reserva-cancelada"

# Alguien pidió un horario ocupado y prefirió anotarse a esperar que se
# libere, en vez de elegir otro (anotar_lista_espera).
ETIQUETA_LISTA_ESPERA = "lista-espera"


@tool
def franjas_ocupadas(fecha: str, config: RunnableConfig) -> str:
    """Lista los horarios ya ocupados del calendario, para una fecha.

    Llamala ANTES de anotar_reserva cuando el negocio tenga un calendario
    conectado, para no ofrecerle a la persona un horario que ya está
    tomado. Lo que no aparece en la lista y cae dentro del horario de
    atención (que esta misma herramienta te aclara, si el negocio lo tiene
    configurado) está libre.

    Args:
        fecha: La fecha a consultar, en formato AAAA-MM-DD (por ejemplo
            "2026-09-13"). Convertí "el sábado" o "mañana" a esta forma
            usando la fecha de hoy que tenés en el mensaje de sistema.
    """
    ajustes = _ajustes_del_config(config)

    try:
        if horario.dia_cerrado(fecha, ajustes.dias_cerrados):
            return f"El {fecha} el negocio está cerrado — no ofrezcas ese día."

        calendario = _calendario_del_config(config)
        if calendario is None:
            return "Este negocio no tiene un calendario conectado."
        ocupado = calendario.ocupado(fecha)
    except Exception as e:
        # Mismo criterio que en clima(): el error viaja como texto, no como
        # excepción, para que la charla siga y el modelo se lo explique a
        # la persona con sus palabras.
        return f"No se pudo consultar el calendario: {type(e).__name__}: {e}"

    if not ocupado:
        base = f"No hay nada ocupado en el calendario el {fecha}."
    else:
        lineas = [f"Horarios ocupados el {fecha}:"]
        lineas += [f"- {desde}–{hasta}" for desde, hasta in ocupado]
        base = "\n".join(lineas)

    # Sin esto, el modelo podía ofrecer un horario que el calendario tiene
    # libre pero que en realidad cae fuera de atención (el corte de un
    # horario partido, por ejemplo) — y recién se enteraba al llamar a
    # anotar_reserva, después de pedirle nombre y personas a la persona
    # para nada.
    aviso = horario.descripcion(
        ajustes.horario_desde, ajustes.horario_hasta, ajustes.horario_franjas
    )
    if aviso:
        base += f"\n{aviso} No ofrezcas nada fuera de esa atención."

    return base


@tool
def anotar_reserva(
    nombre: str,
    personas: int,
    fecha: str,
    hora: str,
    config: RunnableConfig,
    telefono: str = "",
    aclaracion: str = "",
    duracion_minutos: int = 60,
) -> str:
    """Guarda un turno o una reserva.

    Si el negocio tiene Google Calendar conectado, esta herramienta CONFIRMA
    la reserva de una: revisa que el horario esté libre y crea el evento —
    llamá antes a franjas_ocupadas para no ofrecer un horario tomado. Si el
    negocio pide aprobación manual (RESERVA_REQUIERE_APROBACION), el horario
    queda reservado igual (nadie más lo puede tomar) pero a la espera de que
    alguien del negocio lo apruebe. Si el negocio NO tiene calendario, la
    reserva queda anotada nada más, pendiente de que alguien la confirme a
    mano.

    De cualquiera de las formas, repetile el resumen a la persona antes de
    llamar a esta herramienta: un dato mal entendido acá es peor que
    preguntar de nuevo.

    Args:
        nombre: A nombre de quién es la reserva.
        personas: Cuántas personas van a ser. Poné 1 si es un turno
            individual (una consulta, una sesión).
        fecha: La fecha en formato AAAA-MM-DD. Convertí "el sábado" o
            "mañana" usando la fecha de hoy que tenés en tu propio prompt.
        hora: La hora en formato HH:MM, 24 horas (por ejemplo "21:00").
        telefono: Un teléfono de contacto, si lo dio. Opcional.
        aclaracion: Algo para tener en cuenta (una alergia, un cumpleaños,
            un pedido especial). Opcional.
        duracion_minutos: Cuánto dura el turno. Si no te dijeron nada, 60.
    """
    ajustes = _ajustes_del_config(config)

    try:
        horario.validar(
            fecha,
            hora,
            ajustes.horario_desde,
            ajustes.horario_hasta,
            ajustes.dias_cerrados,
            ajustes.horario_franjas,
        )
    except horario.ErrorDeHorario as e:
        return str(e)

    chatwoot = _chatwoot_del_config(config)
    conversacion = _conversacion_de(config)

    detalle = [
        f"Nombre: {nombre}",
        f"Personas: {personas}",
        f"Fecha: {fecha}",
        f"Hora: {hora}",
    ]
    if telefono:
        detalle.append(f"Teléfono: {telefono}")
    if aclaracion:
        detalle.append(f"Aclaración: {aclaracion}")
    texto_detalle = "\n".join(detalle)

    # La descripción que va al CALENDARIO lleva además la conversación —
    # así recordatorios.py puede, más adelante, encontrar a quién avisarle
    # sin necesitar guardar esa relación en ningún otro lado. No va en la
    # nota de Chatwoot: ahí la lee una persona, y el id de conversación no
    # le dice nada útil.
    descripcion_calendario = texto_detalle
    if conversacion:
        descripcion_calendario += f"\nConversación: {conversacion}"

    confirmada = False
    evento_pendiente_id: str | None = None

    try:
        calendario = _calendario_del_config(config)
        if calendario is not None:
            inicio, fin = calendario.rango(fecha, hora, duracion_minutos)

            if calendario.se_superpone(inicio, fin):
                return (
                    f"Ese horario ({fecha} {hora}) ya está ocupado en el "
                    "calendario. Ofrecele otro a la persona — podés "
                    "consultar franjas_ocupadas de nuevo para ese día."
                )

            requiere_aprobacion = ajustes.reserva_requiere_aprobacion

            evento = calendario.crear_evento(
                titulo=f"{nombre} ({personas}p)",
                descripcion=descripcion_calendario,
                inicio=inicio,
                fin=fin,
                estado="tentative" if requiere_aprobacion else "confirmed",
            )

            if requiere_aprobacion:
                evento_pendiente_id = evento.get("id")
            else:
                confirmada = True
    except Exception as e:
        return f"No se pudo crear el turno en el calendario: {type(e).__name__}: {e}"

    if chatwoot is None and not confirmada and not evento_pendiente_id:
        # Ni calendario ni Chatwoot: no hay dónde dejar ninguna constancia.
        return (
            "No puedo tomar reservas en este canal: hace falta tener "
            "Chatwoot o Google Calendar configurados."
        )

    if chatwoot is not None:
        if conversacion:
            nota = "Reserva\n" + texto_detalle
            etiqueta = ETIQUETA_RESERVA

            if evento_pendiente_id:
                etiqueta = ETIQUETA_RESERVA_PENDIENTE
                nota += "\n\n" + _aviso_de_aprobacion(
                    ajustes, conversacion, evento_pendiente_id
                )

            try:
                chatwoot.anotar(conversacion, nota)
                chatwoot.etiquetar(conversacion, etiqueta)
            except Exception as e:
                if not confirmada and not evento_pendiente_id:
                    # Acá Chatwoot ES la única constancia de la reserva: si
                    # esto falla, no se guardó en ningún lado. Tiene que
                    # llegar como error, no como "quedó anotada".
                    return f"No se pudo anotar la reserva: {type(e).__name__}: {e}"
                # El calendario ya tiene el horario tomado (confirmado o
                # tentative); esto es solo para que el equipo también lo
                # vea en la bandeja, no es la fuente de la verdad — no vale
                # la pena arruinar una reserva que sí se guardó por un
                # aviso que no salió.

    if confirmada:
        return f"Turno confirmado para el {fecha} a las {hora}. Avisale a la persona."

    if evento_pendiente_id:
        return (
            f"Horario reservado para el {fecha} a las {hora}: ya nadie más lo "
            "puede tomar, pero queda a la espera de que el negocio lo "
            "apruebe. Avisale a la persona que le confirman en breve."
        )

    return (
        "Reserva anotada. Avisale a la persona que queda pendiente de "
        "confirmación."
    )


@tool
def cancelar_mi_reserva(fecha: str, hora: str, config: RunnableConfig) -> str:
    """Cancela un turno ya anotado en ESTA conversación.

    Usala cuando la misma persona que hizo la reserva te pida cancelarla o
    avise que no va a poder ir. Necesitás la fecha y hora CON LA QUE SE
    ANOTÓ originalmente — si no las tenés claras, preguntaselas antes de
    llamar a esta herramienta. Solo funciona con Google Calendar conectado:
    es ahí donde se busca el turno, y solo cancela el que corresponda a
    ESTA conversación (no el de otra persona que caiga en la misma fecha y
    hora). Si el negocio pide un mínimo de anticipación
    (CANCELACION_HORAS_MINIMAS) y el turno es antes de eso, no cancela —
    le decís a la persona que hable directo con el negocio.

    Args:
        fecha: La fecha original de la reserva, en formato AAAA-MM-DD.
        hora: La hora original, en formato HH:MM (24 horas).
    """
    ajustes = _ajustes_del_config(config)
    calendario = _calendario_del_config(config)
    if calendario is None:
        return (
            "No puedo cancelar reservas en este canal: hace falta tener "
            "Google Calendar configurado."
        )

    conversacion = _conversacion_de(config)

    try:
        inicio, _ = calendario.rango(fecha, hora, 1)
        evento = calendario.evento_en(inicio)
        if evento is None:
            return (
                f"No encontré ninguna reserva para el {fecha} a las {hora}. "
                "Puede que ya se haya cancelado, o que el dato esté mal —"
                " confirmá la fecha y hora con la persona."
            )

        mensaje_ajena = _chequear_propietario(evento, conversacion, fecha, hora)
        if mensaje_ajena:
            return mensaje_ajena

        mensaje_anticipacion = _chequear_anticipacion(evento, ajustes)
        if mensaje_anticipacion:
            return mensaje_anticipacion

        calendario.cancelar_evento(evento["id"])
    except Exception as e:
        return f"No se pudo cancelar la reserva: {type(e).__name__}: {e}"

    _avisar_a_chatwoot(
        config,
        f"Reserva cancelada por la persona: {fecha} {hora}.",
        ETIQUETA_RESERVA_CANCELADA,
    )

    return f"Listo, cancelé la reserva del {fecha} a las {hora}."


@tool
def reprogramar_mi_reserva(
    fecha_actual: str,
    hora_actual: str,
    fecha_nueva: str,
    hora_nueva: str,
    config: RunnableConfig,
) -> str:
    """Mueve un turno ya anotado en ESTA conversación a otro día u horario.

    Usala cuando la persona pida cambiar su turno. Llamá antes a
    franjas_ocupadas para confirmar que el horario nuevo esté libre — igual
    se revisa acá adentro, pero avisarle a la persona de una es mejor que
    hacerle preguntar dos veces. Solo funciona con Google Calendar
    conectado, y solo mueve el turno que corresponda a ESTA conversación
    (no el de otra persona que caiga en la misma fecha y hora). Si el
    negocio pide un mínimo de anticipación (CANCELACION_HORAS_MINIMAS) y
    el turno actual es antes de eso, no lo mueve — le decís a la persona
    que hable directo con el negocio.

    Args:
        fecha_actual: La fecha con la que se anotó la reserva, AAAA-MM-DD.
        hora_actual: La hora con la que se anotó, HH:MM (24 horas).
        fecha_nueva: La fecha nueva pedida, AAAA-MM-DD.
        hora_nueva: La hora nueva pedida, HH:MM (24 horas).
    """
    ajustes = _ajustes_del_config(config)
    calendario = _calendario_del_config(config)
    if calendario is None:
        return (
            "No puedo reprogramar reservas en este canal: hace falta tener "
            "Google Calendar configurado."
        )

    conversacion = _conversacion_de(config)

    try:
        inicio_actual, _ = calendario.rango(fecha_actual, hora_actual, 1)
        evento = calendario.evento_en(inicio_actual)
        if evento is None:
            return (
                f"No encontré ninguna reserva para el {fecha_actual} a las "
                f"{hora_actual}. Confirmá la fecha y hora con la persona."
            )

        mensaje_ajena = _chequear_propietario(evento, conversacion, fecha_actual, hora_actual)
        if mensaje_ajena:
            return mensaje_ajena

        mensaje_anticipacion = _chequear_anticipacion(evento, ajustes)
        if mensaje_anticipacion:
            return mensaje_anticipacion

        duracion = _duracion_minutos(evento)
        inicio_nuevo, fin_nuevo = calendario.rango(fecha_nueva, hora_nueva, duracion)

        if calendario.se_superpone(inicio_nuevo, fin_nuevo):
            return (
                f"Ese horario nuevo ({fecha_nueva} {hora_nueva}) ya está "
                "ocupado. Ofrecele otro a la persona."
            )

        # Cancelar y crear de nuevo, no "mover": la API de Calendar no
        # tiene un PATCH atómico para start/end que además re-chequee
        # freeBusy, así que el chequeo de arriba y esto son dos pasos.
        calendario.cancelar_evento(evento["id"])
        calendario.crear_evento(
            titulo=evento.get("summary", ""),
            descripcion=evento.get("description", ""),
            inicio=inicio_nuevo,
            fin=fin_nuevo,
            estado=evento.get("status", "confirmed"),
        )
    except Exception as e:
        return f"No se pudo reprogramar la reserva: {type(e).__name__}: {e}"

    _avisar_a_chatwoot(
        config,
        f"Reserva movida de {fecha_actual} {hora_actual} a "
        f"{fecha_nueva} {hora_nueva}.",
    )

    return (
        f"Listo, moví la reserva del {fecha_actual} {hora_actual} al "
        f"{fecha_nueva} a las {hora_nueva}."
    )


@tool
def anotar_lista_espera(
    nombre: str,
    personas: int,
    fecha: str,
    hora: str,
    config: RunnableConfig,
    telefono: str = "",
) -> str:
    """Anota a alguien en lista de espera para un horario que está ocupado.

    Usala cuando anotar_reserva te avisó que el horario pedido ya está
    tomado y la persona prefiere esperar a que se libere, en vez de elegir
    otro. Deja una nota para el equipo del negocio — el aviso de que se
    liberó un lugar lo hace alguien del negocio a mano, esto no manda nada
    solo.

    Args:
        nombre: A nombre de quién es la espera.
        personas: Cuántas personas van a ser.
        fecha: La fecha pedida, en formato AAAA-MM-DD.
        hora: La hora pedida, en formato HH:MM (24 horas).
        telefono: Un teléfono de contacto, si lo dio. Opcional.
    """
    chatwoot = _chatwoot_del_config(config)
    if chatwoot is None:
        return "No puedo anotar listas de espera en este canal: hace falta tener Chatwoot configurado."

    detalle = [
        "Lista de espera",
        f"Nombre: {nombre}",
        f"Personas: {personas}",
        f"Fecha: {fecha}",
        f"Hora: {hora}",
    ]
    if telefono:
        detalle.append(f"Teléfono: {telefono}")

    conversacion = _conversacion_de(config)
    if not conversacion:
        return "No puedo anotar listas de espera en este canal."

    try:
        chatwoot.anotar(conversacion, "\n".join(detalle))
        chatwoot.etiquetar(conversacion, ETIQUETA_LISTA_ESPERA)
    except Exception as e:
        return f"No se pudo anotar en la lista de espera: {type(e).__name__}: {e}"

    return (
        f"Listo, quedó anotado en lista de espera para el {fecha} a las "
        f"{hora}. Avisale a la persona que el negocio la contacta si se "
        "libera ese horario."
    )


# Lo que el agente tiene atado. Cuando agregues otra herramienta, sumala acá:
# es la única lista que mira el grafo.
HERRAMIENTAS = [
    clima,
    franjas_ocupadas,
    anotar_reserva,
    cancelar_mi_reserva,
    reprogramar_mi_reserva,
    anotar_lista_espera,
]


# -- La reserva ---------------------------------------------------------------


def _conversacion_de(config: RunnableConfig) -> str:
    """El thread_id de la conversación (el id de Chatwoot, en ese canal).

    `config` no lo manda el modelo: LangChain lo inyecta solo porque el
    parámetro está anotado como `RunnableConfig` (mismo mecanismo con el que
    Agente._config_hilo() arma el thread_id). Por eso no aparece en
    `anotar_reserva.args`.
    """
    return str((config.get("configurable") or {}).get("thread_id") or "")


def _chatwoot_del_config(config: RunnableConfig) -> Chatwoot | None:
    """Un cliente de Chatwoot armado con el .env, o None si no está puesto.

    No se guarda un cliente único a nivel de módulo: se arma en cada llamada,
    igual que el prompt de sistema se relee en cada mensaje (ver
    Agente._sistema()). Así, si cambiás las credenciales en el .env, la
    próxima reserva ya las usa sin reiniciar nada.
    """
    ajustes = Config.desde_entorno()
    if not ajustes.chatwoot_url or not ajustes.chatwoot_token:
        return None

    return Chatwoot(
        url=ajustes.chatwoot_url,
        token=ajustes.chatwoot_token,
        cuenta_id=ajustes.chatwoot_cuenta_id,
    )


def _avisar_a_chatwoot(config: RunnableConfig, texto: str, etiqueta: str = "") -> None:
    """Deja una nota (y, si se pasó, una etiqueta) en Chatwoot — sin fallar
    si Chatwoot no está configurado o si el pedido no sale.

    La usan cancelar_mi_reserva y reprogramar_mi_reserva: en las dos, el
    calendario YA es la fuente de la verdad para cuando llegan acá (el
    turno ya se canceló o ya se movió), así que un aviso que no sale a la
    bandeja no puede voltear la respuesta a la persona.
    """
    chatwoot = _chatwoot_del_config(config)
    if chatwoot is None:
        return

    conversacion = _conversacion_de(config)
    if not conversacion:
        return

    try:
        chatwoot.anotar(conversacion, texto)
        if etiqueta:
            chatwoot.etiquetar(conversacion, etiqueta)
    except Exception:
        pass


def _duracion_minutos(evento: dict) -> int:
    """Cuánto dura un evento de Google Calendar, en minutos.

    Al menos 1: una duración de 0 rompería calendario.rango() más adelante
    (fin == inicio no tiene sentido para un turno).
    """
    inicio = datetime.fromisoformat(evento["start"]["dateTime"])
    fin = datetime.fromisoformat(evento["end"]["dateTime"])
    return max(1, int((fin - inicio).total_seconds() // 60))


def _horas_hasta_el_turno(evento: dict) -> float:
    """Cuántas horas faltan, desde ahora, para que empiece ese turno.

    Función aparte (en vez de un datetime.now() metido adentro de
    cancelar_mi_reserva) para que los tests puedan reemplazarla por un
    valor fijo sin pelearse con la hora real de la máquina que corre el
    test.
    """
    inicio = datetime.fromisoformat(evento["start"]["dateTime"])
    ahora = datetime.now(inicio.tzinfo)
    return (inicio - ahora).total_seconds() / 3600


def _chequear_anticipacion(evento: dict, ajustes: Config) -> str | None:
    """None si se puede cancelar/reprogramar; si no, el mensaje para el modelo.

    CANCELACION_HORAS_MINIMAS en 0 (el default) es "sin restricción" — ni
    siquiera se calculan las horas que faltan.
    """
    if ajustes.cancelacion_horas_minimas <= 0:
        return None

    if _horas_hasta_el_turno(evento) >= ajustes.cancelacion_horas_minimas:
        return None

    return (
        f"Ese turno es en menos de {ajustes.cancelacion_horas_minimas} horas: "
        "no se puede cancelar ni mover solo por acá. Decile a la persona "
        "que se comunique directo con el negocio."
    )


def _chequear_propietario(
    evento: dict, conversacion: str, fecha: str, hora: str
) -> str | None:
    """None si esta conversación puede cancelar/mover ese turno; si no, el
    mensaje para el modelo.

    El turno guarda de quién es en su descripción ("Conversación: <id>",
    ver conversacion_del_evento). Sin esto, cualquiera que acierte la
    fecha y hora exactas de OTRA persona podría cancelarle el turno.

    Un turno SIN esa marca (uno cargado a mano en Calendar, o de antes de
    que existiera esta protección) se deja pasar: no hay con qué comparar,
    y cortarlo de raíz rompería reservas viejas que hoy funcionan bien.
    """
    propietario = conversacion_del_evento(evento)
    if not conversacion or not propietario or propietario == conversacion:
        return None

    return (
        f"Ese turno del {fecha} a las {hora} no está anotado en esta "
        "conversación — no lo puedo cancelar ni mover desde acá. Si la "
        "persona insiste en que es suyo, decile que se comunique directo "
        "con el negocio."
    )


def _ajustes_del_config(config: RunnableConfig) -> Config:
    """La configuración leída del .env.

    Un nivel de indirección más, mismo criterio que _chatwoot_del_config y
    _calendario_del_config: así los tests pueden reemplazar esto por
    ajustes de mentira, sin depender de lo que diga el .env de verdad de
    esta máquina.
    """
    return Config.desde_entorno()


def _aviso_de_aprobacion(ajustes: Config, conversacion: str, evento_id: str) -> str:
    """El texto que se suma a la nota de Chatwoot de una reserva "tentative".

    Con URL_PUBLICA y RESERVA_SECRETO puestos, son dos links de un clic. Sin
    eso, avisamos igual — la reserva ya está tomada en el calendario, pero
    aprobarla hay que hacerlo directo desde Google Calendar.
    """
    if not ajustes.url_publica or not ajustes.reserva_secreto:
        return (
            "Queda pendiente de aprobación. Para que este aviso traiga "
            "links de un clic, completá URL_PUBLICA y RESERVA_SECRETO en "
            "el .env — mientras tanto, aprobala o rechazala directo en "
            "Google Calendar."
        )

    aprobar = aprobacion.link(
        ajustes.url_publica, conversacion, evento_id, ajustes.reserva_secreto, "aprobar"
    )
    rechazar = aprobacion.link(
        ajustes.url_publica, conversacion, evento_id, ajustes.reserva_secreto, "rechazar"
    )
    return f"Aprobar: {aprobar}\nRechazar: {rechazar}"


def _calendario_del_config(config: RunnableConfig) -> Calendario | None:
    """Un cliente de Google Calendar armado con el .env, o None si no está puesto.

    Mismo criterio que _chatwoot_del_config(): se arma en cada llamada, así
    que un cambio de credenciales en el .env se ve sin reiniciar nada.
    """
    ajustes = Config.desde_entorno()
    if not ajustes.google_calendar_id or not ajustes.google_service_account_json:
        return None

    return Calendario(
        calendario_id=ajustes.google_calendar_id,
        credencial_json=ajustes.google_service_account_json,
        zona_horaria=ajustes.zona_horaria,
    )


# -- Las consultas ------------------------------------------------------------


def _buscar_lugar(nombre: str) -> dict | None:
    """Convierte un nombre de ciudad en coordenadas. None si no existe."""
    datos = _traer(
        GEOCODING,
        {"name": nombre, "count": 1, "language": "es", "format": "json"},
    )

    resultados = datos.get("results") or []
    if not resultados:
        return None

    primero = resultados[0]
    return {
        "nombre": primero.get("name") or nombre,
        # admin1 es la provincia o el estado. Sirve para desambiguar cuando hay
        # cinco ciudades con el mismo nombre en países distintos.
        "provincia": primero.get("admin1") or "",
        "pais": primero.get("country") or "",
        "latitud": primero["latitude"],
        "longitud": primero["longitude"],
    }


def _pedir_el_clima(latitud: float, longitud: float) -> dict:
    """El clima de este momento en esas coordenadas."""
    return _traer(
        PRONOSTICO,
        {
            "latitude": latitud,
            "longitude": longitud,
            "current": (
                "temperature_2m,relative_humidity_2m,apparent_temperature,"
                "weather_code,wind_speed_10m"
            ),
            # timezone=auto hace que la hora venga en la del lugar consultado,
            # no en la nuestra. Si preguntás por Tokio querés la hora de Tokio.
            "timezone": "auto",
        },
    )


def _traer(url: str, parametros: dict) -> dict:
    """Un GET que devuelve JSON."""
    completa = f"{url}?{urllib.parse.urlencode(parametros)}"

    with urllib.request.urlopen(completa, timeout=ESPERA) as respuesta:
        return json.loads(respuesta.read().decode("utf-8"))


# -- El texto que lee el modelo -----------------------------------------------


def _redactar(lugar: dict, datos: dict) -> str:
    """Arma la respuesta en texto.

    Le devolvemos al modelo una frase escrita, no el JSON crudo: entiende
    cualquiera de los dos, pero con el texto ya redactado es mucho menos
    probable que se equivoque de unidad o invente un dato que no está.
    """
    ahora = datos.get("current") or {}

    partes = [f"Clima en {_nombre_completo(lugar)}:"]
    partes.append(f"- Temperatura: {ahora.get('temperature_2m', '?')} °C")

    sensacion = ahora.get("apparent_temperature")
    if sensacion is not None:
        partes.append(f"- Sensación térmica: {sensacion} °C")

    partes.append(f"- Cielo: {_describir_cielo(ahora.get('weather_code'))}")

    humedad = ahora.get("relative_humidity_2m")
    if humedad is not None:
        partes.append(f"- Humedad: {humedad} %")

    viento = ahora.get("wind_speed_10m")
    if viento is not None:
        partes.append(f"- Viento: {viento} km/h")

    hora = ahora.get("time")
    if hora:
        partes.append(f"- Medido a las {hora[11:16]}, hora local del lugar")

    return "\n".join(partes)


def _nombre_completo(lugar: dict) -> str:
    """"Rosario, Provincia de Santa Fe, Argentina" — sin comas de más."""
    return ", ".join(
        p for p in (lugar.get("nombre"), lugar.get("provincia"), lugar.get("pais")) if p
    )


def _describir_cielo(codigo) -> str:
    """El código WMO en castellano. Si es uno raro, devolvemos el número."""
    if codigo is None:
        return "sin datos"
    return CIELO.get(codigo, f"sin descripción (código {codigo})")

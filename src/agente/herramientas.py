"""Las herramientas: lo que el agente puede hacer además de conversar.

Una herramienta es una función común de Python que el modelo puede decidir
llamar. El modelo no la ejecuta: dice "quiero llamar a clima con lugar=Rosario"
y LangGraph la corre y le devuelve el resultado. Por eso el **docstring importa
tanto como el código**: es literalmente lo único que el modelo lee para decidir
si esta herramienta le sirve y qué mandarle.

Hay tres:

  · `clima`             → no necesita nada del canal, funciona en cualquiera.
  · `franjas_ocupadas`  → lee Google Calendar. Sirve solo si el negocio
                           conectó un calendario (ver calendario.py).
  · `anotar_reserva`    → guarda el turno. Si hay calendario conectado, lo
                           confirma de una (chequea el horario y crea el
                           evento); si no, deja una nota en Chatwoot
                           pendiente de que alguien la confirme a mano.
                           Sirve con cualquiera de los dos, con los dos, o
                           con ninguno — en ese último caso avisa que no
                           puede tomar reservas en ese canal, en vez de
                           fallar.

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

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from .calendario import Calendario
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


@tool
def franjas_ocupadas(fecha: str, config: RunnableConfig) -> str:
    """Lista los horarios ya ocupados del calendario, para una fecha.

    Llamala ANTES de anotar_reserva cuando el negocio tenga un calendario
    conectado, para no ofrecerle a la persona un horario que ya está
    tomado. Lo que no aparece en la lista y cae dentro del horario de
    atención (el que sabés por tu propio prompt) está libre.

    Args:
        fecha: La fecha a consultar, en formato AAAA-MM-DD (por ejemplo
            "2026-09-13"). Convertí "el sábado" o "mañana" a esta forma
            usando la fecha de hoy que tenés en el mensaje de sistema.
    """
    try:
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
        return f"No hay nada ocupado en el calendario el {fecha}."

    lineas = [f"Horarios ocupados el {fecha}:"]
    lineas += [f"- {desde}–{hasta}" for desde, hasta in ocupado]
    return "\n".join(lineas)


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
    negocio NO tiene calendario, la reserva queda anotada nada más,
    pendiente de que alguien la confirme a mano.

    De cualquiera de las dos formas, repetile el resumen a la persona antes
    de llamar a esta herramienta: un dato mal entendido acá es peor que
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
    chatwoot = _chatwoot_del_config(config)

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

    confirmada = False
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

            calendario.crear_evento(
                titulo=f"{nombre} ({personas}p)",
                descripcion=texto_detalle,
                inicio=inicio,
                fin=fin,
            )
            confirmada = True
    except Exception as e:
        return f"No se pudo crear el turno en el calendario: {type(e).__name__}: {e}"

    if chatwoot is None and not confirmada:
        # Ni calendario ni Chatwoot: no hay dónde dejar ninguna constancia.
        return (
            "No puedo tomar reservas en este canal: hace falta tener "
            "Chatwoot o Google Calendar configurados."
        )

    if chatwoot is not None:
        conversacion = _conversacion_de(config)
        if conversacion:
            try:
                chatwoot.anotar(conversacion, "Reserva\n" + texto_detalle)
                chatwoot.etiquetar(conversacion, ETIQUETA_RESERVA)
            except Exception as e:
                if not confirmada:
                    # Acá Chatwoot ES la única constancia de la reserva: si
                    # esto falla, no se guardó en ningún lado. Tiene que
                    # llegar como error, no como "quedó anotada".
                    return f"No se pudo anotar la reserva: {type(e).__name__}: {e}"
                # El calendario ya tiene la reserva confirmada; esto es
                # solo para que el equipo también la vea en la bandeja, no
                # es la fuente de la verdad — no vale la pena arruinar una
                # reserva que sí se guardó por un aviso que no salió.

    if confirmada:
        return f"Turno confirmado para el {fecha} a las {hora}. Avisale a la persona."

    return (
        "Reserva anotada. Avisale a la persona que queda pendiente de "
        "confirmación."
    )


# Lo que el agente tiene atado. Cuando agregues otra herramienta, sumala acá:
# es la única lista que mira el grafo.
HERRAMIENTAS = [clima, franjas_ocupadas, anotar_reserva]


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

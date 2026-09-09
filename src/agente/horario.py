"""El horario de atención del negocio: qué días y qué horas acepta turnos.

Antes de esto, lo único que sabía el modelo del horario de atención era lo
que decía su propio prompt (`prompts/sistema.md`) — nada se lo hacía
cumplir de verdad. Con HORARIO_DESDE/HORARIO_HASTA (un turno corrido) o
HORARIO_FRANJAS (horario partido, con un corte al medio) y DIAS_CERRADOS
en el .env, `anotar_reserva` lo valida de una. Sin nada de esto
configurado, no hay restricción — se comporta igual que antes de que
existiera este archivo.
"""

from __future__ import annotations

from datetime import datetime, time

DIAS = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "miércoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "sábado": 5,
    "domingo": 6,
}


class ErrorDeHorario(Exception):
    """La fecha o la hora pedida cae fuera del horario de atención."""


def dias_cerrados(texto: str) -> set[int]:
    """"domingo, lunes" -> {6, 0}.

    Un nombre que no reconoce se ignora en vez de explotar: mejor aceptar
    de más (un día que alguien escribió con una tilde distinta) que romper
    el arranque del agente por un typo en el .env.
    """
    return {
        DIAS[nombre]
        for nombre in (n.strip().lower() for n in texto.split(","))
        if nombre in DIAS
    }


def _hora(texto: str) -> time | None:
    texto = (texto or "").strip()
    return datetime.strptime(texto, "%H:%M").time() if texto else None


def franjas_de(texto: str) -> list[tuple[time, time]]:
    """"09:00-15:00, 18:00-23:00" -> [(9:00, 15:00), (18:00, 23:00)].

    Para el horario partido (un corte al mediodía, por ejemplo). Formato:
    pares "HH:MM-HH:MM" separados por coma. Una franja mal escrita se
    ignora en vez de romper el arranque — mismo criterio que
    dias_cerrados() con un nombre que no reconoce.
    """
    franjas = []
    for parte in texto.split(","):
        parte = parte.strip()
        if "-" not in parte:
            continue

        desde_str, _, hasta_str = parte.partition("-")
        try:
            desde, hasta = _hora(desde_str), _hora(hasta_str)
        except ValueError:
            continue

        if desde and hasta:
            franjas.append((desde, hasta))

    return franjas


def _franjas_legibles(franjas: list[tuple[time, time]]) -> str:
    return " y ".join(
        f"{d.strftime('%H:%M')} a {h.strftime('%H:%M')}" for d, h in franjas
    )


def dia_cerrado(fecha: str, cerrados: str) -> bool:
    """Si esa fecha cae en uno de los días cerrados."""
    dia = datetime.strptime(fecha, "%Y-%m-%d").date()
    return dia.weekday() in dias_cerrados(cerrados)


def descripcion(desde: str, hasta: str, franjas: str) -> str:
    """Una frase con el horario de atención, para que franjas_ocupadas se
    la sume al modelo — sin esto, el modelo puede ofrecer un horario que
    el calendario tiene libre pero que en realidad cae fuera de atención
    (por ejemplo, en el corte de un horario partido). Cadena vacía si no
    hay nada configurado.
    """
    lista = franjas_de(franjas)
    if lista:
        return f"Atiende de {_franjas_legibles(lista)}."
    if desde and hasta:
        return f"Atiende de {desde} a {hasta}."
    if desde:
        return f"Atiende desde las {desde}."
    if hasta:
        return f"Atiende hasta las {hasta}."
    return ""


def validar(
    fecha: str,
    hora: str,
    desde: str = "",
    hasta: str = "",
    cerrados: str = "",
    franjas: str = "",
    ahora: datetime | None = None,
) -> None:
    """Tira ErrorDeHorario si (fecha, hora) cae fuera de la atención.

    Con `desde`, `hasta`, `cerrados` y `franjas` vacíos (el caso por
    defecto), no valida nada de horario de atención: el negocio que no
    configuró nada acepta cualquiera, como pasaba antes de este módulo.

    `franjas` (HORARIO_FRANJAS) es para el horario partido — si viene con
    algo, manda por sobre `desde`/`hasta`: alcanza con que la hora caiga en
    CUALQUIERA de sus rangos. Sin `franjas`, se usa el rango único de
    `desde`/`hasta` (un solo turno corrido), como antes de que existiera
    el horario partido.

    `ahora` es aparte de todo lo anterior: si se pasa, rechaza una fecha u
    hora anterior a `ahora`, sin importar si hay horario de atención
    configurado o no — reservar para el pasado no es una preferencia del
    negocio, es que el turno ya sucedió. Nadie lo llamaba con esto hasta
    ahora, así que quien no lo use (`ahora=None`, el default) no valida
    esto — mismo criterio que el resto de los parámetros opcionales.
    """
    dia = datetime.strptime(fecha, "%Y-%m-%d").date()
    hora_pedida = datetime.strptime(hora, "%H:%M").time()

    if ahora is not None:
        pedida = datetime.combine(dia, hora_pedida, tzinfo=ahora.tzinfo)
        if pedida < ahora:
            raise ErrorDeHorario(
                f"El {fecha} a las {hora} ya pasó — no se puede reservar una "
                "fecha u hora anterior a ahora. Preguntale a la persona por "
                "una fecha futura."
            )

    if dia.weekday() in dias_cerrados(cerrados):
        raise ErrorDeHorario(
            f"El {fecha} el negocio está cerrado. Ofrecele otro día a la "
            "persona."
        )

    lista_franjas = franjas_de(franjas)
    if lista_franjas:
        if not any(d <= hora_pedida <= h for d, h in lista_franjas):
            raise ErrorDeHorario(
                f"El negocio atiende de {_franjas_legibles(lista_franjas)}, "
                f"y pediste las {hora}. Ofrecele un horario dentro de esas "
                "franjas."
            )
        return

    hora_desde = _hora(desde)
    hora_hasta = _hora(hasta)

    if hora_desde and hora_pedida < hora_desde:
        raise ErrorDeHorario(
            f"El negocio atiende desde las {desde}, y pediste las {hora}. "
            "Ofrecele un horario dentro de la atención."
        )
    if hora_hasta and hora_pedida > hora_hasta:
        raise ErrorDeHorario(
            f"El negocio atiende hasta las {hasta}, y pediste las {hora}. "
            "Ofrecele un horario dentro de la atención."
        )

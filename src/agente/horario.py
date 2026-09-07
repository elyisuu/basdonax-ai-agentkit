"""El horario de atención del negocio: qué días y qué horas acepta turnos.

Antes de esto, lo único que sabía el modelo del horario de atención era lo
que decía su propio prompt (`prompts/sistema.md`) — nada se lo hacía
cumplir de verdad. Con HORARIO_DESDE, HORARIO_HASTA y DIAS_CERRADOS en el
.env, `anotar_reserva` lo valida de una, así que un dato mal puesto en el
prompt (o el modelo ignorándolo) no termina en un turno a las 3 de la
mañana. Sin nada de esto configurado, no hay restricción — se comporta
igual que antes de que existiera este archivo.
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


def validar(fecha: str, hora: str, desde: str, hasta: str, cerrados: str) -> None:
    """Tira ErrorDeHorario si (fecha, hora) cae fuera de la atención.

    Con `desde`, `hasta` y `cerrados` vacíos (el caso por defecto), no
    valida nada: el negocio que no configuró horario acepta cualquiera,
    como pasaba antes de este módulo.
    """
    dia = datetime.strptime(fecha, "%Y-%m-%d").date()
    if dia.weekday() in dias_cerrados(cerrados):
        raise ErrorDeHorario(
            f"El {fecha} el negocio está cerrado. Ofrecele otro día a la "
            "persona."
        )

    hora_pedida = datetime.strptime(hora, "%H:%M").time()
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

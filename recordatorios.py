"""Recordatorios automáticos de turnos, por WhatsApp.

    python recordatorios.py

No es un servidor: es un programa que corre, avisa lo que tenga que avisar,
y termina. La idea es dejarlo programado para que se repita solo —una
Scheduled Task de Coolify, un cron— cada tanto (por ejemplo, cada hora).
Cada corrida barre el calendario buscando turnos que empiecen dentro de
RECORDATORIO_HORAS_ANTES horas (± la ventana de RECORDATORIO_VENTANA_MINUTOS)
y le manda un WhatsApp a cada persona, si todavía no se le avisó.

Necesita Google Calendar Y Chatwoot configurados: el calendario para saber
qué turnos hay, Chatwoot para saber por dónde avisarle a cada uno. Sin
alguno de los dos, no hay nada que hacer — el programa lo dice y termina
sin error, para que sea seguro dejarlo programado en cualquier instancia,
esté o no armada para esto.

Cómo sabe a QUIÉN avisarle: anotar_reserva() (herramientas.py) deja una
línea "Conversación: <id>" en la descripción del evento de Calendar. Sin
eso —un turno cargado a mano en Calendar, por ejemplo— no hay forma de
avisarle a nadie, y se lo salta.

Cómo evita avisar dos veces: no hay ninguna base de datos para esto. Cuando
se manda un recordatorio, se marca el evento mismo (extendedProperties,
invisible para quien lo mira en Calendar) — ver calendario.ya_recordado().
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from agente.consola import preparar  # noqa: E402

preparar()  # antes de imprimir nada, para que las tildes no rompan Windows

from agente.calendario import Calendario, ya_recordado  # noqa: E402
from agente.canales.chatwoot import Chatwoot  # noqa: E402
from agente.config import Config  # noqa: E402

AMBAR = "\033[38;5;214m"
GRIS = "\033[90m"
ROJO = "\033[91m"
FIN = "\033[0m"

_RE_CONVERSACION = re.compile(r"^Conversaci[oó]n:\s*(\S+)", re.MULTILINE)


def main() -> int:
    config = Config.desde_entorno()

    if not config.google_calendar_id or not config.google_service_account_json:
        print(f"{GRIS}Sin Google Calendar configurado: no hay nada que recordar.{FIN}")
        return 0

    if not config.chatwoot_url or not config.chatwoot_token:
        print(f"{GRIS}Sin Chatwoot configurado: no hay por dónde avisar.{FIN}")
        return 0

    calendario = Calendario(
        calendario_id=config.google_calendar_id,
        credencial_json=config.google_service_account_json,
        zona_horaria=config.zona_horaria,
    )
    chatwoot = Chatwoot(
        url=config.chatwoot_url,
        token=config.chatwoot_token,
        cuenta_id=config.chatwoot_cuenta_id,
    )

    ahora = datetime.now(calendario.zona)
    desde = ahora + timedelta(hours=config.recordatorio_horas_antes)
    hasta = desde + timedelta(minutes=config.recordatorio_ventana_minutos)

    try:
        eventos = calendario.eventos_entre(desde, hasta)
    except Exception as e:
        print(f"{ROJO}No se pudo consultar el calendario: {type(e).__name__}: {e}{FIN}")
        return 1

    avisados = 0

    for evento in eventos:
        if not deberia_avisar(evento):
            continue

        conversacion = conversacion_del_evento(evento)
        inicio = datetime.fromisoformat(evento["start"]["dateTime"]).astimezone(calendario.zona)
        mensaje = (
            f"¡Hola! Te recordamos tu turno para el {inicio.strftime('%d/%m')} "
            f"a las {inicio.strftime('%H:%M')}. Si no podés venir, avisanos "
            "por acá."
        )

        try:
            chatwoot.enviar(conversacion, [mensaje])
            calendario.marcar_recordado(evento["id"])
            avisados += 1
            print(f"{AMBAR}[{conversacion}]{FIN} avisado — {inicio.strftime('%d/%m %H:%M')}")
        except Exception as e:
            # Un aviso que falla no puede cortar los que siguen: son turnos
            # de personas distintas.
            print(f"{ROJO}[{conversacion}] no se pudo avisar: {type(e).__name__}: {e}{FIN}")

    print(f"{GRIS}{avisados} de {len(eventos)} turno(s) en la ventana.{FIN}")
    return 0


def conversacion_del_evento(evento: dict) -> str | None:
    """El id de conversación que anotar_reserva() dejó en la descripción,
    o None si el evento no tiene esa línea (uno cargado a mano, por ejemplo).
    """
    coincidencia = _RE_CONVERSACION.search(evento.get("description") or "")
    return coincidencia.group(1) if coincidencia else None


def deberia_avisar(evento: dict) -> bool:
    """Si a este evento le corresponde un recordatorio ahora.

    Tres condiciones: que esté confirmado (no "tentative" a la espera de
    aprobación — avisarle a alguien de un turno que todavía puede
    rechazarse sería confuso), que no se le haya avisado ya, y que sepamos
    a qué conversación avisarle.
    """
    return (
        evento.get("status") == "confirmed"
        and not ya_recordado(evento)
        and conversacion_del_evento(evento) is not None
    )


if __name__ == "__main__":
    raise SystemExit(main())

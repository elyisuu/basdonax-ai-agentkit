"""Los links para aprobar o rechazar una reserva pendiente, sin login.

Cuando el negocio pide confirmar los turnos a mano
(RESERVA_REQUIERE_APROBACION en el .env), `anotar_reserva` deja el turno
como "tentative" en el calendario — el horario ya queda tomado, nadie más
lo puede reservar — y le suma a la nota de Chatwoot dos links: uno para
aprobarlo, uno para rechazarlo. Alguien del negocio los abre desde el
celular y listo, sin entrar a ningún panel.

No hay tabla ni sesión que guardar: el link mismo lleva la firma. Mismo
criterio que CHATWOOT_WEBHOOK_TOKEN en la URL del webhook — un secreto en
la URL, no una cookie ni un usuario y contraseña. La firma incluye la
conversación y el evento, así que un link sirve solo para ESA reserva
puntual, no para aprobar ninguna otra.
"""

from __future__ import annotations

import hashlib
import hmac

ACCIONES = ("aprobar", "rechazar")


def firmar(secreto: str, conversacion: str, evento_id: str) -> str:
    """El token que va al final del link."""
    mensaje = f"{conversacion}:{evento_id}".encode()
    return hmac.new(secreto.encode(), mensaje, hashlib.sha256).hexdigest()


def valido(secreto: str, conversacion: str, evento_id: str, token: str) -> bool:
    """Si ese token corresponde de verdad a esa reserva.

    `hmac.compare_digest` en vez de `==` para no filtrar por temporización
    cuánto del token acertó — este endpoint no tiene mucho tráfico, pero
    hacerlo bien no cuesta nada.
    """
    if not secreto or not token:
        return False
    return hmac.compare_digest(firmar(secreto, conversacion, evento_id), token)


def link(
    url_publica: str, conversacion: str, evento_id: str, secreto: str, accion: str
) -> str:
    """El link completo para pegar en la nota de Chatwoot."""
    if accion not in ACCIONES:
        raise ValueError(f"accion tiene que ser una de {ACCIONES}, no '{accion}'")

    token = firmar(secreto, conversacion, evento_id)
    base = url_publica.rstrip("/")
    return f"{base}/reservas/{accion}/{conversacion}/{evento_id}?token={token}"

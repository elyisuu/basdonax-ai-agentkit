"""Avisos al dueño del bot cuando algo se rompe en producción.

No es el canal que atiende clientes (eso es `canales/telegram.py` o
Chatwoot): esto manda un mensaje aparte, a un chat propio, para que el
dueño del bot se entere de una falla ANTES que un cliente le escriba
enojado. Nace de un caso real: la conexión a Postgres se cortó sola en
producción y nadie lo notó hasta que alguien preguntó algo y vio el error
crudo en su chat (ver AGENTS.md, sección de Postgres).

Configuración, las dos variables (si falta una, no avisa y no rompe nada
— es la misma idea que Chatwoot/Calendar: opcional, no obligatorio):

    ALERTA_TELEGRAM_TOKEN    → el token de un bot de Telegram (@BotFather)
    ALERTA_TELEGRAM_CHAT_ID  → el chat al que avisar (@userinfobot te da el tuyo)

Un bot nuevo y separado del que use `canales/telegram.py`, a propósito:
ese es el que atiende clientes y en producción puede ni estar configurado.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request

registro = logging.getLogger("agente.alertas")

# Cuánto esperar antes de repetir la MISMA alerta. Sin esto, una caída de
# Postgres que dura una hora manda un mensaje de Telegram por cada mensaje
# de WhatsApp que llega mientras tanto — el aviso deja de servir y se
# vuelve ruido que da ganas de silenciar el bot de alertas.
_COOLDOWN_SEGUNDOS = 300

# clave de la alerta -> último momento en que se mandó (time.monotonic()).
# Vive mientras vive el proceso: alcanza, porque el objetivo es no
# repetirse mientras la misma falla sigue activa, no llevar un historial.
_ultima_alerta: dict[str, float] = {}


def avisar(token: str, chat_id: str, clave: str, texto: str) -> None:
    """Manda `texto` por Telegram, salvo que ya se haya avisado `clave`
    hace menos de `_COOLDOWN_SEGUNDOS`.

    Sin token o chat_id, no hace nada — mismo criterio que Chatwoot y
    Calendar: son opcionales, y sin configurar no tiene que romper nada.
    Si el propio aviso falla (Telegram caído, token vencido), se loguea y
    se sigue: una alerta que no sale no puede además voltear el pedido
    que la disparó.
    """
    if not token or not chat_id:
        return

    ahora = time.monotonic()
    if ahora - _ultima_alerta.get(clave, 0.0) < _COOLDOWN_SEGUNDOS:
        return
    _ultima_alerta[clave] = ahora

    try:
        cuerpo = json.dumps({"chat_id": chat_id, "text": texto}).encode("utf-8")
        pedido = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=cuerpo,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(pedido, timeout=5)
    except Exception as e:
        registro.error("No se pudo mandar la alerta de Telegram: %s", e)

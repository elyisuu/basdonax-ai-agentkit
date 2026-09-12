"""Avisos fijos que le llegan a un cliente sin pasar por una conversación.

`anotar_reserva()`/`cancelar_mi_reserva()` (herramientas.py) contestan
DENTRO de un turno de chat — lo que dicen lo redacta el modelo, en el
idioma que ya venía usando, como cualquier otra respuesta. Pero hay avisos
que se disparan SOLOS, sin que nadie le esté escribiendo al bot en ese
momento: el genérico de error (`web/webhook.py`), el de aprobar/rechazar
una reserva (`web/webhook.py`, `/reservas/{accion}`), y el recordatorio de
turno (`recordatorios.py`). Ninguno de los tres pasa por el agente, así
que sin este módulo siempre saldrían en el idioma en que está escrito el
código (español), sin importar en qué idioma venía la conversación.
"""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from . import alertas
from .agente import Agente

registro = logging.getLogger("agente.mensajes")


def mensaje_en_idioma_de_conversacion(
    agente: Agente, conversacion: str, texto_es: str
) -> str:
    """Traduce un aviso fijo al idioma en que viene hablando esta conversación.

    Le pide al MISMO modelo que traduzca, mirando los últimos mensajes de
    la persona para saber en qué idioma escribir — sin tocar la memoria de
    la conversación (no pasa por agente.grafo/el checkpointer) ni las
    herramientas (agente.modelo es el modelo sin bind_tools). Si el
    idioma es español, pide español NEUTRO a propósito (ver AGENTS.md):
    un cliente final de cualquier país no tiene por qué entender voseo
    argentino, que es la convención del resto del código de este repo.

    Si algo falla (sin internet, el modelo no contesta), se manda el
    texto en español tal cual: peor es no avisarle nada a la persona. PERO
    a diferencia de otros "nunca revienta" del proyecto, esto SÍ loguea y
    avisa por Telegram (mismo mecanismo que alertas.py) — encontrado en
    vivo el 12 sep 2026: sin este aviso, una traducción que falla es
    indistinguible de una conversación que nunca dijo nada en otro
    idioma, y no hay forma de saber después por qué salió en español.
    """
    try:
        ultimos = [
            m.content
            for m in agente.historial(conversacion)
            if isinstance(m, HumanMessage) and isinstance(m.content, str) and m.content
        ][-4:]
        if not ultimos:
            registro.info(
                "[%s] mensaje_en_idioma_de_conversacion: sin historial, "
                "se manda el texto en español tal cual",
                conversacion,
            )
            return texto_es

        respuesta = agente.modelo.invoke(
            [
                SystemMessage(
                    "Traducí el siguiente aviso al idioma en el que está "
                    "escrita esta conversación (mirá los mensajes de abajo "
                    "para saber cuál es). Si el idioma es español, usá "
                    "español NEUTRO — sin voseo argentino (nunca 'vos', "
                    "'tenés', 'andá') ni modismos de ningún país, como se "
                    "entendería igual en cualquier país hispanohablante. "
                    "Si ya está en ese idioma y ya es neutro, devolvelo tal "
                    "cual. Respondé SOLO con el aviso traducido, sin "
                    "comillas ni explicaciones.\n\n"
                    "Mensajes de la conversación:\n" + "\n".join(ultimos)
                ),
                HumanMessage(texto_es),
            ]
        )
        traducido = respuesta.content if isinstance(respuesta.content, str) else ""
        if not traducido.strip():
            registro.warning(
                "[%s] mensaje_en_idioma_de_conversacion: el modelo devolvió "
                "una traducción vacía, se manda el texto en español tal cual",
                conversacion,
            )
        return traducido.strip() or texto_es
    except Exception as e:
        detalle = f"{type(e).__name__}: {e}"
        registro.warning(
            "[%s] mensaje_en_idioma_de_conversacion falló, se manda el "
            "texto en español tal cual: %s",
            conversacion,
            detalle,
        )
        try:
            alertas.avisar(
                agente.config.alerta_telegram_token,
                agente.config.alerta_telegram_chat_id,
                "traduccion_aviso_fijo",
                f"[agente-whatsapp] no se pudo traducir un aviso fijo "
                f"(conversación {conversacion}), salió en español: {detalle}",
            )
        except Exception:
            pass  # la alerta es un extra — que no salga no puede tapar el aviso real
        return texto_es

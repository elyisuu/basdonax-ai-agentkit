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

from langchain_core.messages import HumanMessage, SystemMessage

from .agente import Agente


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

    Si algo falla (sin internet, historial vacío), se manda el texto en
    español tal cual: peor es no avisarle nada a la persona.
    """
    try:
        ultimos = [
            m.content
            for m in agente.historial(conversacion)
            if isinstance(m, HumanMessage) and isinstance(m.content, str) and m.content
        ][-4:]
        if not ultimos:
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
        return traducido.strip() or texto_es
    except Exception:
        return texto_es

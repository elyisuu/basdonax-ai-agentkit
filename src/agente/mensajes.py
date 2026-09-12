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


def _texto_de(contenido: object) -> str:
    """El texto de una respuesta del modelo — mismo criterio que
    agente.py: _texto_de(), pero acá se lo reimplementa en vez de
    importarlo porque ese es privado de ese módulo.

    Bug real, encontrado en vivo el 12 sep 2026 y reproducido contra el
    modelo de verdad: con el thinking adaptativo de Claude (siempre
    prendido, ver modelos.py), `respuesta.content` NO siempre es un
    string — a veces es una LISTA de bloques (uno "thinking", vacío
    porque display es "omitted", y otro "text" con la respuesta real).
    El chequeo viejo (`isinstance(respuesta.content, str)`) daba por
    vacía cualquier respuesta que viniera en ese formato — el modelo SÍ
    había traducido bien, pero el código lo tiraba y mandaba el texto en
    español tal cual. No es intermitente por el idioma: es intermitente
    porque el modelo no siempre decide pensar antes de responder, y
    cuando lo hace, cambia la forma del content.
    """
    if isinstance(contenido, str):
        return contenido
    if isinstance(contenido, list):
        return "".join(
            b.get("text", "")
            for b in contenido
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


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
        humanos = [
            m.content
            for m in agente.historial(conversacion)
            if isinstance(m, HumanMessage) and isinstance(m.content, str) and m.content
        ]
        if not humanos:
            registro.info(
                "[%s] mensaje_en_idioma_de_conversacion: sin historial, "
                "se manda el texto en español tal cual",
                conversacion,
            )
            return texto_es

        # El ÚLTIMO mensaje es el único que importa de verdad — es
        # literalmente el idioma en el que la persona le está hablando al
        # bot AHORA. Antes se le pasaban al modelo los últimos 4 mensajes
        # juntos, numerados, pidiéndole que "priorice" el más reciente —
        # y aun así, en producción, terminó traduciendo al idioma de un
        # mensaje de más atrás (ver AGENTS.md, 12 sep 2026: sin ninguna
        # excepción ni alerta, solo una mala decisión del modelo entre
        # varias señales). Separar el último de literal "el resto" — un
        # solo texto principal, no una lista a promediar — deja mucho
        # menos margen para esa confusión. Los anteriores quedan nada más
        # como red de contención para un último mensaje corto/ambiguo
        # ("sí", "912345678", un nombre solo).
        ultimo = humanos[-1]
        anteriores = humanos[-4:-1]

        contexto = f'Último mensaje de la persona: "{ultimo}"'
        if anteriores:
            contexto += (
                "\n\nMensajes anteriores de la misma conversación — usalos "
                "para reconocer el idioma SOLO si el último mensaje es "
                "demasiado corto o ambiguo (un número, un \"sí\", un "
                "nombre solo) y no alcanza por sí mismo. Si el último ya "
                "deja claro el idioma, ignorá estos por completo, aunque "
                "estén en otro idioma (la persona pudo haber cambiado de "
                "idioma a mitad de charla):\n"
                + "\n".join(f"- {texto}" for texto in anteriores)
            )

        respuesta = agente.modelo.invoke(
            [
                SystemMessage(
                    "Traducí el siguiente aviso al idioma en el que está "
                    "escrito el ÚLTIMO mensaje de esta conversación (te lo "
                    "paso abajo). Si el idioma es español, usá español "
                    "NEUTRO — sin voseo argentino (nunca 'vos', 'tenés', "
                    "'andá') ni modismos de ningún país, como se entendería "
                    "igual en cualquier país hispanohablante. Si ya está en "
                    "ese idioma y ya es neutro, devolvelo tal cual. "
                    "Respondé SOLO con el aviso traducido, sin comillas ni "
                    "explicaciones.\n\n" + contexto
                ),
                HumanMessage(texto_es),
            ]
        )
        traducido = _texto_de(respuesta.content).strip()

        # Log incondicional (no solo en el except): si el idioma vuelve a
        # salir mal sin ninguna excepción de por medio (como esta vez),
        # esto es lo único que permite ver después qué vio el modelo y qué
        # devolvió, sin tener que reproducirlo de nuevo gastando tokens.
        registro.info(
            "[%s] mensaje_en_idioma_de_conversacion: último mensaje=%r, "
            "aviso original=%r, traducido=%r",
            conversacion,
            ultimo,
            texto_es,
            traducido,
        )

        if not traducido:
            registro.warning(
                "[%s] mensaje_en_idioma_de_conversacion: el modelo devolvió "
                "una traducción vacía, se manda el texto en español tal cual",
                conversacion,
            )
        return traducido or texto_es
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

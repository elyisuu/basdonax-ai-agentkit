"""El servidor que atiende WhatsApp.

Esta es la app que corre en el servidor. **No es la plataforma de pruebas**
(`web/app.py`): son dos cosas distintas y a propósito. La de pruebas es para
tu máquina, tiene la pantalla con los ajustes y no sale de localhost. Esta no
tiene pantalla: es una puerta por donde entra Chatwoot y nada más.

Lo que hace, de punta a punta:

    Chatwoot pega en POST /chatwoot/<token>
      → contestamos 200 al toque              ← esto es obligatorio
      → juntamos la ráfaga de mensajes          (buffer.py)
      → responde el agente                      (agente.py)
      → la respuesta sale por la API de Chatwoot (canales/chatwoot.py)

**Por qué el 200 sale antes de responderle a la persona.** Chatwoot espera
que el webhook conteste rápido; si tardamos lo que tarda el modelo en
pensar, da el pedido por fallado y lo reintenta — y entonces el agente
contesta dos veces lo mismo. Así que primero decimos "recibido" y recién
después pensamos la respuesta, en segundo plano.

**La seguridad es el token en la URL.** Chatwoot no firma sus webhooks (no
hay HMAC como en Meta), así que lo único que separa un mensaje de verdad de
cualquiera que descubra el dominio es que la URL tenga el token. Por eso es
largo y por eso no va en el código.
"""

from __future__ import annotations

import asyncio
import logging
import urllib.parse
from collections import defaultdict
from contextlib import asynccontextmanager
from html import escape

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .. import alertas, aprobacion, visitas
from ..agente import Agente
from ..calendario import Calendario, ErrorDeCalendario
from ..canales.buffer import BufferDeMensajes
from ..canales.chatwoot import MENSAJE_ADJUNTO_SIN_TEXTO, Chatwoot
from ..config import Config
from ..memoria import verificar as verificar_memoria
from ..mensajes import mensaje_en_idioma_de_conversacion as _mensaje_en_idioma_de_conversacion
from .textos_panel import t as _t

registro = logging.getLogger("agente.webhook")

# Lo que ve la PERSONA cuando el agente revienta. A propósito no es el
# error crudo (antes sí lo era, siguiendo la regla general de "el error del
# proveedor no se esconde" — ver AGENTS.md): esa regla tiene sentido cuando
# "el usuario" sos vos probando en servidor.py/chat.py, pero acá del otro
# lado hay un cliente de verdad de la empresa que te contrata, y un
# "OperationalError: consuming input failed..." en pleno WhatsApp no es
# información, es una mala experiencia. El detalle real sigue yendo a los
# logs (y, si está configurado, a la alerta de Telegram) tal cual antes.
#
# En español neutro (tú, no voseo argentino) a propósito — es la ÚNICA
# excepción al "español rioplatense" que pide AGENTS.md para el resto del
# código: esta variable no es un comentario ni un docstring, es texto que
# lee un cliente de cualquier país. `responder()`, más abajo, la pasa por
# _mensaje_en_idioma_de_conversacion() antes de mandarla — así alguien que
# viene hablando en portugués o inglés no se encuentra, encima de la
# falla, con un mensaje en un idioma que no entiende.
MENSAJE_ERROR_GENERICO = (
    "Se me rompió algo de mi lado. Ya lo estamos revisando — inténtalo de "
    "nuevo en un rato."
)


def _campo_de_descripcion(descripcion: str, etiqueta: str) -> str:
    """Un campo tipo "Etiqueta: valor" de la descripción de un evento de
    Calendar (ver anotar_reserva, herramientas.py, que arma esas líneas).
    "" si no está — Teléfono y Aclaración son opcionales ahí."""
    prefijo = f"{etiqueta}: "
    for linea in descripcion.splitlines():
        if linea.startswith(prefijo):
            return linea[len(prefijo):].strip()
    return ""


def _grafico_mensual(resumen: list[dict], idioma: str) -> str:
    """Un gráfico de barras apiladas (nuevos + recurrentes) por mes — puro
    CSS, ninguna librería de gráficos: cada barra son dos `div` con la
    altura calculada a mano en Python. Sirve para mostrar de un vistazo
    lo que la tabla de abajo obliga a leer con calma (útil al presentarle
    esto a un cliente).

    De más viejo a más nuevo (izquierda a derecha, como se lee un
    calendario) — `resumen_mensual()` viene al revés (más nuevo primero),
    por eso se da vuelta acá nomás, sin tocar esa consulta. Los últimos 12
    meses, para que la barra no quede angosta si ya hay años de datos.
    """
    if not resumen:
        return ""

    meses = list(reversed(resumen))[-12:]
    tope = max(f["turnos"] for f in meses) or 1
    alto_px = 120

    barras = "".join(
        f'<div class="barra-mes">'
        f'<span class="barra-total">{f["turnos"]}</span>'
        f'<div class="barra" style="height:{alto_px}px">'
        f'<div class="segmento recurrentes" style="height:{round(f["recurrentes"] / tope * alto_px)}px"></div>'
        f'<div class="segmento nuevos" style="height:{round(f["nuevos"] / tope * alto_px)}px"></div>'
        f"</div>"
        # "2026-09" -> "09/26": compacto para que quepan doce en fila.
        f'<span class="barra-mes-label">{escape(f["mes"][5:7])}/{escape(f["mes"][2:4])}</span>'
        f"</div>"
        for f in meses
    )

    return f"""
  <div class="grafico">{barras}</div>
  <div class="leyenda">
    <span><i class="punto nuevos"></i> {_t(idioma, 'tarjeta_nuevos')}</span>
    <span><i class="punto recurrentes"></i> {_t(idioma, 'tarjeta_recurrentes')}</span>
  </div>
"""


def _pagina_estadisticas(resumen: list[dict], detalle: list[dict], idioma: str = "es") -> str:
    """Arma el HTML de /estadisticas a mano — sin motor de plantillas ni
    JavaScript, mismo criterio liviano que el resto del repo (ver
    AGENTS.md: "web/app.py: un solo HTML, sin build ni npm").

    Cuatro bloques: tarjetas con el mes más reciente y el total histórico
    (para que el número grande se vea de una, sin tener que sumar la
    tabla a mano), el gráfico de la tendencia, el resumen mes a mes, y el
    detalle turno por turno.

    `idioma` es IDIOMA_PANEL (config.py) — lo elige el negocio en el
    .env, no depende de nada dinámico (ver textos_panel.py: es distinto
    del idioma de los avisos al cliente final, que sí es por conversación).
    """
    ultimo = resumen[0] if resumen else {"turnos": 0, "nuevos": 0, "recurrentes": 0}
    total_historico = sum(f["turnos"] for f in resumen)
    grafico_html = _grafico_mensual(resumen, idioma)

    if not resumen:
        resumen_filas = (
            f'<tr><td colspan="4" class="vacio">{_t(idioma, "vacio_turnos")}</td></tr>'
        )
    else:
        resumen_filas = "".join(
            f"<tr><td>{escape(f['mes'])}</td><td>{f['turnos']}</td>"
            f"<td>{f['nuevos']}</td><td>{f['recurrentes']}</td></tr>"
            for f in resumen
        )

    if not detalle:
        detalle_filas = (
            f'<tr><td colspan="6" class="vacio">{_t(idioma, "vacio_turnos")}</td></tr>'
        )
    else:
        # Nombre/teléfono/motivo son texto que la persona escribió por
        # WhatsApp — nunca confiar en que venga "limpio". escape() antes
        # de meterlo en el HTML (ver AGENTS.md).
        detalle_filas = "".join(
            f"<tr><td>{escape(v['nombre']) or '—'}</td>"
            f"<td>{escape(v['telefono']) or '—'}</td>"
            f"<td>{escape(v['motivo']) or '—'}</td>"
            f"<td>{escape(v['fecha'])}</td><td>{escape(v['hora'])}</td>"
            + (
                f'<td><span class="chip cancelada">{_t(idioma, "chip_cancelada")}</span></td></tr>'
                if v["cancelado"]
                else f"<td><span class=\"chip {'nueva' if v['es_nueva'] else 'recurrente'}\">"
                f"{_t(idioma, 'chip_nueva') if v['es_nueva'] else _t(idioma, 'chip_recurrente')}"
                "</span></td></tr>"
            )
            for v in detalle
        )

    return f"""<!doctype html>
<html lang="{_t(idioma, 'html_lang')}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_t(idioma, 'titulo_pagina')}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap">
<style>
  :root {{
    --tinta: #1c2530; --tinta-suave: #5b6672; --borde: #e3e7ec;
    --fondo: #f7f8fa; --superficie: #ffffff;
    --acento: #2f6f4f; --acento-suave: #e6f2ec;
    --recurrente: #b7c0cc; --recurrente-texto: #465063;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: "Inter", -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: var(--fondo); color: var(--tinta);
    margin: 0; padding: 40px 20px 80px;
  }}
  .contenedor {{ max-width: 880px; margin: 0 auto; }}
  h1 {{ font-size: 1.6rem; font-weight: 700; margin: 0 0 4px; letter-spacing: -.01em; }}
  .subtitulo {{ color: var(--tinta-suave); margin: 0 0 32px; font-size: .95rem; }}
  .tarjetas {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 40px; }}
  .tarjeta {{
    background: var(--superficie); border: 1px solid var(--borde); border-radius: 12px;
    padding: 18px 22px; flex: 1; min-width: 140px;
  }}
  .tarjeta .numero {{ display: block; font-size: 1.9rem; font-weight: 700; line-height: 1.2; }}
  .tarjeta .etiqueta {{ display: block; color: var(--tinta-suave); font-size: .8rem; margin-top: 2px; }}
  h2 {{ font-size: 1.05rem; font-weight: 600; margin: 40px 0 4px; }}
  .ayuda {{ color: var(--tinta-suave); font-size: .85rem; margin: 0 0 12px; }}

  .grafico {{
    display: flex; align-items: flex-end; justify-content: center; gap: 18px; height: 150px;
    background: var(--superficie); border: 1px solid var(--borde); border-radius: 12px;
    padding: 20px 16px 12px; overflow-x: auto;
  }}
  .barra-mes {{ display: flex; flex-direction: column; align-items: center; gap: 6px; min-width: 28px; }}
  .barra-total {{ font-size: .72rem; font-weight: 600; color: var(--tinta-suave); }}
  .barra {{ width: 100%; max-width: 26px; display: flex; flex-direction: column-reverse; border-radius: 4px; overflow: hidden; background: var(--borde); }}
  .segmento.nuevos {{ background: var(--acento); }}
  .segmento.recurrentes {{ background: var(--recurrente); }}
  .barra-mes-label {{ font-size: .68rem; color: var(--tinta-suave); white-space: nowrap; }}
  .leyenda {{ display: flex; gap: 20px; margin: 10px 0 0; font-size: .8rem; color: var(--tinta-suave); }}
  .leyenda .punto {{ display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 6px; }}
  .leyenda .punto.nuevos {{ background: var(--acento); }}
  .leyenda .punto.recurrentes {{ background: var(--recurrente); }}

  .tabla-scroll {{ overflow-x: auto; border: 1px solid var(--borde); border-radius: 10px; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--superficie); min-width: 480px; }}
  th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--borde); font-size: .92rem; white-space: nowrap; }}
  th {{ color: var(--tinta-suave); font-size: .75rem; text-transform: uppercase; letter-spacing: .03em; background: var(--fondo); }}
  tr:last-child td {{ border-bottom: none; }}
  td.vacio {{ color: var(--tinta-suave); text-align: center; padding: 24px; white-space: normal; }}
  .chip {{ display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: .78rem; font-weight: 600; }}
  .chip.nueva {{ background: var(--acento-suave); color: var(--acento); }}
  .chip.recurrente {{ background: #eef1f5; color: var(--recurrente-texto); }}
  .chip.cancelada {{ background: #fbe9e9; color: #a23c3c; }}
</style>
</head>
<body>
<div class="contenedor">
  <h1>{_t(idioma, 'titulo_pagina')}</h1>
  <p class="subtitulo">{_t(idioma, 'subtitulo')}</p>

  <div class="tarjetas">
    <div class="tarjeta"><span class="numero">{ultimo['turnos']}</span><span class="etiqueta">{_t(idioma, 'tarjeta_turnos_mes')}</span></div>
    <div class="tarjeta"><span class="numero">{ultimo['nuevos']}</span><span class="etiqueta">{_t(idioma, 'tarjeta_nuevos')}</span></div>
    <div class="tarjeta"><span class="numero">{ultimo['recurrentes']}</span><span class="etiqueta">{_t(idioma, 'tarjeta_recurrentes')}</span></div>
    <div class="tarjeta"><span class="numero">{total_historico}</span><span class="etiqueta">{_t(idioma, 'tarjeta_total')}</span></div>
  </div>
{grafico_html}
  <h2>{_t(idioma, 'encabezado_turnos_por_mes')}</h2>
  <div class="tabla-scroll"><table>
    <thead><tr><th>{_t(idioma, 'col_mes')}</th><th>{_t(idioma, 'col_turnos')}</th><th>{_t(idioma, 'col_nuevos')}</th><th>{_t(idioma, 'col_recurrentes')}</th></tr></thead>
    <tbody>{resumen_filas}</tbody>
  </table></div>

  <h2>{_t(idioma, 'encabezado_detalle')}</h2>
  <p class="ayuda">{_t(idioma, 'ayuda_detalle', n=len(detalle))}</p>
  <div class="tabla-scroll"><table>
    <thead><tr><th>{_t(idioma, 'col_nombre')}</th><th>{_t(idioma, 'col_telefono')}</th><th>{_t(idioma, 'col_motivo')}</th><th>{_t(idioma, 'col_fecha')}</th><th>{_t(idioma, 'col_hora')}</th><th></th></tr></thead>
    <tbody>{detalle_filas}</tbody>
  </table></div>
</div>
</body>
</html>"""


def _registrar_visita_aprobada(
    canal: Chatwoot, config: Config, conversacion: str, evento: dict
) -> None:
    """Guarda la visita (ver visitas.py) recién cuando el negocio APRUEBA
    una reserva "tentative" — no antes: contarla al crearla inflaría las
    estadísticas con turnos que después se rechazan.

    Nunca revienta: una estadística perdida no puede voltear una
    aprobación que ya se hizo de verdad. El detalle del fallo, si lo hay,
    queda en los logs de visitas.py.
    """
    try:
        contacto_id = canal.contacto_de(conversacion)
        if not contacto_id:
            return

        inicio = evento.get("start", {}).get("dateTime", "")
        fecha, _, resto = inicio.partition("T")
        hora = resto[:5]  # "09:00:00+01:00" -> "09:00"
        # El título se arma en anotar_reserva() como "Nombre (Np)".
        nombre = evento.get("summary", "").rsplit(" (", 1)[0]
        descripcion = evento.get("description", "")
        telefono = _campo_de_descripcion(descripcion, "Teléfono")
        motivo = _campo_de_descripcion(descripcion, "Aclaración")

        visitas.registrar_visita(
            config.postgres_dsn,
            contacto_id,
            fecha,
            hora,
            telefono=telefono,
            nombre=nombre,
            motivo=motivo,
        )
    except Exception as e:
        registro.warning("[%s] no se pudo registrar la visita: %s", conversacion, e)


def _calendario_para_aprobacion(
    config: Config, calendario_legacy: Calendario | None, profesional: str
) -> Calendario | None:
    """El Calendario correcto para UN link de /reservas/{accion} puntual.

    Con un solo profesional (o ninguno, el caso de siempre): el mismo
    `calendario_legacy` armado una sola vez al arrancar la app (ver
    crear_app) — ni este link ni ningún otro necesitan más que ese.

    Con PROFESIONALES configurado, `calendario_legacy` no sirve (puede ni
    existir, si el negocio no puso GOOGLE_CALENDAR_ID): se arma un
    Calendario nuevo, puntual para este pedido, según a qué profesional
    apunte el link — el mismo nombre que anotar_reserva usó para armarlo
    (ver herramientas.py, `_aviso_de_aprobacion`). Sin importar mayúsculas
    ni espacios de más, mismo criterio que herramientas._buscar_calendar_id
    (funciones separadas a propósito: esta es la única pieza de esa lógica
    que necesita el servidor web, y evita importar algo privado de
    herramientas.py).
    """
    if not config.profesionales:
        return calendario_legacy

    if not config.google_service_account_json:
        return None

    objetivo = profesional.strip().lower()
    for nombre, calendar_id in config.profesionales.items():
        if nombre.strip().lower() == objetivo:
            return Calendario(
                calendario_id=calendar_id,
                credencial_json=config.google_service_account_json,
                zona_horaria=config.zona_horaria,
            )
    return None


def _validar_link_reserva(
    accion: str,
    config: Config,
    calendario: Calendario | None,
    profesional: str,
    conversacion: str,
    evento_id: str,
    token: str,
) -> tuple[Calendario | None, HTMLResponse | None]:
    """Las cinco validaciones de un link de /reservas/{accion}, factorizadas
    para no repetirlas entre el GET (pantalla de confirmar) y el POST
    (ejecuta de verdad) — ver reserva_confirmar/reserva_ejecutar.

    Devuelve (agenda, None) si el link es válido, o (None, respuesta) si
    hay que cortar acá con esa respuesta tal cual.
    """
    idioma = config.idioma_panel

    if accion not in aprobacion.ACCIONES:
        return None, HTMLResponse(_t(idioma, "accion_desconocida"), status_code=404)

    if not config.reserva_secreto:
        return None, HTMLResponse(_t(idioma, "sin_reserva_secreto"), status_code=404)

    agenda = _calendario_para_aprobacion(config, calendario, profesional)
    if agenda is None:
        return None, HTMLResponse(_t(idioma, "sin_calendario_para_reserva"), status_code=404)

    if not aprobacion.valido(config.reserva_secreto, conversacion, evento_id, token, profesional):
        return None, HTMLResponse(_t(idioma, "link_invalido"), status_code=403)

    return agenda, None


def _pagina_simple(idioma: str, mensaje: str) -> str:
    """El HTML mínimo de "Listo, <lo que pasó>" — lo usan tanto el GET
    (cuando ya no hay nada que confirmar: la reserva ya se resolvió antes)
    como el POST (después de ejecutar la acción de verdad)."""
    return f"<h1>{_t(idioma, 'listo_titulo')}</h1><p>{mensaje}</p>"


def _pagina_confirmar_reserva(
    idioma: str,
    accion: str,
    evento: dict,
    conversacion: str,
    evento_id: str,
    token: str,
    profesional: str,
) -> str:
    """La pantalla que separa "abrir el link" de "aprobar/rechazar de
    verdad" — ver el docstring de reserva_confirmar para por qué existe.

    Sin JavaScript: un <form method="post"> con un solo botón. El GET que
    trajo hasta acá no tocó nada; recién el POST de este formulario (un
    clic de una persona de verdad, no una vista previa automática)
    ejecuta la acción.
    """
    inicio = evento.get("start", {}).get("dateTime", "")
    fecha, _, resto = inicio.partition("T")
    hora = resto[:5]  # "09:00:00+01:00" -> "09:00"
    # El título se arma en anotar_reserva() como "Nombre (Np)".
    nombre = evento.get("summary", "").rsplit(" (", 1)[0]
    motivo = _campo_de_descripcion(evento.get("description", ""), "Aclaración")

    clave_pregunta = "confirmar_pregunta_aprobar" if accion == "aprobar" else "confirmar_pregunta_rechazar"
    clave_boton = "confirmar_boton_aprobar" if accion == "aprobar" else "confirmar_boton_rechazar"

    fila_motivo = (
        f"<p><strong>{_t(idioma, 'col_motivo')}:</strong> {escape(motivo)}</p>" if motivo else ""
    )

    accion_url = f"/reservas/{accion}/{conversacion}/{evento_id}?token={urllib.parse.quote(token)}"
    if profesional:
        accion_url += f"&profesional={urllib.parse.quote(profesional)}"

    return f"""<!doctype html>
<html lang="{_t(idioma, 'html_lang')}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_t(idioma, 'confirmar_titulo')}</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
          max-width: 420px; margin: 48px auto; padding: 0 20px; color: #1c2530; }}
  h1 {{ font-size: 1.3rem; }}
  button {{ font: inherit; font-weight: 600; padding: 12px 20px; border: none;
            border-radius: 8px; background: #2f6f4f; color: #fff; width: 100%;
            margin-top: 20px; }}
  .ayuda {{ color: #5b6672; font-size: .85rem; margin-top: 16px; }}
</style>
</head>
<body>
  <h1>{escape(_t(idioma, clave_pregunta))}</h1>
  <p><strong>{_t(idioma, 'col_nombre')}:</strong> {escape(nombre)}</p>
  <p><strong>{_t(idioma, 'col_fecha')}:</strong> {escape(fecha)}</p>
  <p><strong>{_t(idioma, 'col_hora')}:</strong> {escape(hora)}</p>
  {fila_motivo}
  <form method="post" action="{escape(accion_url)}">
    <button type="submit">{escape(_t(idioma, clave_boton))}</button>
  </form>
  <p class="ayuda">{escape(_t(idioma, 'confirmar_ayuda'))}</p>
</body>
</html>"""


def crear_app(
    config: Config | None = None,
    agente: Agente | None = None,
    canal: Chatwoot | None = None,
    calendario: Calendario | None = None,
) -> FastAPI:
    """Arma el servidor.

    El agente, el canal y el calendario se pueden pasar armados: es lo que
    hacen los tests para probar todo esto sin salir a internet ni gastar
    un token.
    """
    config = config or Config.desde_entorno()

    canal = canal or Chatwoot(
        url=config.chatwoot_url,
        token=config.chatwoot_token,
        cuenta_id=config.chatwoot_cuenta_id,
        etiqueta_humano=config.chatwoot_etiqueta_humano,
    )

    # Solo para /reservas/{accion}: aprobar o rechazar una reserva
    # "tentative". Si el negocio no conectó calendario (ni tiene
    # PROFESIONALES), queda None y esas rutas avisan que no hay nada que
    # aprobar, en vez de fallar. Con varios profesionales, este NO es el
    # calendario a usar — _calendario_para_aprobacion() arma uno puntual
    # por pedido, según qué profesional venga en el link (ver más abajo).
    if calendario is None and config.google_calendar_id and config.google_service_account_json:
        calendario = Calendario(
            calendario_id=config.google_calendar_id,
            credencial_json=config.google_service_account_json,
            zona_horaria=config.zona_horaria,
        )

    # El agente se arma una sola vez y atiende a todo el mundo. Es lo que
    # queremos: adentro tiene la conexión a Postgres, y armarlo por mensaje
    # sería abrir una conexión nueva cada vez.
    agente = agente or Agente(config)

    # Un candado por conversación. Dos personas distintas se atienden a la
    # vez sin problema, pero dos mensajes de la MISMA persona no: si se
    # respondieran en paralelo, los dos leerían la memoria en el mismo punto
    # y el segundo pisaría lo que guardó el primero.
    candados: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    # Un candado por reserva, para /reservas/{accion}. Sin esto, dos GET
    # casi simultáneos al mismo link (la app de Chatwoot en el celular
    # precargando el link + el clic real de la persona, por ejemplo) pueden
    # los dos leer el evento como "todavía no confirmado" antes de que
    # cualquiera de los dos termine de escribirlo — y los dos mandan el
    # WhatsApp de confirmación. Reproducido en vivo: un solo clic, dos
    # avisos de "tu turno quedó confirmado". El chequeo de abajo ("¿cómo
    # está el evento ANTES de tocar nada?") ya existía, pero por su cuenta
    # no alcanza contra dos pedidos que llegan a la vez — hace falta que el
    # segundo espere a que el primero termine antes de mirar.
    candados_reserva: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def responder(conversacion: str, texto: str) -> None:
        """Le pasa la ráfaga al agente y manda la respuesta por Chatwoot."""
        async with candados[conversacion]:
            registro.info("[%s] %s", conversacion, texto.replace("\n", " | ")[:200])

            # El "escribiendo..." y el agente son código bloqueante (urllib y
            # el modelo). Van a un hilo aparte para no trabar el servidor:
            # mientras este mensaje se piensa, los demás siguen entrando.
            await asyncio.to_thread(canal.escribiendo, conversacion, True)

            try:
                mensajes = await asyncio.to_thread(
                    agente.responder_partido, texto, conversacion
                )
            except Exception as e:
                # El detalle real queda en los logs y, si está configurado,
                # en la alerta de Telegram — a la persona le llega un
                # mensaje genérico (ver MENSAJE_ERROR_GENERICO, arriba).
                # Tampoco volteamos el servidor: atiende a varias personas y
                # una falla con una no puede dejar sin respuesta a las demás.
                aviso = f"{type(e).__name__}: {e}"
                registro.error("[%s] %s", conversacion, aviso)
                mensaje_error = await asyncio.to_thread(
                    _mensaje_en_idioma_de_conversacion,
                    agente,
                    conversacion,
                    MENSAJE_ERROR_GENERICO,
                )
                mensajes = [mensaje_error]
                await asyncio.to_thread(
                    alertas.avisar,
                    config.alerta_telegram_token,
                    config.alerta_telegram_chat_id,
                    type(e).__name__,
                    f"[agente-whatsapp] falló una respuesta (conversación {conversacion}): {aviso}",
                )

            try:
                await asyncio.to_thread(canal.enviar, conversacion, mensajes)
            except Exception as e:
                # Acá ya no hay a quién avisarle: el canal de salida es
                # justamente el que falló. Queda en los logs.
                registro.error("[%s] no se pudo enviar: %s", conversacion, e)
            finally:
                await asyncio.to_thread(canal.escribiendo, conversacion, False)

            registro.info("[%s] -> %s mensaje(s)", conversacion, len(mensajes))

    buffer = BufferDeMensajes(config.buffer_segundos, responder)

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI):
        # Mismo momento en que PostgresSaver.setup() arma las tablas de la
        # memoria (Agente() ya la construyó arriba). Sin POSTGRES_DSN, no
        # hace nada — ver visitas.py.
        if config.postgres_dsn:
            try:
                await asyncio.to_thread(visitas.preparar, config.postgres_dsn)
            except Exception as e:
                registro.warning("no se pudo preparar la tabla de visitas: %s", e)

        registro.info(
            "Agente escuchando - %s / %s - memoria %s - buffer %ss",
            config.proveedor,
            config.modelo,
            "Postgres" if config.modo == "produccion" else "SQLite",
            config.buffer_segundos,
        )
        yield
        # Al apagar, soltamos lo que estaba esperando. Sin esto, un deploy
        # justo en esos segundos se come la ráfaga de alguien.
        await buffer.vaciar()

    app = FastAPI(title="Agente - webhook de Chatwoot", lifespan=ciclo_de_vida)

    # -- Las rutas -------------------------------------------------------------

    @app.get("/salud")
    async def salud() -> JSONResponse:
        """Para que el servidor sepa que la app está viva.

        Coolify le pega a esto cada tanto. Si no contesta, reinicia el
        contenedor.

        Antes esto contestaba "ok" sin tocar la base — y nos pasó en
        producción que la conexión a Postgres se cortó sola mientras el
        proceso seguía vivo: Coolify lo mostraba sano y nadie recibía
        respuesta hasta que un cliente se quejaba. Ahora `verificar_memoria`
        (memoria.py) hace un chequeo de verdad contra Postgres — para
        SQLite no hace falta, es un archivo local.
        """
        error_memoria = await asyncio.to_thread(verificar_memoria, agente.checkpointer)

        cuerpo = {
            "estado": "ok" if error_memoria is None else "error",
            "proveedor": config.proveedor,
            "modelo": config.modelo,
            "memoria": "postgres" if config.modo == "produccion" else "sqlite",
        }

        if error_memoria is None:
            return JSONResponse(cuerpo)

        cuerpo["error_memoria"] = error_memoria
        registro.error("Chequeo de salud: la memoria no responde: %s", error_memoria)
        await asyncio.to_thread(
            alertas.avisar,
            config.alerta_telegram_token,
            config.alerta_telegram_chat_id,
            "salud_memoria",
            f"[agente-whatsapp] /salud detectó la memoria caída: {error_memoria}",
        )
        return JSONResponse(cuerpo, status_code=503)

    @app.post("/chatwoot/{token}")
    async def entrante(token: str, pedido: Request) -> JSONResponse:
        """Por acá entra todo lo que manda Chatwoot."""
        if not config.chatwoot_webhook_token or token != config.chatwoot_webhook_token:
            # Sin detalles en la respuesta: al que probó la URL no le decimos
            # si el token existe, si es corto o si le erró por una letra.
            registro.warning("Llamada con token equivocado")
            return JSONResponse({"error": "no autorizado"}, status_code=401)

        try:
            evento = await pedido.json()
        except Exception:
            return JSONResponse({"error": "esperaba JSON"}, status_code=400)

        entrante = canal.traducir(evento)

        if entrante is None or not canal.deberia_responder(entrante):
            # No es un error: es la mayoría de lo que llega. Cada respuesta
            # que manda el propio agente vuelve como un evento más.
            return JSONResponse({"estado": "ignorado"})

        if entrante.es_adjunto_sin_texto:
            # Un audio, una foto, un adjunto suelto: no hay nada que el
            # modelo pueda leer ahí. Contestamos algo fijo y ya — ni vale la
            # pena gastar un turno del modelo en algo tan predecible, y así
            # la persona no se queda pensando que no le llegó el mensaje.
            canal.enviar(entrante.conversacion, [MENSAJE_ADJUNTO_SIN_TEXTO])
            return JSONResponse({"estado": "recibido"})

        # Se suma a la ráfaga y contestamos ya. Lo que sigue pasa solo.
        await buffer.agregar(entrante.conversacion, entrante.texto)

        return JSONResponse({"estado": "recibido"})

    @app.get("/reservas/{accion}/{conversacion}/{evento_id}")
    async def reserva_confirmar(
        accion: str,
        conversacion: str,
        evento_id: str,
        token: str = "",
        profesional: str = "",
    ) -> HTMLResponse:
        """El link que le llega al negocio para aprobar o rechazar una
        reserva "tentative" (RESERVA_REQUIERE_APROBACION) — pero este GET
        **no aprueba ni rechaza nada todavía**, solo muestra una pantalla
        de confirmación con un botón. La acción de verdad la ejecuta
        `reserva_ejecutar()`, más abajo, con un POST — el que dispara el
        botón de esta pantalla.

        **Por qué en dos pasos, y no de una como antes.** Un GET que
        ejecuta una acción es cómodo (un link de un clic, sin formulario)
        pero es indistinguible de cualquier cosa que visite esa URL sin
        que una persona lo haya tocado — y eso pasa de verdad: Chatwoot (u
        otra app de mensajería) arma una vista previa de la nota
        buscándole título a la URL, y ESO ya dispara el GET. Reproducido
        en producción dos veces: la primera, dos avisos por un solo clic
        real (ver `candados_reserva` — el arreglo de ENTONCES); la
        segunda, el 12 sep 2026, un cliente recibió "tu turno quedó
        confirmado" sin que el dueño del negocio hubiera tocado nada — la
        vista previa sola alcanzó para aprobar la reserva de punta a
        punta (Calendar, WhatsApp, la visita registrada). Ningún candado
        soluciona eso: el problema no es que se dispare dos veces, es que
        se dispara UNA vez de más, sola. La solución de fondo es la de
        siempre en la web para esto (como "confirmar cancelación" antes de
        cancelar algo importante): separar "mirar" (GET, sin efectos) de
        "actuar" (POST, solo lo dispara un clic real — ninguna vista
        previa envía formularios).

        `profesional` (query param, vacío con un solo profesional) dice en
        qué agenda buscar el evento cuando el negocio tiene varios — lo
        pone `anotar_reserva` al armar el link (ver herramientas.py,
        `_aviso_de_aprobacion`) y la firma del token lo incluye, así que no
        se puede cambiar en la URL sin invalidar el link.
        """
        idioma = config.idioma_panel

        agenda, error = _validar_link_reserva(
            accion, config, calendario, profesional, conversacion, evento_id, token
        )
        if error is not None:
            return error

        try:
            evento = await asyncio.to_thread(agenda.obtener_evento, evento_id)
        except ErrorDeCalendario as e:
            if e.codigo not in (404, 410):
                registro.error("[%s] error al leer la reserva: %s", conversacion, e)
                return HTMLResponse(
                    _t(idioma, "algo_fallo", detalle=f"{type(e).__name__}: {e}"),
                    status_code=500,
                )
            evento = None
        except Exception as e:
            registro.error("[%s] error al leer la reserva: %s", conversacion, e)
            return HTMLResponse(
                _t(idioma, "algo_fallo", detalle=f"{type(e).__name__}: {e}"),
                status_code=500,
            )

        # Si ya se resolvió (por otro clic, o por esta misma vista previa
        # antes del arreglo), no hay nada que confirmar: mostrar el estado
        # tal cual, sin ofrecer un botón que ya no tiene sentido.
        if accion == "aprobar":
            if evento is None:
                return HTMLResponse(_pagina_simple(idioma, _t(idioma, "ya_no_existe")))
            if evento.get("status") == "confirmed":
                return HTMLResponse(_pagina_simple(idioma, _t(idioma, "ya_aprobada")))
        else:
            if evento is None:
                return HTMLResponse(_pagina_simple(idioma, _t(idioma, "ya_rechazada")))
            if evento.get("status") == "confirmed":
                return HTMLResponse(
                    _pagina_simple(idioma, _t(idioma, "ya_confirmada_no_rechazar"))
                )

        return HTMLResponse(
            _pagina_confirmar_reserva(
                idioma, accion, evento, conversacion, evento_id, token, profesional
            )
        )

    @app.post("/reservas/{accion}/{conversacion}/{evento_id}")
    async def reserva_ejecutar(
        accion: str,
        conversacion: str,
        evento_id: str,
        token: str = "",
        profesional: str = "",
    ) -> HTMLResponse:
        """Aprueba o rechaza de verdad — el POST que dispara el botón de
        `reserva_confirmar()`, arriba. Mismas validaciones (repetidas: este
        endpoint es alcanzable por su cuenta, no solo desde ese botón) y el
        mismo candado de siempre contra dos POST casi simultáneos.
        """
        idioma = config.idioma_panel

        agenda, error = _validar_link_reserva(
            accion, config, calendario, profesional, conversacion, evento_id, token
        )
        if error is not None:
            return error

        try:
            async with candados_reserva[f"{conversacion}:{evento_id}"]:
                # ¿Cómo está el evento ANTES de tocar nada? Un 404/410 acá
                # significa que ya no existe (un rechazo previo lo borró) —
                # no es un error, es justo lo que se necesita saber para no
                # repetir la acción. Cualquier otro código sí es un error de
                # verdad y sube tal cual al except de abajo.
                try:
                    evento = await asyncio.to_thread(agenda.obtener_evento, evento_id)
                except ErrorDeCalendario as e:
                    if e.codigo not in (404, 410):
                        raise
                    evento = None

                if accion == "aprobar":
                    if evento is None:
                        mensaje = _t(idioma, "ya_no_existe")
                    elif evento.get("status") == "confirmed":
                        mensaje = _t(idioma, "ya_aprobada")
                    else:
                        await asyncio.to_thread(agenda.aprobar_evento, evento_id)
                        aviso = await asyncio.to_thread(
                            _mensaje_en_idioma_de_conversacion,
                            agente,
                            conversacion,
                            "¡Tu turno quedó confirmado! Te esperamos.",
                        )
                        await asyncio.to_thread(canal.enviar, conversacion, [aviso])
                        await asyncio.to_thread(
                            canal.etiquetar, conversacion, "reserva-confirmada"
                        )
                        await asyncio.to_thread(
                            _registrar_visita_aprobada, canal, config, conversacion, evento
                        )
                        mensaje = _t(idioma, "aprobada_avisada")
                else:
                    if evento is None:
                        mensaje = _t(idioma, "ya_rechazada")
                    elif evento.get("status") == "confirmed":
                        # Simétrico al chequeo de "aprobar" de arriba.
                        # Reproducible: Chatwoot manda los dos links juntos
                        # (aprobar y rechazar) en la misma nota — si ya se
                        # aprobó una reserva y alguien toca el otro link por
                        # error, sin este chequeo se cancela un turno que el
                        # cliente ya sabe confirmado, y encima le llega un
                        # WhatsApp diciéndole que no se lo puede atender.
                        mensaje = _t(idioma, "ya_confirmada_no_rechazar")
                    else:
                        await asyncio.to_thread(agenda.cancelar_evento, evento_id)
                        aviso = await asyncio.to_thread(
                            _mensaje_en_idioma_de_conversacion,
                            agente,
                            conversacion,
                            "Por ese horario no vamos a poder atenderte, "
                            "disculpa. Escríbenos para coordinar otro.",
                        )
                        await asyncio.to_thread(canal.enviar, conversacion, [aviso])
                        await asyncio.to_thread(
                            canal.etiquetar, conversacion, "reserva-rechazada"
                        )
                        mensaje = _t(idioma, "rechazada_avisada")
        except Exception as e:
            registro.error("[%s] error al %s la reserva: %s", conversacion, accion, e)
            return HTMLResponse(
                _t(idioma, "algo_fallo", detalle=f"{type(e).__name__}: {e}"),
                status_code=500,
            )

        return HTMLResponse(_pagina_simple(idioma, mensaje))

    @app.get("/estadisticas")
    async def estadisticas(token: str = "") -> HTMLResponse:
        """Turnos por mes para el dueño del negocio: nuevos vs. recurrentes,
        y abajo el detalle turno por turno — quién, cuándo, primera vez o
        no (ver AGENTS.md, "Estadísticas para el dueño del negocio"). Mismo
        criterio de seguridad que /reservas/{accion}: un token fijo en la
        URL (DASHBOARD_SECRETO), sin pantalla de login que mantener.
        """
        if not config.dashboard_secreto or token != config.dashboard_secreto:
            # Sin detalles, mismo motivo que el token del webhook de
            # Chatwoot: a quien prueba la URL no le decimos si el secreto
            # existe, si es corto o si le erró por una letra.
            return HTMLResponse(_t(config.idioma_panel, "no_encontrado"), status_code=404)

        try:
            resumen = await asyncio.to_thread(visitas.resumen_mensual, config.postgres_dsn)
            detalle = await asyncio.to_thread(visitas.listar_visitas, config.postgres_dsn)
        except Exception as e:
            registro.error("no se pudo armar /estadisticas: %s", e)
            return HTMLResponse(
                f"<h1>No se pudo cargar</h1><p>{escape(f'{type(e).__name__}: {e}')}</p>",
                status_code=500,
            )

        return HTMLResponse(_pagina_estadisticas(resumen, detalle, config.idioma_panel))

    return app

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

registro = logging.getLogger("agente.webhook")

# Lo que ve la PERSONA cuando el agente revienta. A propósito no es el
# error crudo (antes sí lo era, siguiendo la regla general de "el error del
# proveedor no se esconde" — ver AGENTS.md): esa regla tiene sentido cuando
# "el usuario" sos vos probando en servidor.py/chat.py, pero acá del otro
# lado hay un cliente de verdad de la empresa que te contrata, y un
# "OperationalError: consuming input failed..." en pleno WhatsApp no es
# información, es una mala experiencia. El detalle real sigue yendo a los
# logs (y, si está configurado, a la alerta de Telegram) tal cual antes.
MENSAJE_ERROR_GENERICO = (
    "Uy, se me rompió algo de mi lado. Ya me avisaron y lo estamos mirando "
    "— probá de nuevo en un rato."
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


def _pagina_estadisticas(resumen: list[dict], detalle: list[dict]) -> str:
    """Arma el HTML de /estadisticas a mano — sin motor de plantillas ni
    JavaScript, mismo criterio liviano que el resto del repo (ver
    AGENTS.md: "web/app.py: un solo HTML, sin build ni npm").

    Tres bloques: tarjetas con el mes más reciente y el total histórico
    (para que el número grande se vea de una, sin tener que sumar la
    tabla a mano), el resumen mes a mes, y el detalle turno por turno.
    """
    ultimo = resumen[0] if resumen else {"turnos": 0, "nuevos": 0, "recurrentes": 0}
    total_historico = sum(f["turnos"] for f in resumen)

    if not resumen:
        resumen_filas = (
            '<tr><td colspan="4" class="vacio">Todavía no hay turnos registrados.</td></tr>'
        )
    else:
        resumen_filas = "".join(
            f"<tr><td>{escape(f['mes'])}</td><td>{f['turnos']}</td>"
            f"<td>{f['nuevos']}</td><td>{f['recurrentes']}</td></tr>"
            for f in resumen
        )

    if not detalle:
        detalle_filas = (
            '<tr><td colspan="6" class="vacio">Todavía no hay turnos registrados.</td></tr>'
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
            f"<td><span class=\"chip {'nueva' if v['es_nueva'] else 'recurrente'}\">"
            f"{'Nueva' if v['es_nueva'] else 'Recurrente'}</span></td></tr>"
            for v in detalle
        )

    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Estadísticas</title>
<style>
  :root {{
    --tinta: #1c2530; --tinta-suave: #5b6672; --borde: #e3e7ec;
    --fondo: #f7f8fa; --superficie: #ffffff;
    --acento: #2f6f4f; --acento-suave: #e6f2ec;
    --recurrente: #eef1f5; --recurrente-texto: #465063;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: var(--fondo); color: var(--tinta);
    margin: 0; padding: 40px 20px 80px;
  }}
  .contenedor {{ max-width: 880px; margin: 0 auto; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 4px; }}
  .subtitulo {{ color: var(--tinta-suave); margin: 0 0 32px; font-size: .95rem; }}
  .tarjetas {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 40px; }}
  .tarjeta {{
    background: var(--superficie); border: 1px solid var(--borde); border-radius: 12px;
    padding: 18px 22px; flex: 1; min-width: 140px;
  }}
  .tarjeta .numero {{ display: block; font-size: 1.9rem; font-weight: 600; line-height: 1.2; }}
  .tarjeta .etiqueta {{ display: block; color: var(--tinta-suave); font-size: .8rem; margin-top: 2px; }}
  h2 {{ font-size: 1.05rem; margin: 40px 0 4px; }}
  .ayuda {{ color: var(--tinta-suave); font-size: .85rem; margin: 0 0 12px; }}
  .tabla-scroll {{ overflow-x: auto; border: 1px solid var(--borde); border-radius: 10px; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--superficie); min-width: 480px; }}
  th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--borde); font-size: .92rem; white-space: nowrap; }}
  th {{ color: var(--tinta-suave); font-size: .75rem; text-transform: uppercase; letter-spacing: .03em; background: var(--fondo); }}
  tr:last-child td {{ border-bottom: none; }}
  td.vacio {{ color: var(--tinta-suave); text-align: center; padding: 24px; white-space: normal; }}
  .chip {{ display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: .78rem; font-weight: 600; }}
  .chip.nueva {{ background: var(--acento-suave); color: var(--acento); }}
  .chip.recurrente {{ background: var(--recurrente); color: var(--recurrente-texto); }}
</style>
</head>
<body>
<div class="contenedor">
  <h1>Estadísticas</h1>
  <p class="subtitulo">Turnos confirmados: cuántos, quiénes, y si vuelven.</p>

  <div class="tarjetas">
    <div class="tarjeta"><span class="numero">{ultimo['turnos']}</span><span class="etiqueta">Turnos este mes</span></div>
    <div class="tarjeta"><span class="numero">{ultimo['nuevos']}</span><span class="etiqueta">Nuevos</span></div>
    <div class="tarjeta"><span class="numero">{ultimo['recurrentes']}</span><span class="etiqueta">Recurrentes</span></div>
    <div class="tarjeta"><span class="numero">{total_historico}</span><span class="etiqueta">Total histórico</span></div>
  </div>

  <h2>Turnos por mes</h2>
  <div class="tabla-scroll"><table>
    <thead><tr><th>Mes</th><th>Turnos</th><th>Nuevos</th><th>Recurrentes</th></tr></thead>
    <tbody>{resumen_filas}</tbody>
  </table></div>

  <h2>Detalle</h2>
  <p class="ayuda">Últimos {len(detalle)} turnos, el más reciente primero.</p>
  <div class="tabla-scroll"><table>
    <thead><tr><th>Nombre</th><th>Teléfono</th><th>Motivo</th><th>Fecha</th><th>Hora</th><th></th></tr></thead>
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
    # "tentative". Si el negocio no conectó calendario, queda None y esas
    # rutas avisan que no hay nada que aprobar, en vez de fallar.
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
                mensajes = [MENSAJE_ERROR_GENERICO]
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
    async def reserva_pendiente(
        accion: str, conversacion: str, evento_id: str, token: str = ""
    ) -> HTMLResponse:
        """El link que alguien del negocio abre desde el celular para
        aprobar o rechazar una reserva "tentative" (RESERVA_REQUIERE_APROBACION).

        Es HTML y no JSON a propósito: esto lo abre una persona en el
        navegador, no un programa. No hay login — la seguridad es el token
        de la URL, mismo criterio que /chatwoot/<token> (ver aprobacion.py).

        **Es un GET que ejecuta una acción — a propósito, para que sea un
        link de un solo clic sin formulario ni JS — pero eso lo hace
        vulnerable a que alguien más lo dispare sin que la persona lo haya
        tocado.** Reproducido en producción: la app de Chatwoot en iPhone
        precargó el link para armar una vista previa de la nota, y ese GET
        automático ya había aprobado la reserva antes de que el dueño del
        negocio le diera clic él mismo — el segundo GET (el suyo) chocó
        contra un evento que ya no estaba "tentative". Por eso, antes de
        tocar nada, se fija cómo está el evento AHORA: si ya se resolvió
        (aprobado, o ya no existe porque se rechazó antes), avisa eso en
        vez de repetir el WhatsApp a la persona y el pedido a Calendar.
        """
        if accion not in aprobacion.ACCIONES:
            return HTMLResponse("Acción desconocida.", status_code=404)

        if calendario is None or not config.reserva_secreto:
            return HTMLResponse(
                "Este negocio no tiene la aprobación por link configurada "
                "(faltan GOOGLE_CALENDAR_ID/GOOGLE_SERVICE_ACCOUNT_JSON o "
                "RESERVA_SECRETO en el .env).",
                status_code=404,
            )

        if not aprobacion.valido(config.reserva_secreto, conversacion, evento_id, token):
            return HTMLResponse("Link inválido o vencido.", status_code=403)

        try:
            # ¿Cómo está el evento ANTES de tocar nada? Un 404/410 acá
            # significa que ya no existe (un rechazo previo lo borró) — no
            # es un error, es justo lo que se necesita saber para no repetir
            # la acción. Cualquier otro código sí es un error de verdad y
            # sube tal cual al except de abajo.
            try:
                evento = await asyncio.to_thread(calendario.obtener_evento, evento_id)
            except ErrorDeCalendario as e:
                if e.codigo not in (404, 410):
                    raise
                evento = None

            if accion == "aprobar":
                if evento is None:
                    mensaje = "Esta reserva ya no existe (puede que se haya rechazado antes)."
                elif evento.get("status") == "confirmed":
                    mensaje = "Esta reserva ya estaba aprobada. No hace falta hacer nada más."
                else:
                    await asyncio.to_thread(calendario.aprobar_evento, evento_id)
                    await asyncio.to_thread(
                        canal.enviar,
                        conversacion,
                        ["¡Tu turno quedó confirmado! Te esperamos."],
                    )
                    await asyncio.to_thread(
                        canal.etiquetar, conversacion, "reserva-confirmada"
                    )
                    await asyncio.to_thread(
                        _registrar_visita_aprobada, canal, config, conversacion, evento
                    )
                    mensaje = "Reserva aprobada. Ya se le avisó a la persona."
            else:
                if evento is None:
                    mensaje = "Esta reserva ya había sido rechazada antes."
                else:
                    await asyncio.to_thread(calendario.cancelar_evento, evento_id)
                    await asyncio.to_thread(
                        canal.enviar,
                        conversacion,
                        [
                            "Por ese horario no vamos a poder atenderte, "
                            "disculpá. Escribinos para coordinar otro."
                        ],
                    )
                    await asyncio.to_thread(
                        canal.etiquetar, conversacion, "reserva-rechazada"
                    )
                    mensaje = "Reserva rechazada. Ya se le avisó a la persona."
        except Exception as e:
            registro.error("[%s] error al %s la reserva: %s", conversacion, accion, e)
            return HTMLResponse(
                f"Algo falló: {type(e).__name__}: {e}", status_code=500
            )

        return HTMLResponse(f"<h1>Listo</h1><p>{mensaje}</p>")

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
            return HTMLResponse("No encontrado.", status_code=404)

        try:
            resumen = await asyncio.to_thread(visitas.resumen_mensual, config.postgres_dsn)
            detalle = await asyncio.to_thread(visitas.listar_visitas, config.postgres_dsn)
        except Exception as e:
            registro.error("no se pudo armar /estadisticas: %s", e)
            return HTMLResponse(
                f"<h1>No se pudo cargar</h1><p>{escape(f'{type(e).__name__}: {e}')}</p>",
                status_code=500,
            )

        return HTMLResponse(_pagina_estadisticas(resumen, detalle))

    return app

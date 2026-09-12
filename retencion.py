"""Borrado de datos por la política de retención (2 años por default).

    python retencion.py            # solo mira, no borra nada — el default
    python retencion.py --aplicar  # borra de verdad

Mismo espíritu que `recordatorios.py`: un programa que corre solo y
termina, pensado para dejarlo programado (una Scheduled Task de Coolify,
un cron) — a diferencia de aquel, no hace falta que corra seguido: una vez
por semana o por mes alcanza de sobra, esto no es urgente minuto a minuto.

**Por qué el modo de prueba es el default, no `--aplicar`.** Un DELETE no
tiene deshacer. La primera vez que corra esto contra una Postgres de
verdad, mejor que se pueda mirar la lista de "esto borraría" antes de que
borre algo — y conviene seguir corriéndolo así cada vez que cambie algo
en el negocio (un cliente nuevo, una migración), no solo la primera vez.

Qué revisa, y por qué justo estos tres lugares (ver AGENTS.md → "Dónde
termina el dato de una persona"):

  1. **Memoria de conversaciones en Postgres** (los checkpoints de
     LangGraph, `MODO=produccion`) — conversaciones sin ningún mensaje
     nuevo hace más de RETENCION_DIAS. Se resuelve con la propia API de
     `PostgresSaver` (`list()`/`delete_thread()`), no con SQL a mano
     contra su esquema interno — ese esquema no es público y cambia entre
     versiones de la librería.
  2. **La tabla `visitas`** (`visitas.py`) — turnos de hace más de
     RETENCION_DIAS (`visitas.borrar_visitas_viejas`).
  3. **Las notas del contacto en Chatwoot** (las que deja
     `actualizar_ficha_cliente`, `herramientas.py`) — una por una, según
     su propio `created_at`. Hay que recorrer TODOS los contactos de la
     cuenta: la API de Chatwoot no tiene un "notas vencidas de cualquier
     contacto" de una sola consulta.

Lo que NO toca (fuera del alcance de este programa):

  · **Los eventos en Google Calendar.** Son del negocio, no nuestros — su
    calendario, su propia política de cuánto los guarda.
  · **Las notas de CONVERSACIÓN en Chatwoot** (`Chatwoot.anotar()`, la
    nota de "Reserva\\nNombre: ...") ni las conversaciones mismas.
    Chatwoot es la bandeja del negocio: no es este programa el que decide
    cuándo se borra algo de ahí.
  · **El backup de Postgres.** Tiene su propia retención en Coolify/el
    servidor — aparte de esto.

Sin `POSTGRES_DSN`, se saltan los pasos 1 y 2 (mismo criterio que
`recordatorios.py`: termina sin error). Sin `CHATWOOT_URL`/`CHATWOOT_TOKEN`,
se salta el paso 3.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from agente.consola import preparar  # noqa: E402

preparar()  # antes de imprimir nada, para que las tildes no rompan Windows

from agente import memoria, visitas  # noqa: E402
from agente.canales.chatwoot import Chatwoot  # noqa: E402
from agente.config import Config  # noqa: E402

AMBAR = "\033[38;5;214m"
GRIS = "\033[90m"
ROJO = "\033[91m"
FIN = "\033[0m"

# "Política acordada (11 sep 2026): retener 2 años por default" — ver
# AGENTS.md. Una constante acá, no una variable de .env: hoy es la misma
# para todos los clientes; si algún día uno necesita otra cosa, ahí sí
# conviene moverla a Config (mismo criterio que CANCELACION_HORAS_MINIMAS).
RETENCION_DIAS = 365 * 2


def main() -> int:
    aplicar = "--aplicar" in sys.argv[1:]
    config = Config.desde_entorno()

    corte = datetime.now(timezone.utc) - timedelta(days=RETENCION_DIAS)
    corte_fecha = corte.date().isoformat()  # para "visitas" (columna DATE)
    corte_iso = corte.isoformat()  # para comparar contra checkpoint["ts"]

    if aplicar:
        print(f"{ROJO}Modo --aplicar: esto borra de verdad. Sin deshacer.{FIN}")
    else:
        print(
            f"{AMBAR}Modo de prueba — no se borra nada. Corré con --aplicar "
            f"para borrar de verdad.{FIN}"
        )
    print(f"{GRIS}Corte: antes de {corte_fecha} (retención de {RETENCION_DIAS} días).{FIN}")

    _conversaciones(config, corte_iso, aplicar)
    _visitas(config, corte_fecha, aplicar)
    _notas_de_contacto(config, corte, aplicar)

    return 0


def _conversaciones(config: Config, corte_iso: str, aplicar: bool) -> None:
    """Borra (o cuenta) las conversaciones de la memoria de LangGraph sin
    actividad desde antes del corte."""
    if not config.postgres_dsn:
        print(f"{GRIS}Sin POSTGRES_DSN: no hay memoria de conversaciones que revisar.{FIN}")
        return

    saver = memoria.postgres(config.postgres_dsn)
    try:
        ultimo_por_hilo: dict[str, str] = {}
        for tupla in saver.list(None):
            configurable = tupla.config.get("configurable") or {}
            thread_id = configurable.get("thread_id")
            if not thread_id:
                continue
            ts = (tupla.checkpoint or {}).get("ts") or ""
            if ts > ultimo_por_hilo.get(thread_id, ""):
                ultimo_por_hilo[thread_id] = ts

        vencidos = sorted(tid for tid, ts in ultimo_por_hilo.items() if ts and ts < corte_iso)

        print(
            f"{GRIS}conversaciones: {len(vencidos)} de {len(ultimo_por_hilo)} "
            f"vencida(s).{FIN}"
        )
        for thread_id in vencidos:
            if aplicar:
                saver.delete_thread(thread_id)
            etiqueta = "borrada" if aplicar else "a borrar"
            print(f"  [{etiqueta}] conversación {thread_id}")
    finally:
        saver.conn.close()


def _visitas(config: Config, corte_fecha: str, aplicar: bool) -> None:
    """Borra (o avisa) las visitas de antes del corte."""
    if not config.postgres_dsn:
        return  # ya se avisó en _conversaciones()

    if not aplicar:
        # No hay un "contar sin borrar" en visitas.py: un COUNT(*) aparte
        # para el modo de prueba sería otra conexión más solo para esto.
        # Se anota la intención y listo — el número real sale con
        # --aplicar.
        print(
            f"{GRIS}visitas: se borrarían las de antes de {corte_fecha} "
            f"(corré con --aplicar para ver cuántas).{FIN}"
        )
        return

    borradas = visitas.borrar_visitas_viejas(config.postgres_dsn, corte_fecha)
    print(f"{GRIS}visitas: {borradas} borrada(s) (de antes de {corte_fecha}).{FIN}")


def _notas_de_contacto(config: Config, corte: datetime, aplicar: bool) -> None:
    """Borra (o cuenta) las notas de contacto de Chatwoot de antes del corte."""
    if not config.chatwoot_url or not config.chatwoot_token:
        print(f"{GRIS}Sin Chatwoot configurado: no hay notas de contacto que revisar.{FIN}")
        return

    chatwoot = Chatwoot(
        url=config.chatwoot_url,
        token=config.chatwoot_token,
        cuenta_id=config.chatwoot_cuenta_id,
    )

    revisadas = 0
    vencidas = 0
    pagina = 1
    while True:
        contactos = chatwoot.listar_contactos(pagina)
        if not contactos:
            break

        for contacto in contactos:
            contacto_id = contacto.get("id")
            if not contacto_id:
                continue

            try:
                notas = chatwoot.listar_notas_contacto(contacto_id)
            except Exception as e:
                print(
                    f"{ROJO}contacto {contacto_id}: no se pudieron consultar "
                    f"sus notas: {type(e).__name__}: {e}{FIN}"
                )
                continue

            for nota in notas:
                revisadas += 1
                creada = _fecha_de_nota(nota)
                if creada is None or creada >= corte:
                    continue

                vencidas += 1
                if not aplicar:
                    continue

                try:
                    chatwoot.borrar_nota_contacto(contacto_id, nota.get("id"))
                except Exception as e:
                    print(
                        f"{ROJO}contacto {contacto_id}, nota {nota.get('id')}: "
                        f"no se pudo borrar: {type(e).__name__}: {e}{FIN}"
                    )

        pagina += 1

    etiqueta = "borrada(s)" if aplicar else "a borrar (corré con --aplicar)"
    print(f"{GRIS}notas de contacto: {vencidas} de {revisadas} {etiqueta}.{FIN}")


def _fecha_de_nota(nota: dict) -> datetime | None:
    """El `created_at` de una nota de contacto, como datetime — Chatwoot
    suele mandarlo como timestamp Unix (segundos), pero **esto no se probó
    todavía contra una cuenta de Chatwoot de verdad** (ver
    `Chatwoot.listar_notas_contacto`, en canales/chatwoot.py). Si tu
    versión lo manda distinto (un string ISO, por ejemplo), esta es la
    única función que hay que tocar — ya intenta las dos formas."""
    valor = nota.get("created_at")
    if valor is None:
        return None

    if isinstance(valor, (int, float)):
        return datetime.fromtimestamp(valor, tz=timezone.utc)

    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None


if __name__ == "__main__":
    raise SystemExit(main())

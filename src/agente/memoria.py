"""La memoria del agente.

Las APIs de los modelos NO recuerdan nada: cada llamada es independiente.
Que el agente "se acuerde" es puro trabajo nuestro — hay que volver a mandarle
la conversación entera en cada mensaje.

LangGraph resuelve eso con los checkpointers. Un checkpointer guarda el estado
de cada conversación (identificada por un thread_id) y lo vuelve a cargar solo.

    thread_id     = una conversación
    checkpointer  = dónde se guardan esas conversaciones

En el .env elegís con una variable:

    MODO=test        → SQLite, un archivo en tu computadora. Cero instalación.
    MODO=produccion  → Postgres. Para cuando hay varios procesos atendiendo.

Y hay una tercera, `ram()`, que no se guarda en ningún lado: sirve para los
tests y para ver el agente en su forma más simple.

El agente no cambia entre un modo y el otro. Cambia esta línea y nada más.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from .config import Config


def crear_memoria(config: "Config") -> "BaseCheckpointSaver":
    """Devuelve la memoria que corresponda al MODO del .env."""
    if config.modo == "produccion":
        if not config.postgres_dsn:
            raise ValueError(
                "MODO=produccion necesita POSTGRES_DSN en el .env.\n"
                "Ejemplo: POSTGRES_DSN=postgresql://usuario:clave@localhost:5432/agente"
            )
        return postgres(config.postgres_dsn)

    return sqlite(config.sqlite_ruta)


def verificar(checkpointer: "BaseCheckpointSaver") -> str | None:
    """Prueba que la memoria funcione de verdad. `None` = sana.

    La usa /salud (web/webhook.py). Nace del mismo caso real de arriba: un
    `/salud` que solo contesta "ok" sin tocar la base no se entera de que
    Postgres está inalcanzable — el proceso sigue vivo, así que Coolify lo
    sigue mostrando sano mientras nadie recibe respuesta.
    Solo hace falta para Postgres: SQLite es un archivo local, si el
    proceso está vivo funciona. Se detecta por el nombre del módulo en vez
    de importar `PostgresSaver` para no obligar a tener psycopg instalado
    en MODO=test.
    """
    if not type(checkpointer).__module__.startswith("langgraph.checkpoint.postgres"):
        return None

    try:
        with checkpointer.conn.connection(timeout=5) as conexion:
            conexion.execute("SELECT 1")
        return None
    except Exception as e:
        return f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------


def ram() -> "BaseCheckpointSaver":
    """Memoria en RAM. Se borra al cerrar el programa.

    Es la forma más simple de ver cómo funciona: no guarda nada en ningún lado.
    La usan los tests.
    """
    from langgraph.checkpoint.memory import InMemorySaver

    return InMemorySaver()


def sqlite(ruta: str = "datos/conversaciones.db") -> "BaseCheckpointSaver":
    """Memoria en un archivo. Sobrevive al reinicio. → MODO=test

    Un archivo, cero servidores. Alcanza de sobra para desarrollar y para un
    bot chico de Telegram con un solo proceso atendiendo.
    """
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    archivo = Path(ruta)
    archivo.parent.mkdir(parents=True, exist_ok=True)

    # check_same_thread=False porque el servidor web atiende en varios hilos.
    conexion = sqlite3.connect(archivo, check_same_thread=False)
    guardador = SqliteSaver(conexion)
    guardador.setup()
    return guardador


def postgres(dsn: str) -> "BaseCheckpointSaver":
    """Memoria en Postgres. → MODO=produccion

    Para cuando hay muchas conversaciones a la vez y más de un proceso
    respondiendo: es el caso de WhatsApp.
    """
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool
    except ImportError as e:
        # El motivo real va adentro del mensaje a propósito. Son dos fallas
        # distintas que se ven igual desde afuera: que falte el paquete, o que
        # esté puesto pero sin la libpq del sistema (el clásico "no pq wrapper
        # available" en Windows). Sin el detalle, la segunda te manda a
        # instalar algo que ya tenías.
        raise ImportError(
            f"MODO=produccion necesita el conector de Postgres.\n\n"
            f"    pip install \"langgraph-checkpoint-postgres>=3.1,<4\" \"psycopg[binary]\"\n\n"
            f"El error de abajo dice cuál de los dos falta:\n    {type(e).__name__}: {e}"
        ) from None

    # Un pool en vez de una única conexión fija. Antes `PostgresSaver` vivía
    # sobre UNA conexión abierta al arrancar el proceso y nunca más tocada:
    # si Postgres la cortaba sola (un blip de red, un timeout de conexión
    # idle — pasó en producción, Postgres seguía sano, solo se cayó el
    # cable) el checkpointer quedaba muerto hasta que alguien lo notaba y
    # reiniciaba el proceso a mano. `/salud` ni se enteraba, porque no
    # tocaba la base (ver web/webhook.py).
    #
    # Con un pool, cada operación de PostgresSaver pide una conexión nueva
    # (`_internal.get_connection`, en la librería) en vez de reusar siempre
    # la misma, y el pool se encarga de descartar las que se cortaron y
    # abrir otras — sin que el agente se entere. `max_idle`/`max_lifetime`
    # (los defaults de psycopg_pool: 10 min / 1 hora) además reciclan las
    # conexiones antes de que lleguen a quedar tan viejas como para que
    # algún firewall/NAT de por medio las corte solo.
    #
    # kwargs replica lo que `PostgresSaver.from_conn_string` le pasaba a la
    # conexión única (autocommit, sin prepared statements, filas como dict).
    pool = ConnectionPool(
        dsn,
        min_size=1,
        max_size=5,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        check=ConnectionPool.check_connection,
        open=True,
    )
    guardador = PostgresSaver(pool)
    guardador.setup()

    # A diferencia de antes, acá no hace falta ningún truco para que el pool
    # sobreviva al recolector de basura: `PostgresSaver` ya lo guarda como
    # `self.conn`, y `guardador` es lo que se devuelve y queda referenciado
    # por el agente. El pool vive exactamente lo que vive la memoria.
    return guardador

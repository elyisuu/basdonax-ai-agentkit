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
    except ImportError:
        raise ImportError(
            "MODO=produccion necesita el conector de Postgres, que no viene "
            "instalado por defecto:\n\n"
            "    pip install langgraph-checkpoint-postgres\n"
        ) from None

    # El pool queda abierto mientras viva el proceso: si lo cerráramos acá,
    # el checkpointer dejaría de funcionar en el primer mensaje.
    contexto = PostgresSaver.from_conn_string(dsn)
    guardador = contexto.__enter__()
    guardador.setup()
    return guardador

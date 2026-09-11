"""Registro de visitas, para las estadísticas que ve el dueño del negocio
(cuántos turnos nuevos y recurrentes tuvo, por ejemplo).

Vive en la MISMA Postgres que la memoria de conversaciones (MODO=produccion,
POSTGRES_DSN), pero en su tabla propia — `visitas` — con su propia conexión:
`herramientas.py` no tiene acceso al pool del checkpointer de LangGraph (ese
objeto lo arma agente.py y no llega a través de RunnableConfig), así que se
abre una conexión nueva por llamada, mismo criterio que
`_chatwoot_del_config()`/`_calendario_del_config()` en herramientas.py.

**Esto NO es una herramienta que el modelo decide llamar.** A diferencia de
`actualizar_ficha_cliente` (que el modelo puede o no usar — y de hecho, en
una prueba real, no la usó), `registrar_visita()` la llama el CÓDIGO,
directo, en el momento exacto en que un turno queda confirmado de verdad:

  · `anotar_reserva()` (herramientas.py), cuando confirma de una.
  · `web/webhook.py`, la ruta que aprueba una reserva "tentative", recién
    cuando alguien del negocio la aprueba — no antes, para no contar
    turnos que después se terminan rechazando.

Así las estadísticas no dependen de que el modelo se acuerde de nada.

Sin `POSTGRES_DSN` (MODO=test, o Postgres no configurado), no hace nada: ni
`preparar()` ni `registrar_visita()` fallan, simplemente no hay dónde
guardar. Mismo espíritu que `recordatorios.py`/`alertas.py`: opcional, no
rompe nada si no está.
"""

from __future__ import annotations

import logging

registro = logging.getLogger("agente.visitas")


def preparar(dsn: str) -> None:
    """Crea la tabla si no existe. Se llama una sola vez al arrancar (ver
    el `ciclo_de_vida` de web/webhook.py) — mismo momento en que
    `PostgresSaver.setup()` arma las suyas para la memoria."""
    if not dsn:
        return

    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conexion:
        conexion.execute(
            """
            CREATE TABLE IF NOT EXISTS visitas (
                id SERIAL PRIMARY KEY,
                contacto_id TEXT NOT NULL,
                telefono TEXT NOT NULL DEFAULT '',
                nombre TEXT NOT NULL DEFAULT '',
                fecha_turno DATE NOT NULL,
                hora_turno TEXT NOT NULL,
                creado_en TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        # Para "¿ya había venido antes?" (nuevo vs. recurrente): sin este
        # índice, esa consulta barre la tabla entera cada vez.
        conexion.execute(
            "CREATE INDEX IF NOT EXISTS visitas_contacto_idx ON visitas (contacto_id)"
        )


def registrar_visita(
    dsn: str,
    contacto_id: str,
    fecha_turno: str,
    hora_turno: str,
    telefono: str = "",
    nombre: str = "",
) -> bool:
    """Guarda una visita confirmada. Devuelve si se pudo guardar.

    Nunca revienta: perder una estadística no puede voltear una reserva de
    verdad ni una aprobación — mismo criterio que `_avisar_a_chatwoot()` en
    herramientas.py. El detalle del error queda en el log, no en lo que ve
    la persona.
    """
    if not dsn or not contacto_id:
        return False

    try:
        import psycopg

        with psycopg.connect(dsn, autocommit=True) as conexion:
            conexion.execute(
                """
                INSERT INTO visitas
                    (contacto_id, telefono, nombre, fecha_turno, hora_turno)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (contacto_id, telefono, nombre, fecha_turno, hora_turno),
            )
        return True
    except Exception as e:
        registro.warning("no se pudo registrar la visita de %s: %s", contacto_id, e)
        return False

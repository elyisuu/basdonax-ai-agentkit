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
                motivo TEXT NOT NULL DEFAULT '',
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
        # ADD COLUMN IF NOT EXISTS: para cuando la tabla YA existía sin esta
        # columna (se sumó después del primer despliegue) — el CREATE TABLE
        # de arriba no toca una tabla que ya está. Este patrón es el que
        # seguir la próxima vez que se agregue un campo acá.
        conexion.execute(
            "ALTER TABLE visitas ADD COLUMN IF NOT EXISTS motivo TEXT NOT NULL DEFAULT ''"
        )


def registrar_visita(
    dsn: str,
    contacto_id: str,
    fecha_turno: str,
    hora_turno: str,
    telefono: str = "",
    nombre: str = "",
    motivo: str = "",
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
                    (contacto_id, telefono, nombre, motivo, fecha_turno, hora_turno)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (contacto_id, telefono, nombre, motivo, fecha_turno, hora_turno),
            )
        return True
    except Exception as e:
        registro.warning("no se pudo registrar la visita de %s: %s", contacto_id, e)
        return False


def resumen_mensual(dsn: str) -> list[dict]:
    """Turnos por mes, separados en nuevos (la primera visita registrada de
    esa persona) y recurrentes (ya tenía alguna antes) — ver AGENTS.md,
    "Estadísticas para el dueño del negocio". El más reciente primero.

    A diferencia de `registrar_visita()`, acá SÍ deja subir el error si la
    conexión falla: no hay ninguna reserva real que proteger, así que
    `/estadisticas` (web/webhook.py) puede mostrar el problema en vez de
    una tabla vacía que parece "no tuviste turnos" sin serlo. Sin DSN,
    devuelve una lista vacía sin más — no hay nada configurado que fallar.
    """
    if not dsn:
        return []

    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conexion:
        filas = conexion.execute(
            """
            WITH numeradas AS (
                SELECT
                    fecha_turno,
                    ROW_NUMBER() OVER (
                        PARTITION BY contacto_id
                        ORDER BY fecha_turno, hora_turno, id
                    ) AS numero_visita
                FROM visitas
            )
            SELECT
                to_char(fecha_turno, 'YYYY-MM') AS mes,
                COUNT(*) AS turnos,
                COUNT(*) FILTER (WHERE numero_visita = 1) AS nuevos,
                COUNT(*) FILTER (WHERE numero_visita > 1) AS recurrentes
            FROM numeradas
            GROUP BY mes
            ORDER BY mes DESC
            """
        ).fetchall()

    return [
        {"mes": mes, "turnos": turnos, "nuevos": nuevos, "recurrentes": recurrentes}
        for mes, turnos, nuevos, recurrentes in filas
    ]


def listar_visitas(dsn: str, limite: int = 200) -> list[dict]:
    """El detalle turno por turno (quién, cuándo, primera vez o no) — para
    la segunda tabla de `/estadisticas`, abajo del resumen mensual. La más
    reciente primero.

    `limite` para no mandar la tabla entera a una página HTML el día que
    haya miles de filas — 200 alcanza de sobra para "¿quién vino esta
    semana/mes?", que es para lo que sirve esta vista. Mismo criterio que
    `resumen_mensual()`: sin DSN, lista vacía; con DSN pero sin conexión,
    deja subir el error.
    """
    if not dsn:
        return []

    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conexion:
        filas = conexion.execute(
            """
            SELECT
                nombre,
                telefono,
                motivo,
                to_char(fecha_turno, 'YYYY-MM-DD') AS fecha,
                hora_turno,
                ROW_NUMBER() OVER (
                    PARTITION BY contacto_id
                    ORDER BY fecha_turno, hora_turno, id
                ) = 1 AS es_nueva
            FROM visitas
            ORDER BY fecha_turno DESC, hora_turno DESC, id DESC
            LIMIT %s
            """,
            (limite,),
        ).fetchall()

    return [
        {
            "nombre": nombre,
            "telefono": telefono,
            "motivo": motivo,
            "fecha": fecha,
            "hora": hora,
            "es_nueva": es_nueva,
        }
        for nombre, telefono, motivo, fecha, hora, es_nueva in filas
    ]


def borrar_visitas_viejas(dsn: str, antes_de: str) -> int:
    """Borra las visitas con `fecha_turno` anterior a `antes_de`
    (AAAA-MM-DD). Devuelve cuántas filas borró.

    La usa `retencion.py` (política de 2 años, ver AGENTS.md → "Dónde
    termina el dato de una persona"). Sin DSN, no hace nada y devuelve 0 —
    mismo criterio que el resto de este archivo.
    """
    if not dsn:
        return 0

    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conexion:
        cursor = conexion.execute(
            "DELETE FROM visitas WHERE fecha_turno < %s", (antes_de,)
        )
        return cursor.rowcount

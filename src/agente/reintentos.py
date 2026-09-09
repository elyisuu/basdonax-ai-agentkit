"""Reintentos con backoff para llamadas HTTP a APIs externas.

Sin esto, un timeout de red suelto (una conexión que se corta a mitad de
camino, un 502 pasajero) tira abajo una reserva o una respuesta aunque el
próximo intento, medio segundo después, hubiera andado bien. Lo usan
`calendario.py` y `canales/chatwoot.py`, cada uno alrededor de su propio
`urllib.request.urlopen`.

Solo se reintenta lo que tiene sentido reintentar: errores de red y 5xx del
otro lado (un problema de ELLOS, no nuestro). Un 4xx —token vencido, pedido
mal armado— da el mismo error las tres veces: ahí se sube de una, para no
hacer esperar a la persona por algo que no se va a arreglar solo.

**La excepción es el 403 "rate limit" de Google.** Reproducido en
producción: `Calendario.aprobar_evento()` devolvió
`403 { "error": { "errors": [{"domain": "usageLimits", "reason":
"rateLimitExceeded", ...}] } }` al aprobar una reserva desde el link. Es un
403 —un 4xx—, así que con la regla de arriba se sube de una... pero para
ESTE 403 puntual Google pide lo contrario: reintentar con backoff es
justamente la solución que documentan ellos mismos (no es un pedido mal
armado, es que hubo una ráfaga de pedidos a esa agenda/proyecto en poco
tiempo). Por eso `_es_transitorio()` mira el cuerpo de la respuesta y hace
una excepción puntual para `rateLimitExceeded`/`userRateLimitExceeded`; el
resto de los 403 (permisos, token vencido) siguen sin reintentarse.
"""

from __future__ import annotations

import io
import json
import time
import urllib.error
from typing import Callable, TypeVar

T = TypeVar("T")

INTENTOS = 3
ESPERA_INICIAL = 0.5  # segundos; se duplica en cada reintento (0.5, 1, 2...)

# Los únicos 403 que vale la pena reintentar: los de cuota de Google
# (Calendar y, en general, las APIs de Google Cloud usan este mismo formato
# de error). Un 403 de permisos o de autenticación no trae ninguna de estas
# razones y sigue subiendo de una.
RAZONES_DE_CUOTA = {"rateLimitExceeded", "userRateLimitExceeded"}


def _es_transitorio(e: urllib.error.HTTPError, cuerpo: bytes) -> bool:
    """Si vale la pena reintentar este HTTPError."""
    if e.code >= 500:
        return True
    if e.code != 403:
        return False
    try:
        razones = {
            err.get("reason")
            for err in json.loads(cuerpo.decode("utf-8", "replace"))
            .get("error", {})
            .get("errors", [])
        }
    except (json.JSONDecodeError, AttributeError):
        # El cuerpo no vino en el formato que esperamos (por ejemplo, un
        # 403 de Chatwoot, que no es una API de Google): mejor no
        # reintentar algo que no reconocemos que asumir que sí conviene.
        return False
    return bool(razones & RAZONES_DE_CUOTA)


def con_reintentos(llamada: Callable[[], T]) -> T:
    """Corre `llamada` (sin argumentos, típicamente un lambda) reintentando
    en errores transitorios. Devuelve lo que devuelva `llamada`, o levanta
    el último error si se agotan los intentos."""
    espera = ESPERA_INICIAL
    ultimo_error: Exception | None = None

    for intento in range(1, INTENTOS + 1):
        try:
            return llamada()
        except urllib.error.HTTPError as e:
            # HTTPError es una subclase de URLError, por eso va primero:
            # acá sí importa el código de estado, ahí abajo no.
            #
            # e.read() vacía el body una sola vez, y encima HTTPError
            # CACHEA el método (hereda de tempfile._TemporaryFileWrapper,
            # que memoriza `self.read` apuntando al `fp` original la
            # primera vez que se lo pide) — así que no alcanza con
            # reemplazar `e.fp`, el `e.read` viejo lo seguiría ignorando.
            # Se lo pisa directo para que quien reciba el error de acá
            # (calendario.py / chatwoot.py, ambos hacen `e.read()` en su
            # propio except) lo pueda seguir leyendo como si nada.
            cuerpo = e.read()
            e.read = io.BytesIO(cuerpo).read
            if not _es_transitorio(e, cuerpo) or intento == INTENTOS:
                raise
            ultimo_error = e
        except urllib.error.URLError as e:
            if intento == INTENTOS:
                raise
            ultimo_error = e

        time.sleep(espera)
        espera *= 2

    raise ultimo_error  # pragma: no cover — inalcanzable; deja contento al linter

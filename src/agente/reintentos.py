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
"""

from __future__ import annotations

import time
import urllib.error
from typing import Callable, TypeVar

T = TypeVar("T")

INTENTOS = 3
ESPERA_INICIAL = 0.5  # segundos; se duplica en cada reintento (0.5, 1, 2...)


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
            if e.code < 500 or intento == INTENTOS:
                raise
            ultimo_error = e
        except urllib.error.URLError as e:
            if intento == INTENTOS:
                raise
            ultimo_error = e

        time.sleep(espera)
        espera *= 2

    raise ultimo_error  # pragma: no cover — inalcanzable; deja contento al linter

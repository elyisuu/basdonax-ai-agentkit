"""El calendario: turnos de verdad, no solo una nota para que alguien confirme.

Habla con la API de Google Calendar usando una **cuenta de servicio** (un
"usuario robot" de Google), no el login del dueño del negocio. Por eso no
hay ninguna pantalla de "Iniciar sesión con Google" que construir, ni un
token de una persona que renovar cada tanto: el negocio comparte SU
calendario con el email de la cuenta de servicio (Configuración del
calendario → Compartir con personas específicas → permiso "Modificar
eventos") y desde ese momento el agente puede leerlo y escribir en él. El
paso a paso para sacar esa cuenta de servicio está en AGENTS.md.

Por qué no se usa `google-api-python-client` ni `requests`: la API de
Calendar es HTTP + JSON como cualquier otra (mismo criterio que
`canales/chatwoot.py`), así que alcanza con `urllib`. Lo único que hace
falta de las librerías de Google es **firmar** el JWT de la cuenta de
servicio — eso sí necesita `cryptography` (RSA-SHA256), y reescribir una
firma RSA a mano no tiene sentido.

El flujo para hablar con la API, de punta a punta:

    1. Firmar un JWT con la clave privada de la cuenta de servicio.
    2. Cambiar ese JWT por un access_token en el endpoint de OAuth de
       Google (dura una hora; se guarda y se pide uno nuevo recién cuando
       está por vencer).
    3. Pedirle o escribirle a la API de Calendar con ese access_token.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from google.auth import crypt
from google.auth import jwt as jwt_de_google

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/calendar/v3"
ALCANCE = "https://www.googleapis.com/auth/calendar"

# Margen antes de que venza el access_token para pedir uno nuevo. Sin esto,
# un pedido que arranca a los 3599 segundos de vida puede llegarle a la API
# ya vencido.
MARGEN_SEGUNDOS = 60

ESPERA_DE_RED = 20


class ErrorDeCalendario(Exception):
    """Google Calendar (o la autenticación) contestó algo que no esperábamos."""


class Calendario:
    """Un calendario de Google, autenticado como cuenta de servicio."""

    def __init__(
        self, calendario_id: str, credencial_json: str, zona_horaria: str = "UTC"
    ) -> None:
        if not calendario_id or not credencial_json:
            raise ValueError(
                "Faltan datos de Google Calendar. Completá GOOGLE_CALENDAR_ID "
                "y GOOGLE_SERVICE_ACCOUNT_JSON en el .env."
            )

        try:
            info = json.loads(credencial_json)
        except json.JSONDecodeError as e:
            raise ValueError(
                "GOOGLE_SERVICE_ACCOUNT_JSON no es un JSON válido. Tiene que "
                "ser el contenido completo del archivo que descargaste de "
                "Google Cloud, pegado en una sola línea."
            ) from e

        self.calendario_id = calendario_id
        # ZoneInfo tira excepción si el nombre no existe ("Europe/Lisbon" sí,
        # "Lisboa" no) — se deja subir tal cual: mejor un error claro ahora
        # que turnos guardados en el huso horario equivocado.
        self.zona = ZoneInfo(zona_horaria)
        self._info = info
        self._firmante = crypt.RSASigner.from_service_account_info(info)

        # El access_token se guarda acá y se reusa mientras no venza: pedir
        # uno nuevo en cada mensaje sería un pedido de más por cada charla.
        self._token: str | None = None
        self._token_vence: float = 0.0

    # -- Fechas y horas -----------------------------------------------------

    def rango(
        self, fecha: str, hora: str, duracion_minutos: int
    ) -> tuple[datetime, datetime]:
        """El inicio y el fin de un turno, en la zona horaria del negocio.

        `fecha` en AAAA-MM-DD y `hora` en HH:MM (24 horas). Si no vienen en
        ese formato tira `ValueError` — se deja subir tal cual, la
        herramienta que llama a esto es la que lo convierte en texto.
        """
        inicio = datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H:%M")
        inicio = inicio.replace(tzinfo=self.zona)
        return inicio, inicio + timedelta(minutes=duracion_minutos)

    # -- Consultar ------------------------------------------------------------

    def ocupado(self, fecha: str) -> list[tuple[str, str]]:
        """Los horarios ya ocupados en una fecha, como (desde, hasta) en HH:MM."""
        desde = datetime.strptime(fecha, "%Y-%m-%d").replace(tzinfo=self.zona)
        hasta = desde + timedelta(days=1)

        return [
            (self._a_hora_local(b["start"]), self._a_hora_local(b["end"]))
            for b in self._franjas_ocupadas(desde, hasta)
        ]

    def se_superpone(self, inicio: datetime, fin: datetime) -> bool:
        """Si ese rango pisa algo que ya está en el calendario."""
        return bool(self._franjas_ocupadas(inicio, fin))

    def _franjas_ocupadas(self, desde: datetime, hasta: datetime) -> list[dict]:
        respuesta = self._api(
            "POST",
            "freeBusy",
            {
                "timeMin": desde.isoformat(),
                "timeMax": hasta.isoformat(),
                "items": [{"id": self.calendario_id}],
            },
        )
        return respuesta["calendars"][self.calendario_id]["busy"]

    def _a_hora_local(self, iso: str) -> str:
        return datetime.fromisoformat(iso).astimezone(self.zona).strftime("%H:%M")

    # -- Crear -----------------------------------------------------------------

    def crear_evento(
        self, titulo: str, descripcion: str, inicio: datetime, fin: datetime
    ) -> dict:
        """Crea el turno en el calendario. Devuelve el evento creado."""
        return self._api(
            "POST",
            f"calendars/{urllib.parse.quote(self.calendario_id, safe='')}/events",
            {
                "summary": titulo,
                "description": descripcion,
                # El offset va adentro del propio dateTime (gracias a
                # ZoneInfo): no hace falta mandar un campo timeZone aparte.
                "start": {"dateTime": inicio.isoformat()},
                "end": {"dateTime": fin.isoformat()},
            },
        )

    # -- Autenticación y HTTP -----------------------------------------------

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_vence - MARGEN_SEGUNDOS:
            return self._token

        ahora = int(time.time())
        afirmacion = jwt_de_google.encode(
            self._firmante,
            {
                "iss": self._info["client_email"],
                "scope": ALCANCE,
                "aud": TOKEN_URL,
                "iat": ahora,
                "exp": ahora + 3600,
            },
        )

        cuerpo = urllib.parse.urlencode(
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": afirmacion,
            }
        ).encode()

        pedido = urllib.request.Request(TOKEN_URL, data=cuerpo, method="POST")

        try:
            with urllib.request.urlopen(pedido, timeout=ESPERA_DE_RED) as resp:
                datos = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detalle = e.read().decode("utf-8", "replace")[:300]
            raise ErrorDeCalendario(
                f"Google no autenticó la cuenta de servicio: {detalle}"
            ) from None

        self._token = datos["access_token"]
        self._token_vence = time.time() + datos.get("expires_in", 3600)
        return self._token

    def _api(self, metodo: str, camino: str, cuerpo: dict) -> dict:
        """Un pedido a la API de Calendar. Punto único que tocan los tests."""
        pedido = urllib.request.Request(
            f"{API}/{camino}",
            data=json.dumps(cuerpo).encode("utf-8"),
            method=metodo,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._access_token()}",
            },
        )

        try:
            with urllib.request.urlopen(pedido, timeout=ESPERA_DE_RED) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detalle = e.read().decode("utf-8", "replace")[:300]
            raise ErrorDeCalendario(
                f"Google Calendar devolvió {e.code} en {metodo} {camino}: {detalle}"
            ) from None

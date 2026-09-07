"""Pruebas del calendario. No salen a internet ni gastan tokens.

La API de Google Calendar se reemplaza por una de mentira que anota lo que
se le pidió — mismo criterio que test_chatwoot.py con la API de Chatwoot.
Firmar el JWT sí necesita una clave RSA de verdad (Google no acepta
cualquier cosa), así que se genera una descartable en este archivo: no hay
ningún secreto real involucrado, y generarla no toca la red.

    pytest
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa as rsa_crypto

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agente.calendario import Calendario, ErrorDeCalendario  # noqa: E402


def _cuenta_de_servicio_de_prueba() -> str:
    """Un JSON de cuenta de servicio con una clave real pero inventada.

    Firmar el JWT necesita una clave RSA válida — generarla achica el test
    a "sin red, sin secretos de verdad" sin tener que guardar una clave de
    ejemplo en el repo.
    """
    clave = rsa_crypto.generate_private_key(public_exponent=65537, key_size=2048)
    pem = clave.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    return json.dumps(
        {
            "type": "service_account",
            "private_key": pem,
            "private_key_id": "de-prueba",
            "client_email": "agente@mi-proyecto.iam.gserviceaccount.com",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )


# Se genera una sola vez: a los tests no les importa la clave en sí, y
# generar una por test sería pagar el costo de la firma RSA de más.
CREDENCIAL = _cuenta_de_servicio_de_prueba()


class CalendarioFalso(Calendario):
    """El calendario, pero con la API de mentira. Anota todo lo que se pidió."""

    def __init__(self, ocupado_remoto=None, zona_horaria="America/Argentina/Buenos_Aires"):
        super().__init__(
            calendario_id="negocio@group.calendar.google.com",
            credencial_json=CREDENCIAL,
            zona_horaria=zona_horaria,
        )
        self.llamadas: list[dict] = []
        self._ocupado_remoto = ocupado_remoto or []

    def _api(self, metodo, camino, cuerpo):
        self.llamadas.append({"metodo": metodo, "camino": camino, "cuerpo": cuerpo})

        if camino == "freeBusy":
            return {"calendars": {self.calendario_id: {"busy": self._ocupado_remoto}}}
        return {"id": "evento-nuevo", "htmlLink": "https://calendar.google.com/evento"}


# -- Faltan datos --------------------------------------------------------------


def test_sin_datos_avisa_que_faltan():
    with pytest.raises(ValueError, match="GOOGLE_CALENDAR_ID"):
        Calendario(calendario_id="", credencial_json="")


def test_credencial_que_no_es_json_avisa_con_claridad():
    with pytest.raises(ValueError, match="JSON válido"):
        Calendario(calendario_id="negocio@x.com", credencial_json="esto no es json")


def test_zona_horaria_que_no_existe_explota():
    """Mejor un error apenas se arranca que turnos guardados en el huso
    horario equivocado sin que nadie lo note."""
    with pytest.raises(Exception):
        CalendarioFalso(zona_horaria="Marte/Cráter_Gale")


# -- Fechas y horas --------------------------------------------------------------


def test_rango_arma_inicio_y_fin_en_la_zona_horaria():
    cal = CalendarioFalso()

    inicio, fin = cal.rango("2026-09-12", "21:00", 90)

    assert inicio == datetime(2026, 9, 12, 21, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))
    assert fin == datetime(2026, 9, 12, 22, 30, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))


def test_rango_con_formato_invalido_explota():
    cal = CalendarioFalso()

    with pytest.raises(ValueError):
        cal.rango("12 de septiembre", "9 de la noche", 60)


# -- Consultar --------------------------------------------------------------------


def test_ocupado_devuelve_las_franjas_en_hora_local():
    cal = CalendarioFalso(
        ocupado_remoto=[
            {"start": "2026-09-12T21:00:00-03:00", "end": "2026-09-12T22:00:00-03:00"},
        ]
    )

    assert cal.ocupado("2026-09-12") == [("21:00", "22:00")]


def test_ocupado_vacio_si_no_hay_nada_reservado():
    cal = CalendarioFalso(ocupado_remoto=[])
    assert cal.ocupado("2026-09-12") == []


def test_ocupado_consulta_el_dia_entero():
    cal = CalendarioFalso()

    cal.ocupado("2026-09-12")

    pedido = cal.llamadas[0]
    assert pedido["camino"] == "freeBusy"
    assert pedido["cuerpo"]["timeMin"].startswith("2026-09-12T00:00:00")
    assert pedido["cuerpo"]["timeMax"].startswith("2026-09-13T00:00:00")
    assert pedido["cuerpo"]["items"] == [{"id": "negocio@group.calendar.google.com"}]


def test_se_superpone_si_hay_algo_en_el_rango():
    cal = CalendarioFalso(
        ocupado_remoto=[
            {"start": "2026-09-12T21:00:00-03:00", "end": "2026-09-12T22:00:00-03:00"},
        ]
    )
    inicio, fin = cal.rango("2026-09-12", "21:30", 30)

    assert cal.se_superpone(inicio, fin) is True


def test_no_se_superpone_si_el_calendario_esta_libre():
    cal = CalendarioFalso(ocupado_remoto=[])
    inicio, fin = cal.rango("2026-09-12", "21:30", 30)

    assert cal.se_superpone(inicio, fin) is False


# -- Crear ------------------------------------------------------------------------


def test_crear_evento_manda_titulo_descripcion_y_horarios():
    cal = CalendarioFalso()
    inicio, fin = cal.rango("2026-09-12", "21:00", 60)

    cal.crear_evento("Juan (4p)", "Nombre: Juan\nPersonas: 4", inicio, fin)

    pedido = cal.llamadas[0]
    assert pedido["camino"] == "calendars/negocio%40group.calendar.google.com/events"
    assert pedido["cuerpo"]["summary"] == "Juan (4p)"
    assert pedido["cuerpo"]["description"] == "Nombre: Juan\nPersonas: 4"
    assert pedido["cuerpo"]["start"]["dateTime"] == inicio.isoformat()
    assert pedido["cuerpo"]["end"]["dateTime"] == fin.isoformat()


# -- Errores de la API real (sin la _api de mentira) ------------------------------


def test_un_error_http_se_convierte_en_errordecalendario(monkeypatch):
    import urllib.error
    import urllib.request

    cal = Calendario(
        calendario_id="negocio@x.com",
        credencial_json=CREDENCIAL,
    )
    monkeypatch.setattr(cal, "_access_token", lambda: "token-de-prueba")

    def explota(pedido, timeout):
        raise urllib.error.HTTPError(
            "url", 404, "not found", hdrs=None, fp=__import__("io").BytesIO(b'{"error":"no existe"}')
        )

    monkeypatch.setattr(urllib.request, "urlopen", explota)

    with pytest.raises(ErrorDeCalendario, match="404"):
        cal.ocupado("2026-09-12")

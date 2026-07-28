"""Pruebas del agente. No gastan un solo token: usan un modelo falso.

    pip install pytest
    pytest
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, SystemMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agente.agente import Agente  # noqa: E402
from agente.config import RAIZ, Config, ErrorDeConfiguracion  # noqa: E402
from agente.memoria import ram  # noqa: E402
from agente.prompts import leer_prompt  # noqa: E402


def agente_falso(respuestas: list[str], memoria_mensajes: int = 20) -> Agente:
    """Un agente igual al de verdad, pero con un modelo de mentira adentro."""
    config = Config(
        proveedor="claude",
        modelo="modelo-de-prueba",
        api_key="no-hace-falta",
        max_tokens=1024,
        memoria_mensajes=memoria_mensajes,
        prompt_sistema=RAIZ / "prompts/sistema.md",
    )

    a = Agente.__new__(Agente)
    a.config = config
    a.modelo = GenericFakeChatModel(messages=iter(AIMessage(t) for t in respuestas))
    a.checkpointer = ram()  # los tests no tocan el disco
    a.grafo = a._construir_grafo()
    return a


def test_responde():
    a = agente_falso(["Hola"])
    assert a.responder("hola").texto == "Hola"


def test_se_acuerda_de_la_conversacion():
    a = agente_falso(["primera", "segunda"])
    a.responder("uno")
    a.responder("dos")
    # 2 mensajes míos + 2 del agente
    assert len(a.historial()) == 4


def test_cada_conversacion_va_por_su_lado():
    a = agente_falso(["a", "b"])
    a.responder("hola", conversacion="chat-1")
    a.responder("hola", conversacion="chat-2")

    assert len(a.historial("chat-1")) == 2
    assert len(a.historial("chat-2")) == 2


def test_streaming_devuelve_lo_mismo_que_responder():
    a = agente_falso(["Esto llega de a pedacitos"])
    transmision = a.responder_en_vivo("dale")
    pedazos = list(transmision)

    assert "".join(pedazos) == "Esto llega de a pedacitos"
    assert transmision.resumen.texto == "Esto llega de a pedacitos"


def test_dos_conversaciones_a_la_vez_no_se_pisan():
    """El resumen vive en cada transmisión, no en el agente.

    Si viviera en el agente, dos conversaciones respondiendo al mismo tiempo
    se mezclarían los datos. Esto es lo que pasaría en produccion con varias
    personas escribiendo a la vez.
    """
    a = agente_falso(["respuesta para ana", "respuesta para beto"])

    ana = a.responder_en_vivo("hola", conversacion="ana")
    beto = a.responder_en_vivo("hola", conversacion="beto")

    # Se consumen intercalados, como pasaría de verdad
    lista_ana, lista_beto = [], []
    for pedazo in ana:
        lista_ana.append(pedazo)
    for pedazo in beto:
        lista_beto.append(pedazo)

    assert "".join(lista_ana) == "respuesta para ana"
    assert "".join(lista_beto) == "respuesta para beto"
    assert ana.resumen.texto == "respuesta para ana"
    assert beto.resumen.texto == "respuesta para beto"


def test_recorta_la_memoria_vieja():
    a = agente_falso([f"r{i}" for i in range(10)], memoria_mensajes=4)
    for i in range(6):
        a.responder(f"mensaje {i}")

    entrada = a._armar_entrada({"messages": a.historial()})

    assert isinstance(entrada[0], SystemMessage), "el prompt del sistema va primero"
    assert len(entrada) - 1 <= 4, "tendría que haber recortado los más viejos"


def test_el_prompt_sale_del_archivo():
    a = agente_falso(["x"])
    a.config.cache = False  # sin caché el prompt viaja como texto pelado

    entrada = a._armar_entrada({"messages": []})

    assert entrada[0].content == leer_prompt(a.config.prompt_sistema)


def test_con_cache_el_prompt_va_marcado_para_claude():
    a = agente_falso(["x"])
    a.config.cache = True
    a.config.proveedor = "claude"

    bloque = a._armar_entrada({"messages": []})[0].content[0]

    assert bloque["cache_control"] == {"type": "ephemeral"}
    assert bloque["text"] == leer_prompt(a.config.prompt_sistema)


def test_sin_cache_el_prompt_va_pelado():
    a = agente_falso(["x"])
    a.config.cache = False

    assert isinstance(a._armar_entrada({"messages": []})[0].content, str)


def test_avisa_si_falta_la_clave(monkeypatch):
    monkeypatch.setenv("PROVEEDOR", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")

    with pytest.raises(ErrorDeConfiguracion, match="Falta la clave"):
        Config.desde_entorno()


def test_avisa_si_el_proveedor_no_existe():
    with pytest.raises(ErrorDeConfiguracion, match="no existe"):
        Config.desde_entorno("nube-magica")


def test_modo_produccion_sin_dsn_avisa(monkeypatch):
    from agente.memoria import crear_memoria

    config = Config(
        proveedor="claude", modelo="x", api_key="x", max_tokens=100,
        memoria_mensajes=10, prompt_sistema=RAIZ / "prompts/sistema.md",
        modo="produccion", postgres_dsn="",
    )

    with pytest.raises(ValueError, match="POSTGRES_DSN"):
        crear_memoria(config)


def test_modo_test_guarda_en_sqlite(tmp_path):
    from agente.memoria import crear_memoria

    archivo = tmp_path / "prueba.db"
    config = Config(
        proveedor="claude", modelo="x", api_key="x", max_tokens=100,
        memoria_mensajes=10, prompt_sistema=RAIZ / "prompts/sistema.md",
        modo="test", sqlite_ruta=str(archivo),
    )

    crear_memoria(config)
    assert archivo.exists(), "tendría que haber creado el archivo de la base"


def test_modo_invalido_avisa(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "clave-de-prueba")
    monkeypatch.setenv("MODO", "cualquier-cosa")

    with pytest.raises(ErrorDeConfiguracion, match="MODO"):
        Config.desde_entorno("claude")


def test_olvidar_borra_de_verdad():
    """El botón "borrar conversación" tiene que borrar.

    No alcanza con crear un agente nuevo: la conversación vive en el
    checkpointer, así que si no se borra de ahí, el agente nuevo la levanta
    igual y el botón miente.
    """
    a = agente_falso(["hola", "te llamas Facu", "no se como te llamas"])

    a.responder("me llamo Facu")
    assert len(a.historial()) == 2

    a.olvidar()

    assert a.historial() == [], "la conversación tenía que quedar vacía"


def test_la_transmision_se_puede_leer_dos_veces():
    """Consumirla y despues pedir .texto() no tiene que devolver vacío.

    Los pedazos llegan del modelo y no vuelven, así que si alguien recorre la
    transmisión con un for y después llama a .texto(), le tenemos que dar lo
    que ya guardamos — no un vacío silencioso que además pise el resumen.
    """
    a = agente_falso(["hola que tal"])
    t = a.responder_en_vivo("dale")

    primero = "".join(t)
    segundo = t.texto()

    assert primero == "hola que tal"
    assert segundo == "hola que tal", "la segunda lectura no puede venir vacía"
    assert t.resumen.texto == "hola que tal", "el resumen no se tiene que pisar"

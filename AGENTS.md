# AGENTS.md — contexto para agentes de IA

Este archivo lo leen solos los agentes de programación cuando abren el
proyecto: **Codex, Claude Code, Cursor, Devin, Jules** y cualquier otro que
siga la convención `AGENTS.md`. Está para que entiendan el repo sin que se lo
tengas que explicar cada vez.

Si sos una persona: leé el `README.md`, es el que está escrito para vos.

---

## Qué es esto

**AgentKit.** Un agente de IA conversacional que corre en la máquina
del usuario. Sin servidor, sin hosting. Funciona con Claude, OpenAI o Gemini,
intercambiables desde el `.env`.

Construido sobre **LangChain + LangGraph**. La memoria son los *checkpointers*
de LangGraph, indexados por `thread_id`.

Es la base de una serie: primero local (esto), después Telegram, después
WhatsApp. Todo lo que se diseñó acá apunta a que esos dos pasos no obliguen a
reescribir el agente.

**Idioma del código: español.** Nombres de funciones, variables, comentarios,
docstrings y mensajes de error, todo en español rioplatense (voseo: *tenés*,
*podés*, *guardás*). Excepciones: los identificadores que vienen de librerías
(`messages`, `thread_id`, `checkpointer`, `StateGraph`) y los nombres de los
proveedores. **Si escribís código nuevo acá, seguí esa convención.**

---

## Estructura

El árbol de archivos está en el **[README](README.md#qué-hay-adentro)**.
Lo que importa acá es qué hace cada uno:

| Archivo | Qué resuelve |
|---|---|
| `agente.py` | **El agente.** El grafo de LangGraph. Empezá por acá. |
| `modelos.py` | Crea el modelo y le pregunta al proveedor cuáles tiene |
| `memoria.py` | Los checkpointers: `ram` / `sqlite` / `postgres` |
| `prompts.py` | Lee y guarda `prompts/sistema.md` |
| `respuesta.py` | Parte una respuesta larga en varios mensajes |
| `consola.py` | Que la terminal de Windows no rompa con las tildes |
| `config.py` | Lee el `.env`. Única fuente de configuración. |
| `canales/base.py` | La forma de un canal. Telegram y WhatsApp vienen después. |
| `web/` | La plataforma de pruebas (FastAPI + un solo HTML) |

---

## Las cuatro decisiones de diseño

Entender esto evita romper cosas:

**1. El agente recibe texto y devuelve texto.**
No sabe si lo llaman desde la terminal, la web, Telegram o WhatsApp. Esa
frontera es deliberada: es lo que permite agregar canales sin tocarlo.
`Agente.responder(texto, conversacion) -> Respuesta`.

**2. La memoria es un checkpointer intercambiable.**
`ram()` / `sqlite()` / `postgres()` en `memoria.py`. El `MODO` del `.env`
elige. Cambiar dónde se guardan las conversaciones no toca `agente.py`.

**3. El prompt del sistema vive en un archivo, no en el código.**
`prompts/sistema.md`, leído en **cada** mensaje (no una vez al arrancar).
Por eso se puede editar con el agente corriendo.

**4. Toda la configuración sale del `.env`, vía `config.py`.**
Ninguna credencial en el código, ni una. Las claves se leen únicamente en
`config.py`.

---

## Dónde tocar cada cosa

| Querés… | Archivo | Cómo |
|---|---|---|
| Agregar un proveedor nuevo | `modelos.py` | Una rama en `crear_modelo()` + una en `listar_modelos()` |
| Cambiar dónde se guardan las charlas | `.env` (`MODO`) | O una función nueva en `memoria.py` |
| Cambiar la personalidad | `prompts/sistema.md` | Es texto plano |
| **Agregar herramientas** | `agente.py` | `self.modelo.bind_tools([...])` + nodo `ToolNode` + `add_conditional_edges` |
| Agregar un canal (Telegram, WhatsApp) | archivo nuevo | Traducir mensaje entrante → `agente.responder(texto, conversacion=<chat_id>)` |
| Nueva variable de configuración | `config.py` | Campo en `Config` + lectura en `desde_entorno()` + línea en `.env.example` |
| Que se pueda editar desde la web | `config.py` | Agregarla a `AJUSTABLES` + campo en `AjustesEntrantes` (`web/app.py`) + control en la barra de estado |
| Tocar la interfaz | `web/static/index.html` | Un solo archivo, sin build ni npm |

---

## Reglas al escribir código acá

- **Ninguna credencial en el código.** Todas viven en el `.env` y se leen en
  `config.py`. (Sí hay algún `os.getenv()` fuera de ahí, pero solo para rutas
  y nunca para una clave.)
- **Español**, según la convención de arriba.
- **Comentar el *por qué*, no el *qué*.** Este repo es material didáctico: si
  algo se hace de una forma no obvia, explicá la razón.
- **El error del proveedor nunca se esconde.** Si Anthropic, OpenAI o Google
  devuelven un error, tiene que llegar tal cual a la pantalla del usuario.
  Sí se pueden tragar fallas que no son del modelo y no deben voltear la app,
  y hoy hay exactamente tres, todas a propósito y comentadas:
  `listar_modelos()` (sin lista, la app sigue), `consola.preparar()` (si la
  terminal no acepta UTF-8, se sigue igual) y `_mensajes_en_memoria()` (es un
  contador para la pantalla). **No agregues una cuarta sin dejar el motivo
  escrito al lado.**
- **Los tests no gastan tokens.** Usan `GenericFakeChatModel`. Si agregás una
  función que llama a un proveedor, el test va con modelo falso.
- **Sin dependencias nuevas** salvo que resuelvan algo que no se puede hacer
  con lo que ya está.

---

## Cómo se corre

La instalación paso a paso está en el
**[README](README.md#arrancar-en-3-pasos)** — no la repito acá para que no se
desincronicen. Lo que hace falta saber:

```bash
python servidor.py    # la plataforma de pruebas, en http://localhost:8000
python chat.py        # lo mismo pero por terminal
```

Para los tests hace falta pytest, que **no** está en `requirements.txt`:

```bash
pip install -r requirements-dev.txt
pytest
```

No hay `pyproject.toml`: el paquete no se instala. Cada punto de entrada y
cada test hace `sys.path.insert(0, "src")`, así que `pytest` se corre desde la
raíz del repo y no desde otro lado.

---

## Detalles que ya mordieron

Cosas que parecen bugs y no lo son, o que cuestan de encontrar:

- **`stream_usage=True` en `ChatOpenAI`**: sin eso, OpenAI no informa tokens
  cuando la respuesta llega en streaming. Quedan en 0.
- **Los chunks se suman** (`chunk_a + chunk_b`) en `responder_en_vivo()`. No es
  cosmético: varios proveedores mandan el conteo de tokens recién en el
  último chunk, y sumando es la única forma de tenerlo completo.
- **El caché de Claude es un bloque, no un string.** El `SystemMessage` pasa a
  ser `[{"type": "text", "text": ..., "cache_control": {...}}]`. Cualquier
  código que asuma que `content` es `str` se rompe. Ver `Agente._sistema()`.
- **El caché no se activa con prompts cortos** (~1.000 tokens mínimo). No es
  un bug: es cómo funciona. Con un prompt corto simplemente no cachea.
- **`check_same_thread=False`** en la conexión de SQLite: el servidor web
  atiende en varios hilos y sin eso rompe.
- **El pool de Postgres se deja abierto a propósito** en `memoria.postgres()`.
  Si se cierra el context manager, el checkpointer muere en el primer mensaje.
- **`trim_messages` cuenta mensajes, no tokens**, porque le pasamos
  `token_counter=len`. `MEMORIA_MENSAJES=20` son 20 mensajes, no 20 tokens.
- **La lista de modelos de OpenAI trae todo junto** (imágenes, audio,
  embeddings) y hay que filtrarla; la de Anthropic ya viene limpia y ordenada.
- **`max_salida` solo lo informan Anthropic y Google.** OpenAI no lo expone en
  su listado, así que queda en `None` y el tope no se ajusta para esos modelos.
  **Consecuencia real:** si venís de un modelo de Claude con tope alto y pasás
  a OpenAI, el `MAX_TOKENS` guardado queda pegado del anterior. No rompe (OpenAI
  no valida el tope como Anthropic), pero el número que ves en la barra no es
  el de ese modelo.
- **`guardar_ajustes()` reescribe el `.env` línea por línea**, no lo regenera:
  los comentarios y el orden se conservan. También actualiza `os.environ` para
  que el proceso vivo vea los valores nuevos sin reiniciar.
- **`AJUSTABLES` es una lista corta a propósito.** Fuera quedan las claves de
  API (no se editan desde el navegador), `MODO` (la plataforma es para probar:
  siempre test) y `CACHE` (siempre activado). Lo que no está en esa lista se
  ignora aunque el navegador lo mande. **No agregues nada ahí sin que te lo
  pidan.**
- **`MAX_TOKENS` lo manda la plataforma, no el usuario.** Es el tope de salida
  del modelo elegido; se acomoda solo al cambiar de modelo. El único campo que
  toca una persona en la barra es `MEMORIA_MENSAJES`.

---

## Lo que NO tiene (todavía)

No lo agregues salvo que te lo pidan: son los próximos videos de la serie.

- Herramientas (el agente solo conversa)
- Canales de mensajería (Telegram, WhatsApp)
- RAG / base de conocimiento
- Autenticación en la plataforma de pruebas (es local, un solo usuario)
- Varias conversaciones en paralelo en la web (usa un `thread_id` fijo)

---

## Cómo se agrega una herramienta

Va en `agente.py`, en `_construir_grafo()`. El grafo pasa de un nodo suelto a
un ciclo: modelo → herramientas → modelo, hasta que el modelo deja de pedirlas.

```python
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode, tools_condition

@tool
def clima(ciudad: str) -> str:
    """Dice el clima de una ciudad."""     # ← el docstring es lo que lee el modelo
    return f"En {ciudad} hay 22 grados y está despejado."

HERRAMIENTAS = [clima]

# En _construir_grafo(), el modelo tiene que saber que existen:
modelo = self.modelo.bind_tools(HERRAMIENTAS)

grafo.add_node("modelo", nodo_modelo)
grafo.add_node("herramientas", ToolNode(HERRAMIENTAS))
grafo.add_edge(START, "modelo")
grafo.add_conditional_edges("modelo", tools_condition)  # ¿pidió una herramienta?
grafo.add_edge("herramientas", "modelo")                # y vuelve al modelo
```

> ⚠️ **La trampa que te vas a comer.** `_armar_entrada()` recorta la
> conversación con `trim_messages(..., start_on="human")`. Con herramientas,
> ese recorte puede dejar un `AIMessage` con `tool_calls` **sin** su
> `ToolMessage` (o al revés), y ahí el proveedor devuelve un 400 que no dice
> nada útil. Cuando agregues herramientas, el recorte tiene que cortar en un
> par completo — no en cualquier mensaje.

---

## Cómo se agrega un canal

`Canal` (en `canales/base.py`) define la **salida**: cómo le mandás mensajes a
una persona. La **entrada** la resuelve cada canal como le convenga, porque
cambia mucho entre uno y otro:

| | Cómo llegan los mensajes | Necesita URL pública |
|---|---|---|
| **Telegram** | *Polling*: tu programa pregunta "¿hay mensajes?" cada tanto | No |
| **WhatsApp (Meta)** | *Webhook*: Meta le pega a una URL tuya | Sí |

La forma de los dos, igual:

```python
# 1. Llega algo del canal y lo traducís
entrante = MensajeEntrante(texto=..., conversacion=<id del chat>, identificador=<id del mensaje>)

# 2. Le preguntás al canal si hay que contestar
#    (persona atendiendo, bot apagado, mensaje repetido, mensaje propio)
if not canal.deberia_responder(entrante):
    return

# 3. El agente. Esta línea es la misma en todos los canales.
mensajes = agente.responder_partido(entrante.texto, conversacion=entrante.conversacion)

# 4. La respuesta sale por donde entró
canal.enviar(entrante.conversacion, mensajes)
```

**El webhook de WhatsApp se monta en su propia app FastAPI**, no en la de la
plataforma de pruebas: son dos cosas distintas y la de pruebas no sale de
`localhost`.

**`conversacion` es el `thread_id` de LangGraph.** Es lo único que no se puede
equivocar: si dos personas comparten el mismo valor, comparten la conversación.

---

## Hacia dónde va (para no diseñar en contra)

Esto todavía **no está implementado** y no hay que implementarlo sin que lo
pidan. Está acá para que cualquier cosa que se agregue al núcleo no lo haga
imposible después.

**Video 2 — Telegram.** `canales/telegram.py` implementa `Canal`.
`conversacion` = el `chat_id`. `MODO=produccion` con Postgres.

**Video 3 — WhatsApp.** `canales/whatsapp.py`, y ahí entra todo lo que
separa un bot de demo de uno que atiende clientes:

| Pieza | Dónde va | Por qué |
|---|---|---|
| Verificar la firma de Meta (HMAC-SHA256 con el App Secret) | `canales/whatsapp.py` | Sin esto cualquiera que sepa la URL le escribe al agente. **No es opcional.** |
| Responder 200 en menos de 5s y procesar aparte | `canales/whatsapp.py` | Meta reintenta y el agente contesta de más |
| Descartar el mensaje repetido por id | `Canal.deberia_responder()` | Meta reenvía ante la duda |
| Juntar la ráfaga de mensajes (Redis) | `buffer.py` (nuevo) | La gente manda 3 mensajes cortos seguidos; hay que contestar una vez |
| Partir la respuesta en varios globos | `respuesta.partir_respuesta()` | **Ya está hecho** |
| Traspaso a una persona | `Canal.deberia_responder()` | Etiqueta en Chatwoot, o un flag propio. Es *el* diferencial |
| Apagar el bot por contacto | `Canal.deberia_responder()` | |
| Chatwoot **opcional** | `canales/chatwoot.py` | Si hay `CHATWOOT_URL` se usa; si no, el canal habla directo |
| Ventana de 24h y plantillas | `canales/whatsapp.py` | Fuera de plazo, Meta rechaza el envío |

**Decisiones ya tomadas** (no volver a discutirlas):

- **Un solo repo.** Cada canal es un archivo nuevo; el núcleo no se toca.
- **Chatwoot es opcional**, no obligatorio.
- **Redis** para juntar los mensajes, no Postgres.
- **`MODO=test` responde y listo.** Todo lo de arriba corre solo en
  `MODO=produccion`.

**Ya preparado en el núcleo para que eso entre sin reescribir nada:**

- `canales/base.py` — la forma de un canal y el gancho `deberia_responder()`
- `respuesta.partir_respuesta()` — la respuesta en varios mensajes
- `Agente.responder_partido()` — lo mismo, listo para usar
- `Transmision` — el resumen vive en cada respuesta, **no** en el agente, así
  varias conversaciones a la vez no se pisan los datos

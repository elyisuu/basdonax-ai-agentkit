# AGENTS.md — contexto para agentes de IA

Este archivo lo leen solos los agentes de programación cuando abren el
proyecto: **Codex, Claude Code, Cursor, Devin, Jules** y cualquier otro que
siga la convención `AGENTS.md`. Está para que entiendan el repo sin que se lo
tengas que explicar cada vez.

Si sos una persona: leé el `README.md`, es el que está escrito para vos.

Si estás sumando un cliente nuevo (no tocando código): el checklist es
**[ALTA_DE_CLIENTE.md](ALTA_DE_CLIENTE.md)**, no este archivo.

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
| `herramientas.py` | Lo que el agente puede hacer además de conversar: el clima y las reservas/turnos. |
| `calendario.py` | Google Calendar (cuenta de servicio), para que `anotar_reserva` confirme turnos de verdad |
| `horario.py` | El horario de atención (`HORARIO_DESDE/HASTA`, `DIAS_CERRADOS`), opcional |
| `aprobacion.py` | Firma y valida los links de aprobar/rechazar una reserva pendiente |
| `reintentos.py` | Backoff para las llamadas HTTP a Chatwoot y Google Calendar |
| `alertas.py` | Avisa por Telegram (a un chat propio) cuando algo se rompe en producción |
| `recordatorios.py` | Programa aparte (raíz del repo): recordatorios de turnos por WhatsApp, para dejar programado (Scheduled Task) |
| `visitas.py` | Registro de turnos confirmados (nuevos vs. recurrentes), para las estadísticas del negocio — corre en código, no es una herramienta del modelo |
| `modelos.py` | Crea el modelo y le pregunta al proveedor cuáles tiene |
| `memoria.py` | Los checkpointers: `ram` / `sqlite` / `postgres` |
| `prompts.py` | Lee y guarda `prompts/sistema.md` |
| `respuesta.py` | Parte una respuesta larga en varios mensajes |
| `consola.py` | Que la terminal de Windows no rompa con las tildes |
| `config.py` | Lee el `.env`. Única fuente de configuración. |
| `canales/base.py` | La forma de un canal |
| `canales/telegram.py` | **El bot de Telegram.** Polling, corre en tu máquina. |
| `canales/chatwoot.py` | **El canal de WhatsApp**, con Chatwoot en el medio |
| `canales/buffer.py` | Junta la ráfaga de mensajes cortos y contesta una vez |
| `web/webhook.py` | **El servidor que atiende WhatsApp.** Es lo que corre en producción. |
| `../webhook_chatwoot.py` | El punto de entrada del webhook |
| `../Dockerfile` | Empaqueta el **webhook** (`webhook_chatwoot.py`); el bot de Telegram queda adentro por si lo querés correr |
| `web/app.py` | La plataforma de pruebas (FastAPI + un solo HTML) — **no es** el webhook |

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
| **Agregar herramientas** | `herramientas.py` | Una función con `@tool` + sumarla a `HERRAMIENTAS`. El grafo ya está armado. |
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
python servidor.py         # la plataforma de pruebas, en http://localhost:8000
python chat.py             # lo mismo pero por terminal
python bot_telegram.py     # el agente atendiendo en Telegram (polling, local)
python webhook_chatwoot.py # el agente atendiendo WhatsApp (necesita servidor)
```

El último es el único que **no** sirve en tu máquina: es un webhook, así que
Chatwoot tiene que poder entrar. Levantalo local solo para confirmar que
arranca (`GET /salud`); para probarlo de verdad tiene que estar desplegado.

El bot se llama `bot_telegram.py` y no `telegram.py` a propósito: un módulo
llamado `telegram` en la raíz taparía la librería del mismo nombre si algún
día se instala.

Para `MODO=produccion` hacen falta dos paquetes que **no** están en el
`requirements.txt`, y en Windows el segundo no es opcional:

```bash
pip install "langgraph-checkpoint-postgres>=3.1,<4" "psycopg[binary]"
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
- **`use_responses_api=True` en `ChatOpenAI`, y no se puede sacar.** Por el
  endpoint viejo (`/v1/chat/completions`), pedirle herramientas a un modelo que
  razona —toda la familia gpt-5— devuelve un 400: *"Function tools with
  reasoning_effort are not supported... use /v1/responses"*. La otra salida que
  ofrece el propio error es apagarle el razonamiento al modelo, que es pagar
  por uno y usar otro. Con modelos viejos (gpt-4.1) el problema no aparece, así
  que si lo sacás no lo vas a ver hasta probar con un gpt-5.
- **Los resultados de las herramientas también salen por el stream.**
  `responder_en_vivo()` filtra los `ToolMessage` a propósito: sin ese filtro, la
  persona ve el texto crudo de la consulta al clima en pantalla y después la
  respuesta de verdad.
- **Con herramientas el modelo habla dos veces**, así que la suma de chunks de
  `responder_en_vivo()` termina juntando el gasto de las dos llamadas. Es lo que
  querés: es lo que costó la respuesta. Ojo que `responder()` (sin streaming)
  informa solo los tokens del último mensaje, porque mira `messages[-1]`.
- **`GenericFakeChatModel` no implementa `bind_tools()`** y el grafo lo llama al
  construirse. Por eso los tests usan `ModeloFalso`, que lo agrega. Si armás un
  modelo falso nuevo, acordate o no arranca ni un test.
- **Los chunks se suman** (`chunk_a + chunk_b`) en `responder_en_vivo()`. No es
  cosmético: varios proveedores mandan el conteo de tokens recién en el
  último chunk, y sumando es la única forma de tenerlo completo.
- **El caché de Claude es un bloque, no un string.** El `SystemMessage` pasa a
  ser `[{"type": "text", "text": ..., "cache_control": {...}}]`. Cualquier
  código que asuma que `content` es `str` se rompe. Ver `Agente._sistema()`.
- **El caché no se activa con prompts cortos** (~1.000 tokens mínimo). No es
  un bug: es cómo funciona. Con un prompt corto simplemente no cachea.
- **Cambiar `HERRAMIENTAS` puede romper para siempre una conversación vieja
  de Claude.** Los modelos Claude 5 piensan (thinking adaptativo) por
  default, y ese pensamiento queda firmado y atado a la lista de
  herramientas del momento en que se generó. El día que agregás o sacás una
  herramienta, la próxima vez que se relee esa conversación el proveedor
  devuelve un 400 ("Invalid signature... The tools list differs from the
  one this block was created with") y la persona ve "Se me rompió algo"
  para siempre, porque el bloque inválido queda guardado en la memoria y se
  reenvía en cada mensaje nuevo. `crear_modelo()` ya manda
  `thinking.block_binding.prefix_mismatch_behavior="drop_block"` (con el
  beta que pide el propio error) para que Anthropic tire el bloque viejo en
  vez de romper el pedido entero. Si en algún momento se cambia de modelo a
  uno que no soporte `thinking: adaptive` (pre-4.7), va a hacer falta sacar
  o condicionar este bloque.
- **`check_same_thread=False`** en la conexión de SQLite: el servidor web
  atiende en varios hilos y sin eso rompe.
- **`memoria.postgres()` usa un `ConnectionPool` (psycopg_pool), no una
  conexión única.** Nos pasó en producción: con una sola conexión abierta al
  arrancar el proceso, si Postgres la cortaba sola (un blip de red, un
  timeout de conexión idle — Postgres seguía sano, solo se caía el cable) el
  checkpointer quedaba muerto hasta que alguien lo notaba a mano y
  reiniciaba. Con un pool, cada operación pide una conexión (la librería se
  encarga, ver `_internal.get_connection`) y el pool reabre solo las que se
  cortaron. De paso, esto también sacó el truco a mano que hacía falta antes
  para que el recolector de basura no cerrara la conexión (`PostgresSaver`
  ya guarda el pool como `self.conn`, y con eso alcanza).
- **`langgraph-checkpoint-postgres` tiene que ser 3.x.** La 2.x arrastra un
  `langgraph-checkpoint` viejo (2.1) que se pelea con `langgraph` 1.2 y con el
  checkpointer de SQLite. `pip install` lo deja instalar igual y lo avisa como
  un warning que es fácil pasar por alto; el entorno queda roto.
- **`psycopg` va con `[binary]` en Windows.** Sin eso el import falla con
  *"no pq wrapper available"* porque no encuentra la libpq del sistema. El
  paquete está instalado y el error igual aparece.
- **El offset de Telegram se adelanta aunque el mensaje no sirva**
  (`Telegram.escuchar()`). Telegram reenvía todo lo que no le confirmaste, así
  que si alguien manda una foto y no avanzamos, esa foto vuelve para siempre y
  el bot se queda trabado ahí sin atender a nadie más.
- **El `chat_id` va como texto** al usarse de `thread_id`. Un `555` y un
  `"555"` son dos conversaciones distintas para LangGraph.
- **El bot de Telegram no expone puerto y eso confunde a los PaaS.** Al
  desplegarlo, el panel le asigna un dominio solo y después lo marca como
  *unhealthy* porque nadie contesta ahí. No está roto: con polling nadie
  entra al bot, sale él. Hay que borrarle el dominio y dejar el health check
  apagado. **Ojo que con el webhook de WhatsApp es al revés**: ese sí escucha
  en el 8000, sí necesita dominio y sí tiene que tener el health check
  prendido apuntando a `/salud`. Son dos formas opuestas de desplegar el
  mismo repo, y el Dockerfile hoy trae la segunda.
- **Dos instancias del bot se roban los mensajes.** Telegram le entrega cada
  mensaje a quien lo pide primero, así que si corren el servidor y la máquina
  local a la vez, las respuestas salen la mitad de cada lado. Es la falla más
  confusa de todas, porque *parece* que anda a veces sí y a veces no.
- **En un contenedor, `MODO=test` pierde las conversaciones en cada deploy**:
  el archivo de SQLite vive en el disco del contenedor y ese disco se
  descarta. En un servidor va Postgres.
- **`MEMORIA_MENSAJES=20` son 20 mensajes, no 20 tokens.** Acá había un
  `trim_messages(token_counter=len)`; ahora es `_recortar()`, que corta por
  turnos completos (ver la sección de herramientas). La unidad no cambió: se
  siguen contando mensajes. Lo que cambió es que el corte cae siempre en el
  borde de un turno, así que el total puede quedar unos mensajes abajo del tope
  antes que partir una vuelta de herramienta al medio.
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

- Más herramientas (hay una sola: el clima)
- RAG / base de conocimiento
- Autenticación en la plataforma de pruebas (es local, un solo usuario)
- Varias conversaciones en paralelo en la web (usa un `thread_id` fijo)

---

## Cómo se agrega una herramienta

**El grafo ya es un ciclo** (modelo → herramientas → modelo, hasta que el
modelo deja de pedirlas), así que agregar una es una sola cosa: escribir la
función en `herramientas.py` y sumarla a `HERRAMIENTAS`. `agente.py` no se
toca.

```python
@tool
def clima(lugar: str) -> str:
    """Dice el clima que hace ahora mismo en una ciudad."""  # ← esto lee el modelo
    ...

HERRAMIENTAS = [clima]   # ← la única lista que mira el grafo
```

Tres cosas que importan:

- **El docstring es el prompt.** Es lo único que el modelo lee para decidir si
  la herramienta le sirve y qué mandarle. Escribilo pensando en eso, no en un
  programador que lee el código.
- **Una herramienta no levanta excepciones: devuelve el problema como texto.**
  Si explota, LangGraph corta la respuesta entera y la persona ve un error
  crudo. Devolviéndolo, el modelo lo lee y lo explica. Está comentado en
  `clima()`.
- **Sin claves nuevas.** `clima` usa Open-Meteo justamente porque no pide
  registro ni tarjeta: arrancar el repo no tiene que depender de sacar una
  credencial más.

> ✅ **La trampa que estaba acá ya está resuelta**, pero conviene entenderla
> antes de tocar `_armar_entrada()`. Una vuelta de herramienta son tres
> mensajes atados (el modelo la pide, la herramienta contesta, el modelo
> responde) y los proveedores los exigen juntos. El `trim_messages()` que
> había recortaba por mensaje suelto, así que tarde o temprano el corte caía
> en el medio y dejaba un `AIMessage` con `tool_calls` **sin** su
> `ToolMessage` → 400 del proveedor, sin explicación, y recién cuando la
> conversación se hacía larga. Ahora `_recortar()` corta por **turnos**
> completos y nunca los parte. `MEMORIA_MENSAJES` sigue contando mensajes.
> Los tests que lo cuidan son `test_el_recorte_no_parte_una_vuelta_de_herramienta`
> (probado con nueve topes distintos) y `test_el_turno_de_ahora_entra_entero_aunque_no_quepa`.

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

## Cómo se conecta Google Calendar (turnos de verdad)

`anotar_reserva` (`herramientas.py`) puede confirmar un turno de una,
chequeando disponibilidad real, en vez de solo dejarlo anotado para que
alguien lo confirme a mano. Para eso habla con la API de Google Calendar
(`calendario.py`) usando una **cuenta de servicio** — no el login del dueño
del negocio. No hay ninguna pantalla de "Iniciar sesión con Google" que
programar: el negocio comparte su calendario con un email, como quien le da
acceso a un empleado más.

**Setup, una sola vez** (sirve para todos los clientes que sumes después):

1. [console.cloud.google.com](https://console.cloud.google.com) → crear un
   proyecto nuevo (o usar uno que ya tengas).
2. APIs & Services → Library → buscar "Google Calendar API" → Enable.
3. IAM & Admin → Service Accounts → Create Service Account. No hace falta
   darle ningún rol a nivel del proyecto: los permisos van a venir de que
   el negocio comparta SU calendario con esta cuenta, no de IAM.
4. Entrá a la cuenta de servicio recién creada → pestaña "Keys" → Add Key →
   Create new key → JSON. Se descarga un archivo — es la única vez que
   Google te lo muestra.
5. Copiá el `client_email` de ese JSON (algo como
   `agente@tu-proyecto.iam.gserviceaccount.com`): es lo que cada cliente
   tiene que agregar a su calendario.

**Setup por cliente** (esto sí se repite con cada uno):

1. El cliente entra a [calendar.google.com](https://calendar.google.com),
   crea un calendario (o usa uno que ya tenga) para los turnos.
2. Configuración de ese calendario → "Compartir con personas específicas"
   → agregar el email de la cuenta de servicio → permiso **"Modificar
   eventos"** (sin esto, `anotar_reserva` puede leer pero no crear turnos).
3. En esa misma pantalla, "Integrar calendario" tiene el **ID del
   calendario** — para uno creado a propósito es algo como
   `xxxxxxxx@group.calendar.google.com`.
4. En el `.env` de esa instancia: `GOOGLE_SERVICE_ACCOUNT_JSON` (el
   contenido completo del archivo del paso 4 de arriba, pegado en una sola
   línea) y `GOOGLE_CALENDAR_ID` (el de este paso). También `ZONA_HORARIA`
   con el huso del negocio (`Europe/Lisbon`, no el tuyo si vivís en otro
   país) — sin esto los turnos se guardan en el huso equivocado.

**Por qué no hace falta OAuth ni una pantalla de consentimiento**: eso es
lo que se usa cuando la app necesita actuar en nombre de una PERSONA
distinta por cada login (y hay que sostener tokens que vencen, refrescarlos,
etc.). Acá alcanza con que el negocio comparta un calendario, que es una
operación de dos clics y no vence nunca. Si en algún momento se vende esto
a muchas empresas y no querés ser vos el que hace este paso a paso con cada
una, ahí sí conviene migrar a OAuth con una pantalla de "Conectar con
Google" — pero es un proyecto aparte, no algo para hacer de entrada.

**Detalles que no son obvios acá:**

- **El JWT de la cuenta de servicio se firma con `google-auth`, no con
  `google-api-python-client`.** Lo único que hace falta de Google es firmar
  (RSA-SHA256, no viene en la biblioteca estándar); el resto —pedir el
  access_token, consultar disponibilidad, crear el evento— son pedidos
  HTTP con `urllib`, mismo criterio que `canales/chatwoot.py`.
- **El modelo no sabe qué día es "hoy" por su cuenta.** `Agente._sistema()`
  le agrega la fecha y hora actuales (en `ZONA_HORARIA`) al final del
  prompt en cada mensaje — sin esto, "el sábado" o "mañana" quedarían
  adivinados. Tiene un costo chico: el caché de Claude falla una vez por
  día, cuando cambia la fecha.
- **`anotar_reserva` sirve con calendario, con Chatwoot, con los dos, o con
  ninguno.** Con calendario, confirma de una. Sin calendario pero con
  Chatwoot, deja una nota pendiente (Nivel 1). Con los dos, hace las dos
  cosas: el calendario es la fuente de la verdad y Chatwoot es solo para
  que el equipo lo vea en la bandeja — por eso, si el calendario ya
  confirmó, un fallo al avisar en Chatwoot no tira abajo el turno. Sin
  ninguno de los dos, avisa que no puede tomar la reserva en ese canal.

## Varios profesionales (una agenda por persona)

Un negocio con más de un profesional atendiendo (varios fisios, por
ejemplo) necesita una agenda de Google Calendar por persona, no una
compartida — si no, `anotar_reserva` no sabría en qué agenda mirar
disponibilidad real ni dónde crear el evento.

**Configuración, en el `.env`:**

```
PROFESIONALES="Dra. García:abc@group.calendar.google.com,Dr. Pérez:xyz@group.calendar.google.com"
```

Nombre y `calendar_id` separados por `:`, cada profesional separado por
`,`. Vacío (el default) = modo de un solo profesional, con
`GOOGLE_CALENDAR_ID` como siempre — **cero cambio de comportamiento** para
los clientes que ya tienen esto configurado así.

**Por qué en el `.env` y no en una tabla de Postgres:** para arrancar, el
número de profesionales de un negocio cambia poco (se decide una vez, por
teléfono con el dueño) y no hace falta que el propio negocio lo edite
solo. Si en algún momento el dueño necesita agregar o sacar un profesional
sin pedirte que le toques el `.env`, ahí sí conviene una tabla y una
pantalla para editarla — pero eso es un proyecto aparte.

**Qué hace cada pieza:**

- `config._profesionales_de(texto)` parsea el `.env` a un diccionario
  `{nombre: calendar_id}`. Una entrada sin `:` se ignora sin tirar abajo
  el arranque completo (un typo en un profesional no puede dejar sin
  servicio a los demás).
- `Agente._sistema()` le agrega al prompt, solo cuando `profesionales` no
  está vacío, la lista de nombres disponibles — así el modelo sabe a
  quién puede ofrecer u ofrecerle a elegir. No está a mano en
  `prompts/sistema.md` a propósito: si viviera ahí, el negocio y el
  prompt podrían desincronizarse (agregás un profesional al `.env` y te
  olvidás de tocar el prompt).
- `herramientas._error_profesional()` es el chequeo que usan
  `anotar_reserva` y `franjas_ocupadas`: si hay más de un profesional
  configurado y el modelo no mandó `profesional` (o mandó uno que no
  existe), devuelve un mensaje pidiendo que se aclare — no revienta ni
  adivina con cuál agenda trabajar.
- `herramientas._calendario_de(config, profesional)` resuelve cuál
  `Calendario` usar. En modo de un solo profesional delega en
  `_calendario_del_config(config)`, la función que ya existía — así todos
  los tests y el comportamiento de siempre no se tocan. En modo de varios,
  busca el `calendar_id` del nombre pedido y arma un `Calendario` para esa
  agenda puntual.

Las cuatro fases del plan ya están completas:

- **Fase 1** — `anotar_reserva` y `franjas_ocupadas` reciben `profesional`
  y usan `_error_profesional()` + `_calendario_de()` (arriba).
- **Fase 2** — `cancelar_mi_reserva` y `reprogramar_mi_reserva` NO reciben
  `profesional`: la persona no siempre se acuerda con quién había
  quedado, así que en vez de preguntarle, `herramientas._calendarios_de()`
  arma la lista de TODAS las agendas y `herramientas._buscar_mi_turno()`
  busca en todas el turno de esta conversación (mismo criterio de
  propiedad que `_chequear_propietario`: un match propio gana, uno sin
  dueño registrado es la siguiente opción, y solo si no hay ninguno de los
  dos se usa un turno ajeno para el mensaje de "no es tuyo" — así un
  profesional con el horario libre y otro con el turno de otra persona no
  bloquea al que sí busca el suyo).
- **Fase 3** — `recordatorios.py` tiene su propia `_calendarios(config)`
  (mismo criterio que la de herramientas.py, pero sin pasar por
  `RunnableConfig`: este programa no corre dentro del grafo) y barre todas
  las agendas, guardando `(calendario, evento)` de a pares para que
  `marcar_recordado()` vaya siempre a la agenda correcta.
- **Fase 4** — los links de `/reservas/{accion}` (Nivel 1.5) llevan un
  query param `profesional` (vacío con un solo profesional) que
  `herramientas._aviso_de_aprobacion()` completa al armarlos, y la firma
  HMAC de `aprobacion.firmar()`/`aprobacion.valido()` lo incluye — nadie
  puede cambiar el profesional en la URL de un link ya emitido sin
  invalidar el token. `web/webhook.py` resuelve la agenda de cada pedido
  puntual con `_calendario_para_aprobacion()` (no con el `Calendario`
  legacy armado una sola vez al arrancar la app, que solo sirve para el
  modo de un profesional).

No hay ninguna fase pendiente de este plan — lo próximo que toque acá es
lo que surja de usarlo con un cliente real de varios profesionales.

## Reserva con aprobación manual (Nivel 1.5)

Algunos negocios no quieren que el agente confirme solo, ni que la reserva
quede solo anotada esperando que alguien la revise en Chatwoot sin chequear
disponibilidad real. El punto medio: `RESERVA_REQUIERE_APROBACION=true` en
el `.env`, con calendario Y Chatwoot conectados.

Qué cambia en `anotar_reserva` (`herramientas.py`):

1. Chequea disponibilidad real, igual que siempre.
2. Crea el evento en el calendario con estado **"tentative"** en vez de
   "confirmed" (`Calendario.crear_evento(..., estado=...)`). Un evento
   "tentative" sigue contando como ocupado para `freeBusy` — nadie más
   puede reservar ese horario mientras el negocio decide.
3. La nota que le llega a Chatwoot queda con la etiqueta
   `reserva-pendiente-aprobacion` (distinta de `reserva-nueva`, para poder
   filtrar en la bandeja "qué me falta aprobar") y, si están puestos
   `URL_PUBLICA` y `RESERVA_SECRETO`, con dos links de un clic: uno para
   aprobar, uno para rechazar.

Esos links los abre una persona del negocio desde el celular, sin login
(`GET /reservas/{aprobar|rechazar}/{conversacion}/{evento_id}?token=...`,
en `web/webhook.py`). La seguridad es el `token` de la URL — mismo criterio
que `CHATWOOT_WEBHOOK_TOKEN` en la URL del webhook, no una cookie ni un
usuario y contraseña — y lo arma y lo valida `aprobacion.py` con HMAC:
firma la `(conversación, evento_id)`, así que un link sirve solo para ESA
reserva puntual. No hay tabla ni sesión que guardar en ningún lado.

Al abrir el link:

- **Aprobar** → `Calendario.aprobar_evento()` pasa el evento a "confirmed",
  y se le avisa a la persona por WhatsApp que el turno quedó confirmado.
- **Rechazar** → `Calendario.cancelar_evento()` borra el evento (libera el
  horario para otra persona), y se le avisa que ese horario no se pudo.

Sin `URL_PUBLICA`/`RESERVA_SECRETO` puestos, este modo igual reserva el
horario en el calendario (nadie te lo dobla-reserva), pero sin links: hay
que aprobar o rechazar directo en Google Calendar a mano.

## Horario de atención

`HORARIO_DESDE`/`HORARIO_HASTA` (un turno corrido), `HORARIO_FRANJAS`
(horario partido, con un corte al medio) y `DIAS_CERRADOS` en el `.env`
(`horario.py`). Antes de esto, el modelo solo sabía qué horario atendía el
negocio por lo que decía su propio prompt (`prompts/sistema.md`) — nada se
lo hacía cumplir de verdad. `anotar_reserva` ahora valida `(fecha, hora)`
contra esto ANTES de tocar Chatwoot o el calendario. Todo es opcional y
vacío por defecto: sin nada configurado, no hay ninguna restricción —
igual que antes de que existiera `horario.py`.

`HORARIO_FRANJAS` es para cuando el negocio cierra al mediodía y vuelve a
abrir más tarde (`09:00-15:00,18:00-23:00`): si tiene algo puesto, manda
por sobre `HORARIO_DESDE`/`HORARIO_HASTA` — alcanza con que la hora caiga
en CUALQUIERA de las franjas. Sin `HORARIO_FRANJAS`, se usa el rango único
de siempre (un solo turno corrido).

**`franjas_ocupadas` también sabe del horario**, no solo `anotar_reserva`.
Sin esto, el modelo podía consultar disponibilidad, ver que el calendario
tenía libre un horario que en realidad caía en el corte de un horario
partido, ofrecérselo a la persona, pedirle nombre y cantidad de personas,
y recién ahí (al llamar a `anotar_reserva`) enterarse de que no se podía —
una vuelta de más innecesaria. Ahora `franjas_ocupadas` le suma al modelo
una línea con `horario.descripcion()` ("Atiende de 09:00 a 15:00 y 18:00 a
23:00.") y, si el día completo está cerrado (`DIAS_CERRADOS`), lo avisa de
una sin ni siquiera consultar el calendario.

## Cancelar y reprogramar mi propia reserva

`cancelar_mi_reserva` y `reprogramar_mi_reserva` (`herramientas.py`) — para
cuando la misma persona que hizo la reserva escribe de vuelta a cambiarla.
Las dos necesitan Google Calendar conectado (buscan el turno ahí, con
`Calendario.evento_en()`) y funcionan por horario, no por id: no hace
falta guardar en ningún lado qué evento le corresponde a qué conversación,
alcanza con que el modelo le pida a la persona la fecha y hora con la que
anotó originalmente. `reprogramar_mi_reserva` reusa el título y la
descripción del evento viejo (no hace falta volver a pedir nombre,
personas, etc.), cancela el turno viejo y crea uno nuevo — la API de
Calendar no tiene un PATCH atómico de horario que además re-chequee
disponibilidad, así que son dos pasos.

## Lista de espera

`anotar_lista_espera` (`herramientas.py`) — para cuando `anotar_reserva`
avisa que el horario está ocupado y la persona prefiere esperar en vez de
elegir otro. Deja una nota en Chatwoot con la etiqueta `lista-espera`; **no
hay re-aviso automático** cuando el horario se libera — eso lo hace
alguien del negocio a mano, filtrando la bandeja por esa etiqueta. Armar el
aviso automático (detectar que se liberó el horario y avisarle solo a la
persona en espera) queda para más adelante: necesitaría poder buscar, por
contenido, qué conversaciones están esperando ESE horario puntual, y hoy
no hay dónde guardar esa relación sin sumar una base de datos.

## Política de cancelación

`CANCELACION_HORAS_MINIMAS` en el `.env`. Si el turno es en menos de esas
horas, `cancelar_mi_reserva` y `reprogramar_mi_reserva` (`herramientas.py`)
no lo tocan: le avisan a la persona que hable directo con el negocio, en
vez de dejarle cancelar/mover algo a último momento por chat solo. `0` (el
default) es sin restricción — se comporta como antes de esto.

`_horas_hasta_el_turno()` está separada de `_chequear_anticipacion()` a
propósito: es lo que los tests reemplazan por un valor fijo, en vez de
pelearse con la hora real de la máquina que corre el test.

## De quién es el turno (no dejar cancelar el de otra persona)

`cancelar_mi_reserva` y `reprogramar_mi_reserva` buscan el evento por fecha
y hora (`Calendario.evento_en()`) — nada más, al principio. Eso significa
que si dos personas distintas dan la misma fecha y hora (por casualidad, o
alguien probando), cualquiera podía cancelar el turno de la otra. Se
arregla comparando la conversación que pide cancelar contra la que quedó
guardada en el evento (`conversacion_del_evento()`, en `calendario.py` —
la misma función que usa `recordatorios.py`):

- **Coinciden, o el turno no tiene esa marca guardada** (uno cargado a
  mano en Calendar, o de antes de que existiera esta protección) → se
  deja pasar. No cortar reservas viejas que hoy andan bien es más
  importante que blindar un caso raro.
- **No coinciden** → se rechaza, con un mensaje para que el modelo le
  avise a la persona que se comunique directo con el negocio.

`_chequear_propietario()` (`herramientas.py`) es la que decide esto; se
llama ANTES que `_chequear_anticipacion()`, así el mensaje que ve la
persona es el correcto según cuál de las dos cosas falló.

## Recordatorios automáticos

`recordatorios.py` (raíz del repo) — un programa que corre, avisa lo que
tenga que avisar por WhatsApp, y termina. No es parte del servidor: la
idea es dejarlo programado aparte (una **Scheduled Task de Coolify**,
apuntando a `python recordatorios.py` en el mismo contenedor de
`agente-whatsapp`, corriendo por ejemplo cada una hora).

Necesita **Google Calendar Y Chatwoot** configurados — el calendario para
saber qué turnos hay, Chatwoot para saber por dónde avisarle a cada
persona. Sin alguno de los dos, no hace nada y no tira error: es seguro
dejarlo programado en cualquier instancia, esté o no armada para esto.

Dos decisiones de diseño que no son obvias:

- **Cómo sabe a quién avisarle, sin una base de datos.** `anotar_reserva()`
  ahora deja una línea `"Conversación: <id>"` en la **descripción del
  evento de Calendar** (no en la nota de Chatwoot — ahí la lee una
  persona, y ese dato no le sirve para nada). `recordatorios.py` la lee de
  vuelta con una regex. Un turno cargado a mano en Calendar, sin esa
  línea, se lo salta — no hay a quién avisarle.
- **Cómo evita avisar el mismo turno dos veces, sin una base de datos.**
  Al mandar el recordatorio, marca el evento mismo con
  `Calendario.marcar_recordado()` (`extendedProperties.private`, invisible
  para quien lo mira en Calendar). La próxima corrida lo salta con
  `calendario.ya_recordado(evento)`.

No le avisa a un turno **"tentative"** (`RESERVA_REQUIERE_APROBACION`
todavía sin aprobar) — avisarle a alguien de algo que el negocio puede
rechazar sería peor que no avisar nada.

`RECORDATORIO_HORAS_ANTES` (cuánta anticipación) y
`RECORDATORIO_VENTANA_MINUTOS` (el ancho de la ventana que barre cada
corrida) tienen que llevarse bien con cada cuánto programás la Scheduled
Task: con una corrida cada hora, la ventana tiene que ser de una hora como
mínimo para no dejar turnos sin avisar en el medio.

## Estadísticas para el dueño del negocio (nuevos vs. recurrentes)

`visitas.py` — una tabla propia (`visitas`) en la MISMA Postgres de
`MODO=produccion` (`POSTGRES_DSN`), para que el negocio pueda ver a fin de
mes cuántos turnos fueron de clientes nuevos y cuántos de recurrentes. Es
el punto de partida de un dashboard más adelante (todavía no existe
ninguna pantalla — esto es solo el registro).

**A propósito NO es una herramienta que el modelo decide llamar** — a
diferencia de `actualizar_ficha_cliente`, que en una prueba real el modelo
no llamó aunque tenía el dato a mano. Para que el conteo sea confiable, el
registro corre siempre, en código:

- `anotar_reserva()` (`herramientas.py`) registra la visita cuando confirma
  un turno DE UNA (sin aprobación manual).
- La ruta `/reservas/aprobar` (`web/webhook.py`) la registra cuando el
  negocio aprueba una reserva `"tentative"` — nunca al crearla, para no
  contar turnos que después se rechazan.
- La tabla se crea sola al arrancar (`visitas.preparar()`, en el
  `ciclo_de_vida` de `web/webhook.py`), mismo momento en que
  `PostgresSaver.setup()` arma las suyas para la memoria.

**Identidad = contacto de Chatwoot, no conversación.** Mismo motivo que
`actualizar_ficha_cliente`: si Chatwoot abre una conversación nueva porque
la anterior se resolvió, el `thread_id` cambia pero la persona es la
misma — `contacto_de()` es lo único estable para saber si alguien ya había
venido antes.

**"Nuevo" vs. "recurrente" (decisión de producto, 11 sep 2026):**
recurrente = ya tiene al menos una visita registrada antes, sin importar
cuánto hace. No hay ventana de tiempo (un cliente de hace dos años cuenta
igual que uno de la semana pasada) — se eligió así por simple, no por que
sea la única forma válida; si en algún momento hace falta distinguir
"activo" de "inactivo hace mucho" para una campaña de reactivación, es un
cálculo nuevo sobre los mismos datos, no un cambio de esquema.

Sin `POSTGRES_DSN` (`MODO=test`, o Postgres no configurado), no hace nada
y no rompe nada — mismo espíritu que `alertas.py`/`recordatorios.py`. Nunca
revienta una reserva ni una aprobación: perder una estadística no puede
voltear algo que ya pasó de verdad.

**La pantalla: `GET /estadisticas?token=...`** (`web/webhook.py`) — dos
tablas HTML simples, sin JavaScript ni build. Mismo criterio de seguridad
que `/reservas/{accion}`: un secreto fijo en la URL (`DASHBOARD_SECRETO`),
no una pantalla de login — sin esa variable puesta, la ruta da 404 aunque
alguien adivine cualquier token.

- **Resumen por mes** — `visitas.py: resumen_mensual()` (un `ROW_NUMBER()`
  por `contacto_id`: la primera visita de cada persona es "nueva", el
  resto "recurrente").
- **Detalle turno por turno** — `visitas.py: listar_visitas()`: nombre,
  teléfono, **motivo de consulta**, fecha, hora y si fue la primera vez,
  los últimos 200 por default (`limite`). Es lo que le permite al dueño
  responder "¿quién vino esta semana?", no solo "¿cuántos?".

**El motivo (`aclaracion` en `anotar_reserva`) se agregó después que el
resto de la tabla** — la columna se suma con `ALTER TABLE ... ADD COLUMN
IF NOT EXISTS` en `visitas.preparar()`, no con el `CREATE TABLE IF NOT
EXISTS` de siempre, porque en producción la tabla ya existía sin ella.
Es el patrón a seguir la próxima vez que se agregue un campo a `visitas`.
En la ruta de aprobación (`web/webhook.py`), el motivo y el teléfono no
vienen del evento como campos propios — se sacan de la descripción de
Calendar (`_campo_de_descripcion()`, busca la línea `"Aclaración: ..."` /
`"Teléfono: ..."` que arma `anotar_reserva()`).

A diferencia de `registrar_visita()`, acá un error de conexión **sí** se
muestra tal cual en la página (500, con el error) en vez de tragarse
silencioso: no hay ninguna reserva real en juego, así que mostrar el
problema es mejor que una tabla vacía que parece decir "no tuviste
turnos" sin serlo.

**El nombre, el teléfono y el motivo del detalle pasan por `html.escape()`
antes de entrar a la página.** Son texto que la persona escribió por
WhatsApp, no algo que el sistema generó — sin escapar, alguien podría
poner `<script>...</script>` como "nombre" (o como motivo) y que corra en
la pantalla que abre el dueño del negocio. El resumen mensual no necesita
esto: `mes` sale de `to_char()` en la propia consulta, no de lo que
alguien tipeó.

## Reintentos en Chatwoot y Google Calendar

`reintentos.py` — un timeout de red pasajero (una conexión que se corta a
mitad de camino, un 502 momentáneo) ya no tira abajo una reserva o una
respuesta: `Calendario._api()` / `_access_token()` y `Chatwoot._api()`
reintentan hasta 3 veces con backoff (0.5s, 1s) antes de subir el error.
Solo reintenta errores de red y 5xx — un 4xx (token vencido, pedido mal
armado) sube de una, porque insistir no lo arregla y solo demora la
respuesta a la persona.

## Que la falla se note sola (no que la note un cliente)

Caso real que motivó esto: la conexión a Postgres se cortó sola en
producción; el proceso del webhook siguió vivo, así que Coolify lo seguía
mostrando sano, y nadie se enteró hasta que alguien preguntó algo por
WhatsApp y vio el error crudo de Python en la respuesta. Tres cambios,
todos en `web/webhook.py`:

- **`/salud` ahora prueba la memoria de verdad** (`memoria.verificar()`),
  no solo contesta "ok". Para Postgres hace un `SELECT 1` contra el pool;
  para SQLite no hace falta nada, es un archivo local. Si la memoria no
  contesta, `/salud` devuelve 503 — así Coolify se entera y reinicia el
  contenedor solo, en vez de mostrarlo "sano" mientras nadie recibe
  respuesta.
- **La persona ya no ve el error crudo.** Antes, cuando `agente.responder_partido()`
  reventaba, el mensaje que salía por WhatsApp era literalmente
  `f"Se me rompió algo: {type(e).__name__}: {e}"` — siguiendo la regla
  general del proyecto de no esconder el error del proveedor (ver "Reglas
  al escribir código acá"). Esa regla tiene sentido cuando "el usuario" sos
  vos probando en `servidor.py`/`chat.py`; en el webhook de WhatsApp del
  otro lado hay un cliente de verdad de la empresa que te contrata, y un
  `OperationalError` en pleno chat no es información, es mala imagen. Ahora
  la persona ve `MENSAJE_ERROR_GENERICO` (uno solo, fijo) y el error real
  sigue yendo a los logs igual que antes — es la única excepción a esa
  regla, y queda documentada acá a propósito, como pide la regla misma.
- **`alertas.py` avisa por Telegram** cuando `responder()` revienta o
  `/salud` detecta la memoria caída — un bot aparte del que atiende
  clientes (`ALERTA_TELEGRAM_TOKEN`/`ALERTA_TELEGRAM_CHAT_ID` en el `.env`,
  los dos opcionales: sin ellos no avisa nada y no rompe nada). Tiene un
  cooldown de 5 minutos por tipo de error para no convertirse en spam
  mientras la misma falla sigue activa.

## Dónde termina el dato de una persona (para hablarlo con el cliente)

Útil el día que el negocio pregunta "¿y lo que me cuenta la gente, dónde
queda?" — por ejemplo un consultorio donde `aclaracion` (`anotar_reserva`,
`herramientas.py`) puede terminar teniendo un motivo de consulta, no solo
"una alergia" o "un pedido especial". El agente no le pone ningún límite
especial a ese campo: es texto libre, y termina en varios lugares distintos
a la vez, cada uno con dueño distinto:

- **Google Calendar** — `calendario.crear_evento()` lo mete en la
  descripción del evento, junto con la marca `"Conversación: <id>"` que
  usan `recordatorios.py` y `cancelar_mi_reserva`/`reprogramar_mi_reserva`
  para saber de quién es el turno. Vive en la cuenta de Google del negocio,
  no en la tuya — quien tenga acceso a ese calendario lo ve.
- **Chatwoot (conversación)** — `Chatwoot.anotar()` deja una nota privada en
  la conversación, visible para cualquiera del equipo del negocio con acceso
  a esa bandeja. No le llega al paciente (es nota, no mensaje).
- **Chatwoot (contacto)** — `actualizar_ficha_cliente` (`herramientas.py`)
  guarda el nombre en el contacto nativo de Chatwoot y datos sueltos como
  notas de ESE contacto (`Chatwoot.actualizar_nombre_contacto()` /
  `agregar_nota_contacto()`) — a diferencia de `Chatwoot.anotar()`, esto
  queda pegado a la persona y sobrevive aunque la próxima charla sea otro
  hilo de conversación.
- **Postgres (`MODO=produccion`)** — el checkpointer de LangGraph guarda la
  conversación **entera**, cada mensaje, **para siempre**. No hay ningún
  borrado automático hoy: `MEMORIA_MENSAJES` solo recorta cuánto le mandás
  al modelo en el próximo pedido (ver `_recortar()` en `agente.py`), no
  borra nada de la base. Si en algún momento se agrega una política de
  retención (borrar conversaciones sin actividad hace X días), es un script
  aparte, con el mismo espíritu que `recordatorios.py`: corre solo, no
  toca nada si no hay algo para borrar.
- **El backup de esa Postgres** — mismo dato, una copia más, en el disco
  del servidor (ver la sección de Coolify más abajo si hay una, o el panel
  directamente). Con retención "sin límite" hoy: se acumulan para siempre
  también.
- **El proveedor del modelo** (Anthropic/OpenAI/Gemini, según `PROVEEDOR`)
  — cada mensaje de la conversación se le manda para que el agente pueda
  responder. Sale de este repo hacia la política de datos de esa empresa,
  no algo que controle el código de acá.
- **La alerta de Telegram** (`alertas.py`) — solo si `responder()` revienta:
  manda el tipo de error y el id de conversación, no el contenido de los
  mensajes.

Nada de esto es un bug: es cómo está armado hoy, sin ninguna política de
borrado. Si el negocio necesita algo más estricto (borrar a pedido, no
guardar cierto tipo de dato), es una conversación de producto antes que de
código — este bloque existe para tenerla con datos concretos en la mano,
no de memoria.

**Política acordada (11 sep 2026): retener 2 años por default.** Es una
decisión de producto, no una garantía legal (no es asesoría — varía según
el país; acá aplica GDPR por ser un negocio en la UE) — **todavía no hay
ningún script que la haga cumplir**. Falta el mismo tipo de programa que
`recordatorios.py`: corre solo, borra lo que tenga más de 2 años en
Postgres (conversaciones) y en las notas de contacto de Chatwoot, no toca
nada si no hay nada vencido. Hasta que exista, esto es una política
escrita, no una que el sistema cumpla sola.


## Hacia dónde va (para no diseñar en contra)

Esto todavía **no está implementado** y no hay que implementarlo sin que lo
pidan. Está acá para que cualquier cosa que se agregue al núcleo no lo haga
imposible después.

**Video 2 — Telegram. ✅ Hecho.** `canales/telegram.py` implementa `Canal`,
`conversacion` = el `chat_id`, y el bucle que las pega está en
`bot_telegram.py` (raíz). Anda por *polling*, así que corre en la máquina de
uno sin dominio ni puertos abiertos. Sirve igual con `MODO=test` (SQLite) que
con `MODO=produccion` (Postgres): el agente no cambia.

**Video 3 — WhatsApp. ✅ Hecho, con Chatwoot en el medio.**

El agente **no le habla a Meta**: le habla a Chatwoot, que ya está conectado
a WhatsApp. Eso cambia el diseño respecto de lo que decía este archivo antes,
y para mejor: la mitad de las piezas las resuelve Chatwoot.

    persona → WhatsApp → Meta → Chatwoot → webhook → agente
                                   ↑                    │
                                   └──── API REST ──────┘

| Pieza | Dónde quedó | Cómo se resolvió |
|---|---|---|
| Autenticar quién llama al webhook | `web/webhook.py` | Chatwoot **no firma** sus webhooks (no hay HMAC como en Meta): la seguridad es un token secreto en la URL, `CHATWOOT_WEBHOOK_TOKEN` |
| Responder 200 rápido y procesar aparte | `web/webhook.py` | El 200 sale antes de pensar la respuesta; si no, Chatwoot reintenta y el agente contesta de más |
| Descartar el mensaje repetido por id | `Chatwoot.deberia_responder()` | Cola de los últimos 1.000 ids |
| **Que el agente no se conteste a sí mismo** | `Chatwoot.deberia_responder()` | Solo se atiende `message_type == "incoming"`. Sin esto es un ida y vuelta infinito que gasta tokens en cada vuelta |
| Juntar la ráfaga de mensajes | `canales/buffer.py` | En memoria, no Redis: hay un solo proceso atendiendo. `BUFFER_SEGUNDOS` |
| Partir la respuesta en varios globos | `respuesta.partir_respuesta()` | Ya estaba |
| Traspaso a una persona | `Chatwoot.deberia_responder()` | La etiqueta `CHATWOOT_ETIQUETA_HUMANO` apaga al bot en esa conversación, con un clic desde la bandeja |
| Notas privadas | `Chatwoot.deberia_responder()` | Son para el equipo: el agente no las contesta |
| Ventana de 24h y plantillas | Lo maneja Chatwoot | Por eso no está acá |

**El `conversacion` (thread_id) es el id de conversación de Chatwoot.** Un
hilo en la bandeja es un hilo de memoria del agente, y es también lo que se
necesita para contestar: sirve para las dos cosas.

**Decisiones ya tomadas** (no volver a discutirlas):

- **Un solo repo.** Cada canal es un archivo nuevo; el núcleo no se toca.
  Se cumplió: `agente.py` no se tocó para que atienda WhatsApp.
- **Chatwoot es opcional**, no obligatorio. El agente sigue andando por
  terminal, web y Telegram sin él.
- ~~**Redis** para juntar los mensajes~~ → **quedó en memoria**
  (`canales/buffer.py`). Redis resolvía compartir la ráfaga entre varios
  procesos, y hoy hay uno solo atendiendo. Sumar una base entera para eso era
  pagar un problema que todavía no tenemos. Cuando se escale a varios
  procesos se cambia esa clase y el webhook ni se entera.
- **`MODO=test` responde y listo.** Todo lo de arriba corre solo en
  `MODO=produccion`.

**Ya preparado en el núcleo para que eso entre sin reescribir nada:**

- `canales/base.py` — la forma de un canal y el gancho `deberia_responder()`
- `respuesta.partir_respuesta()` — la respuesta en varios mensajes
- `Agente.responder_partido()` — lo mismo, listo para usar
- `Transmision` — el resumen vive en cada respuesta, **no** en el agente, así
  varias conversaciones a la vez no se pisan los datos

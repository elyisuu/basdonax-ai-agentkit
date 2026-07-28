# AgentKit

Un agente de IA que corre **en tu computadora**. Sin servidor, sin hosting,
sin pagar infraestructura. Funciona con **Claude, OpenAI o Gemini** —
elegís cuál desde una lista, sin tocar código.

Viene con una plataforma de pruebas: una web local donde le hablás al agente,
cambiás de modelo en caliente, editás su personalidad y ves cuántos tokens
gastás en cada mensaje.

```
┌──────────────────────────────────────────────────┐
│  Vos escribís                                     │
│      ↓                                            │
│  Prompt del sistema  ← prompts/sistema.md         │
│  Memoria             ← LangGraph (thread_id)      │
│  Modelo              ← Claude / OpenAI / Gemini   │
│      ↓                                            │
│  El agente responde                               │
└──────────────────────────────────────────────────┘
```

---

## Índice

1. [Arrancar en 3 pasos](#arrancar-en-3-pasos)
2. [Qué hay adentro](#qué-hay-adentro)
3. [Elegir el modelo](#elegir-el-modelo)
4. [La barra de ajustes](#la-barra-de-ajustes)
5. [La memoria: cómo funciona](#la-memoria-cómo-funciona)
6. [Modo test y modo producción](#modo-test-y-modo-producción)
7. [El caché: gastar menos](#el-caché-gastar-menos)
8. [Cambiar la personalidad](#cambiar-la-personalidad)
9. [Usarlo desde tu código](#usarlo-desde-tu-código)
10. [Todas las variables del .env](#todas-las-variables-del-env)
11. [Preguntas que aparecen siempre](#preguntas-que-aparecen-siempre)

---

## Arrancar en 3 pasos

### 1. Instalar

```bash
git clone <este-repo>
cd AgentKit

python -m venv .venv
```

Activar el entorno:

```bash
# Windows
.venv\Scripts\activate

# Mac o Linux
source .venv/bin/activate
```

Instalar:

```bash
pip install -r requirements.txt
```

### 2. Poner una clave

```bash
# Windows
copy .env.example .env

# Mac o Linux
cp .env.example .env
```

Abrí el `.env` y completá **un solo** proveedor:

| Proveedor | Dónde sacar la clave | Qué completás |
|---|---|---|
| **Claude** | [console.anthropic.com](https://console.anthropic.com/settings/keys) | `ANTHROPIC_API_KEY` |
| **OpenAI** | [platform.openai.com](https://platform.openai.com/api-keys) | `OPENAI_API_KEY` |
| **Gemini** | [aistudio.google.com](https://aistudio.google.com/apikey) | `GOOGLE_API_KEY` |

Con uno alcanza. Si cargás más de uno, los cambiás desde la web con un botón.

> El `.env` está en `.gitignore`. **Nunca se sube a GitHub.**

### 3. Probarlo

```bash
python servidor.py
```

Abrí **http://localhost:8000**.

¿Preferís la terminal? `python chat.py`

---

## Qué hay adentro

```
AgentKit/
├── prompts/
│   └── sistema.md          ← la personalidad del agente (editalo)
├── src/agente/
│   ├── agente.py           ← EL AGENTE. El grafo de LangGraph.
│   ├── modelos.py          ← Claude / OpenAI / Gemini
│   ├── memoria.py          ← dónde se guardan las conversaciones
│   ├── prompts.py          ← lee el prompt del archivo
│   ├── respuesta.py        ← parte una respuesta larga en varios mensajes
│   ├── config.py           ← lee el .env
│   ├── canales/            ← Telegram y WhatsApp van acá
│   └── web/                ← la plataforma de pruebas
├── tests/                  ← 30 tests que no gastan un solo token
├── chat.py                 ← hablarle desde la terminal
├── servidor.py             ← levantar la web
├── AGENTS.md               ← contexto para Codex, Claude Code, Cursor…
├── CLAUDE.md               ← apunta a AGENTS.md
└── .env                    ← tus claves (no se sube)
```

**Si vas a leer un solo archivo, leé `src/agente/agente.py`.** Ahí está todo
el agente: el grafo son 12 líneas, el resto es explicación y los ayudantes.

---

## Elegir el modelo

La plataforma **le pregunta a cada proveedor qué modelos tiene hoy** y te los
muestra en una lista, con el más nuevo arriba. No hay una lista escrita a mano
que envejezca: si mañana sale un modelo nuevo, aparece solo.

- El selector de arriba muestra los modelos disponibles.
- El botón **↻** vuelve a preguntar (por si acaba de salir uno).
- Cambiar de modelo **no borra la conversación**: podés arrancar con uno,
  cambiar a otro y seguir la misma charla.
- **El máximo de respuesta se acomoda solo.** Cada modelo aguanta una cantidad
  distinta de tokens de respuesta; la plataforma le pregunta cuánto es y lo
  pone. No es algo que tengas que saber ni tocar.

¿No querés tocar la web? Ponelo en el `.env` y listo:

```bash
PROVEEDOR=claude
MODELO_CLAUDE=claude-opus-5
```

Si el modelo del `.env` no existe o la lista no carga (sin internet, clave
vencida), la plataforma usa igual lo que diga el `.env`.

---

## La barra de ajustes

Debajo de los modelos hay una barra con el estado del agente:

```
modo test    memoria SQLite    caché activado    máx. respuesta 128.000 tokens    recuerda [20] mensajes
```

**Lo único editable ahí es "recuerda".** Escribís el número y listo: se guarda
en el `.env` y se aplica al instante, sin reiniciar el servidor.

El resto está fijo a propósito:

| | Por qué |
|---|---|
| **modo** | La plataforma es para probar en tu máquina: siempre `test`. Para pasar a producción se edita el `.env`. |
| **caché** | Siempre activado. No hay razón para apagarlo salvo que estés midiendo cuánto ahorra. |
| **máx. respuesta** | **Lo define el modelo, no vos.** Cada modelo aguanta un máximo distinto, así que la plataforma le pregunta cuánto es y lo pone. Cambiás de modelo y se acomoda solo. |

Todo lo demás se cambia editando el `.env`. Cuando la plataforma escribe ahí,
**respeta los comentarios y el orden** del archivo: solo reemplaza la línea de
esa variable. Y las claves de API nunca se editan desde el navegador.

---

## La memoria: cómo funciona

Esto es lo que más confunde y lo que casi nadie explica:

> **Las APIs de los modelos no recuerdan nada.**
> Cada llamada es independiente. Que el agente "se acuerde" de lo que hablaron
> es puro trabajo tuyo: le volvés a mandar la conversación entera cada vez.

LangGraph resuelve eso con dos ideas:

- **`thread_id`** — el identificador de una conversación. Cada valor distinto
  es una charla separada, con su propia memoria.
- **checkpointer** — dónde se guardan esas conversaciones.

```python
agente.responder("Hola, me llamo Facu", conversacion="chat-1")
agente.responder("¿Cómo me llamo?",     conversacion="chat-1")  # → "Facu"
agente.responder("¿Cómo me llamo?",     conversacion="chat-2")  # → no sabe
```

Ese `thread_id` es exactamente lo que después va a ser el número de WhatsApp
o el chat de Telegram de cada persona. **Ahí está el truco de todo esto:**
el mismo agente atiende a mil personas sin mezclar las conversaciones.

### Cuánto recuerda

`MEMORIA_MENSAJES=20` en el `.env`, o el campo **recuerda** en la plataforma.
Son **mensajes**, no tokens (cuentan los tuyos y los del agente).

Ojo con la diferencia:

- **Se guardan todos.** El historial completo queda en la base.
- **Se le mandan al modelo solo los últimos N.** Eso es lo que controla este
  número.

Por eso es la palanca más directa sobre el costo: la conversación viaja entera
en cada mensaje, así que bajar de 20 a 10 es, más o menos, la mitad del gasto
en charlas largas. La contra es que el agente se olvida antes.

Para verlo funcionar: ponelo en 4, decile tu nombre, mandale tres mensajes
cualquiera y después preguntale cómo te llamás. No se va a acordar.

---

## Modo test y modo producción

Una sola variable decide dónde se guardan las conversaciones:

```bash
MODO=test        # SQLite: un archivo. No instalás nada.
MODO=produccion  # Postgres: para varios procesos atendiendo a la vez.
```

|  | `test` | `produccion` |
|---|---|---|
| Guarda en | Un archivo `.db` | Postgres |
| Sobrevive al reinicio | Sí | Sí |
| Varios procesos a la vez | No | Sí |
| Hay que instalar algo | No | Sí (ver abajo) |
| Para qué sirve | Desarrollar · un bot chico de Telegram | WhatsApp · producción de verdad |

### Pasar a producción

```bash
pip install langgraph-checkpoint-postgres
```

En el `.env`:

```bash
MODO=produccion
POSTGRES_DSN=postgresql://usuario:clave@servidor:5432/agente
```

Nada más. **Las tablas las crea solo** la primera vez que arranca. Y el agente
no se toca: es la misma clase, el mismo grafo, el mismo código.

> ¿No tenés Postgres? Con Docker, en una línea:
> ```bash
> docker run -d --name agente-pg -p 5432:5432 \
>   -e POSTGRES_PASSWORD=clave -e POSTGRES_DB=agente postgres:17
> ```
> Y el DSN queda: `postgresql://postgres:clave@localhost:5432/agente`

### Y si querés memoria que no guarde nada

Existe una tercera, para tests o para ver el agente en su forma más simple:

```python
from agente import Agente
from agente.memoria import ram

a = Agente(checkpointer=ram())   # se borra al cerrar el programa
```

---

## El caché: gastar menos

El prompt del sistema viaja **entero, en cada mensaje**. Si tu prompt tiene
2.000 tokens y mandás 100 mensajes, pagaste 200.000 tokens por el mismo texto.

El caché hace que el proveedor lo guarde de su lado y te cobre una fracción a
partir del segundo mensaje.

```bash
CACHE=true    # en el .env — viene activado, dejalo así
```

| Proveedor | Cómo funciona |
|---|---|
| **Claude** | Hay que marcarlo a mano — es lo que hace este repo por vos |
| **OpenAI** | Automático, no hay que hacer nada |
| **Gemini** | Automático, no hay que hacer nada |

**Dos cosas para tener en cuenta:**

1. El caché **recién se activa cuando el prompt supera cierto tamaño**
   (alrededor de 1.000 tokens). Con un prompt corto no pasa nada malo:
   simplemente no se cachea. No es un error.
2. La plataforma te muestra el ahorro en cada mensaje: cuando el caché entra,
   aparece **⚡ N desde caché** debajo de la respuesta.

---

## Cambiar la personalidad

Editá **`prompts/sistema.md`**, guardá, y el próximo mensaje ya sale distinto.
**No hay que reiniciar nada**: el archivo se lee en cada mensaje.

Desde la web lo tenés al costado, con un botón de guardar.

Es la forma más rápida de ver qué cambia: escribí algo, cambiá el prompt,
volvé a escribir lo mismo.

---

## Usarlo desde tu código

El agente recibe texto y devuelve texto. Nada más. Eso es lo que después
permite enchufarlo a cualquier canal:

```python
import sys; sys.path.insert(0, "src")
from agente import Agente

a = Agente()

# Respuesta completa
respuesta = a.responder("Hola", conversacion="usuario-123")
print(respuesta.texto)
print(respuesta.tokens_entrada, respuesta.tokens_salida)
print(respuesta.tokens_cache_leidos)   # cuánto salió del caché

# Respuesta en vivo, mientras se escribe
transmision = a.responder_en_vivo("Contame un chiste", conversacion="usuario-123")
for pedazo in transmision:
    print(pedazo, end="", flush=True)
print(transmision.resumen.tokens_salida)

# Ya partida en varios mensajes (para mensajería)
for mensaje in a.responder_partido("Explicame cómo funciona", conversacion="usuario-123"):
    print("─", mensaje)
```

Conectarlo a Telegram o WhatsApp es escribir el pegamento que traduce
"mensaje que llega" → `a.responder(texto, conversacion=<id del chat>)` →
"mensaje que sale". **El agente no cambia.**

Un detalle que importa cuando haya muchas conversaciones a la vez: el
resumen (tokens, modelo) vive en cada `Transmision`, **no** en el agente.
Si viviera en el agente, dos personas escribiendo al mismo tiempo se
pisarían los datos.

### Agregar herramientas

Este agente conversa: todavía no busca en internet ni lee tus archivos.
Cuando quieras que haga cosas, se le agregan nodos al grafo en
`src/agente/agente.py`. El resto del proyecto no se toca.

---

## Todas las variables del `.env`

| Variable | Por defecto | Qué hace |
|---|---|---|
| `PROVEEDOR` | `claude` | `claude`, `openai` o `gemini` |
| `ANTHROPIC_API_KEY` | — | Tu clave de Claude |
| `OPENAI_API_KEY` | — | Tu clave de OpenAI |
| `GOOGLE_API_KEY` | — | Tu clave de Gemini |
| `MODELO_CLAUDE` | `claude-opus-5` | Qué modelo de Claude usar |
| `MODELO_OPENAI` | `gpt-5` | Qué modelo de OpenAI usar |
| `MODELO_GEMINI` | `gemini-2.5-pro` | Qué modelo de Gemini usar |
| `MODO` | `test` | `test` (SQLite) o `produccion` (Postgres) |
| `SQLITE_RUTA` | `datos/conversaciones.db` | Dónde va el archivo, en modo test |
| `POSTGRES_DSN` | — | La conexión, en modo producción |
| `CACHE` | `true` | Cachear el prompt del sistema |
| `MAX_TOKENS` | `4096` | Cuánto puede escribir el agente por respuesta |
| `MEMORIA_MENSAJES` | `20` | Cuántos mensajes recuerda |
| `PROMPT_SISTEMA` | `prompts/sistema.md` | Qué archivo usar de personalidad |

---

## Preguntas que aparecen siempre

**¿Necesito pagar un servidor?**
No. Corre en tu computadora. Lo único que pagás es el consumo del modelo
(y Gemini tiene un plan gratis para empezar).

**¿Funciona sin internet?**
Con estos tres proveedores no, porque el modelo corre en la nube de ellos.
Si querés 100% local, hay que cambiar `modelos.py` para que apunte a Ollama.

**¿Por qué se olvida de todo cuando cierro el programa?**
No debería: en `MODO=test` guarda en un archivo y sobrevive al reinicio.
Si estás usando `ram()` a mano, eso sí se borra.

**¿Cuánto sale?**
Depende del modelo y de cuánto hables. La web te muestra los tokens de cada
mensaje. Tres formas de gastar menos, de mayor a menor impacto:
1. Usar un modelo más chico (los "mini" / "haiku" salen mucho menos)
2. Bajar `MEMORIA_MENSAJES`
3. Dejar `CACHE=true` (ya viene así)

**Me tira un error y no entiendo.**
La web muestra el error tal cual viene del proveedor, sin esconderlo. Los tres
motivos habituales:
- La clave está mal pegada (le sobra un espacio o le falta un pedazo)
- El nombre del modelo en el `.env` no existe → elegilo de la lista
- No tenés saldo en la cuenta del proveedor

**¿Puedo usarlo con Claude Code?**
Sí, y con Codex y Cursor también. El archivo **`AGENTS.md`** lo leen solos:
les explica la arquitectura, dónde tocar cada cosa, las convenciones y las
trampas del código. Abrí el agente que uses en la carpeta y pedile lo que
quieras.

---

## Con qué está hecho

[LangChain](https://python.langchain.com) + [LangGraph](https://langchain-ai.github.io/langgraph/)
para el agente y la memoria · [FastAPI](https://fastapi.tiangolo.com) para la
plataforma de pruebas · Python 3.10 o más nuevo.

---

Hecho por [Basdonax AI](https://basdonax.com).

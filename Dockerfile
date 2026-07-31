# El agente atendiendo en Telegram, en un servidor.
#
# Esto NO levanta la plataforma de pruebas: corre `bot_telegram.py`, que es
# un proceso que escucha Telegram y contesta. Por eso la imagen no abre
# ningún puerto ni necesita dominio — el bot sale a buscar los mensajes
# (polling), nadie entra a buscarlo a él.
#
# Toda la configuración entra por variables de entorno. El .env no se copia
# acá adentro: en el servidor las variables las pone Coolify.

FROM python:3.13-slim

# Sin esto, Python se guarda los logs en un buffer y en el panel del servidor
# no ves nada hasta que el proceso muere. Con un bot que corre para siempre,
# eso es no ver nunca nada.
ENV PYTHONUNBUFFERED=1

# Que las tildes no rompan cuando se imprime un mensaje.
ENV PYTHONIOENCODING=utf-8

WORKDIR /app

# Las dependencias primero y el código después: así, mientras no toques los
# requirements, Docker reusa la capa ya instalada y el deploy tarda segundos
# en vez de minutos.
COPY requirements.txt requirements-produccion.txt ./
RUN pip install --no-cache-dir -r requirements-produccion.txt

COPY src/ ./src/
COPY prompts/ ./prompts/
COPY bot_telegram.py ./

# Sin esto corre como root sin necesidad: el bot no escribe nada en disco
# (la memoria va a Postgres).
RUN useradd --create-home agente && chown -R agente:agente /app
USER agente

CMD ["python", "bot_telegram.py"]

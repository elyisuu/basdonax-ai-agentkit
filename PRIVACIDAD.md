# Privacidad — qué contarle al cliente sobre los datos de sus pacientes

Esto no es asesoría legal — es un punto de partida para la conversación
con el negocio, con datos concretos de cómo está armado el sistema (ver
`AGENTS.md` → "Dónde termina el dato de una persona", que es la fuente
técnica de todo lo que dice este archivo). Antes de que el negocio lo
publique como propio, que lo revise alguien que sepa de verdad de GDPR en
su país — con más razón siendo un consultorio de salud: el motivo de
consulta es un dato de **categoría especial** (Art. 9 GDPR), no un dato
personal cualquiera.

## Por qué esta conversación no es opcional

Physiomove (o cualquier clínica en la UE) ya responde ante sus propios
pacientes por el RGPD/GDPR, tenga o no un bot de WhatsApp — vos no cambiás
esa obligación, pero sí cambiás POR DÓNDE pasan los datos, y eso el
negocio tiene que poder explicarlo si un paciente pregunta. No hace falta
un documento perfecto: alcanza con que exista, sea verdad, y el negocio lo
entienda antes de que se lo repita a un paciente.

## Qué datos junta el bot, y dónde quedan

Lo que un paciente escribe (nombre, teléfono, motivo de consulta) termina,
según el caso:

- **En el calendario de Google del negocio** — junto con la reserva.
- **En Chatwoot** — como nota interna en la conversación, y en la ficha
  del contacto (para que el bot lo recuerde la próxima vez).
- **En la Postgres del negocio** — la conversación completa, y una fila
  por turno confirmado (para las estadísticas de `/estadisticas`).
- **En el proveedor del modelo** (Anthropic, en el caso de Physiomove) —
  cada mensaje se le manda para que el bot pueda responder. Es el mismo
  circuito que si el negocio usara ChatGPT o cualquier otro asistente de
  IA: sale de este sistema hacia la política de datos de esa empresa.

Nadie fuera del equipo del negocio (y vos, como quien lo mantiene) tiene
acceso a nada de esto.

## Cuánto tiempo se guarda

**2 años desde la última actividad**, después se borra solo — hay un
programa (`retencion.py`) que corre una vez por mes y lo hace cumplir. Es
una política de producto, no algo que el RGPD exija en ese número exacto;
si el negocio necesita otro plazo, se cambia en el código.

## Qué puede pedir un paciente (y qué hacer si lo pide)

Bajo GDPR, un paciente puede pedir ver qué tienen guardado de él, corregir
un dato mal cargado, o pedir que se borre antes de los 2 años. Hoy no hay
un botón de autoservicio para esto — si pasa, el negocio te escribe a vos
y lo resolvés a mano (buscar la conversación por teléfono/nombre y
borrarla de Postgres/Chatwoot/Calendar). Vale la pena que el negocio sepa
que este paso existe, aunque sea manual.

## Borrador para la política de privacidad del negocio

Esto es un punto de partida, en español — **hay que traducirlo al
portugués** antes de que Physiomove se lo muestre a un paciente, y que lo
revise alguien con criterio legal antes de publicarlo:

> Cuando escribís por WhatsApp para agendar o consultar un turno, un
> asistente automatizado te responde en nuestro nombre. Los datos que nos
> compartís (nombre, teléfono, motivo de consulta) se usan únicamente
> para gestionar tu turno y se conservan hasta 2 años desde tu última
> interacción con nosotros, después se eliminan automáticamente. Podés
> pedirnos en cualquier momento ver, corregir o eliminar esta
> información escribiéndonos directamente.

## Lo que este documento NO resuelve

- Si Physiomove necesita una base legal explícita para procesar datos de
  salud (consentimiento explícito del paciente vs. la excepción de
  "necesario para la prestación de cuidado sanitario") — eso lo define un
  abogado, no este archivo.
- Un DPA (Data Processing Agreement) formal entre vos y el negocio, si
  algún cliente lo pide — es un documento legal aparte, no algo que salga
  de este repo.

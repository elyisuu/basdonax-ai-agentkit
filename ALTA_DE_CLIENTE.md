# Alta de cliente — checklist de onboarding

Esto no lo lee el agente ni ningún otro coding agent — es la lista de pasos
para vos (el que vende esto) cada vez que sumás un negocio nuevo. Nace
después de la primera alta real (Physiomove) y se va a ir corrigiendo con
cada cliente siguiente: si algo de acá salió mal o faltó en una alta real,
actualizalo.

Marcá cada paso a medida que lo hacés. El orden importa: el punto 1 (WABA)
es el que más tarda en tener respuesta, así que arrancalo antes que nada,
en paralelo con todo lo demás.

---

## 0. Antes de firmar (comercial)

- [ ] Precio acordado: instalación + mensualidad (o "gratis las primeras 2
      semanas, después mensualidad si le sirvió" — el trato de los primeros
      clientes).
- [ ] Si es prueba gratis: dejar clarísimo qué pasa si no sigue (se apaga la
      instancia, no se cobra nada) — para que no haya sorpresa.
- [ ] Nombre y apellido de cada profesional que va a atender, tal cual
      quiere que el bot lo mencione (si son varios, ver "Varios
      profesionales" en `AGENTS.md`).
- [ ] Horario de atención del negocio (`HORARIO_DESDE` / `HORARIO_HASTA`,
      y si tiene franjas partidas, `HORARIO_FRANJAS`; días que no atiende,
      `DIAS_CERRADOS`).
- [ ] Política de cancelación: con cuántas horas mínimo se puede cancelar
      sin problema (`CANCELACION_HORAS_MINIMAS` — el default de 24hs es lo
      que se viene usando, preguntar si este negocio quiere otra cosa).
- [ ] Huso horario del negocio (`ZONA_HORARIA`, ej. `Europe/Lisbon`) — **no**
      el tuyo si vivís en otro país.

## 1. WhatsApp Business (WABA) — arrancarlo YA, tarda días

Cada cliente verifica **su propia** empresa, en **su propia** cuenta — no
una compartida tuya (si no te acordás por qué, la razón corta: un reporte
de spam contra un cliente puede tirar abajo el WABA completo, y con eso a
todos los que compartieran esa cuenta).

- [ ] El cliente crea/usa su Meta Business Manager y verifica su empresa
      (puede pedir documentos legales — es lo que más tarda).
- [ ] El cliente agrega su número de WhatsApp Business a esa cuenta.
- [ ] El cliente te da acceso de partner/admin sobre ese WABA para que
      puedas conectarlo a Chatwoot.

## 2. Google Calendar — un calendario por profesional

Ver el detalle completo en `AGENTS.md` → "Cómo se conecta Google Calendar"
(sección **Setup por cliente**, ya escrita paso a paso). Resumen:

- [ ] Un calendario de Google Calendar por profesional (si es uno solo,
      alcanza con uno).
- [ ] Cada calendario compartido con el email de la cuenta de servicio,
      permiso **"Modificar eventos"**.
- [ ] Copiar el `calendar_id` de cada uno (pantalla "Integrar calendario").

## 3. Chatwoot

- [ ] Crear la cuenta/inbox de Chatwoot para este cliente (no reusar la de
      otro).
- [ ] Conectar ahí el número de WhatsApp ya verificado (paso 1).
- [ ] Generar un `CHATWOOT_WEBHOOK_TOKEN` nuevo para esta instancia — nunca
      reusar el de otro cliente.

## 4. `.env` de esta instancia

Completar (ver `.env.example` para el detalle de cada uno):

- [ ] `GOOGLE_SERVICE_ACCOUNT_JSON` (el mismo de siempre, es la cuenta de
      servicio única para todos los clientes)
- [ ] `GOOGLE_CALENDAR_ID` (un solo profesional) **o** `PROFESIONALES`
      (varios — formato `Nombre:calendar_id,Nombre2:calendar_id2`)
- [ ] `ZONA_HORARIA`, `HORARIO_DESDE`, `HORARIO_HASTA`,
      `CANCELACION_HORAS_MINIMAS` (lo acordado en el punto 0)
- [ ] `CHATWOOT_URL`, `CHATWOOT_TOKEN`, `CHATWOOT_CUENTA_ID`,
      `CHATWOOT_WEBHOOK_TOKEN` (el del punto 3)
- [ ] `RESERVA_SECRETO` y `URL_PUBLICA` (si este negocio quiere aprobación
      manual antes de confirmar turnos — Nivel 1.5) o
      `RESERVA_REQUIERE_APROBACION=false` (si confía en la confirmación
      automática)
- [ ] `DASHBOARD_SECRETO` (para el `/estadisticas` que le vas a mandar al
      dueño)
- [ ] `POSTGRES_DSN` propio de esta instancia (memoria de conversación +
      tabla de visitas — no compartir la base entre clientes)
- [ ] `RECORDATORIO_HORAS_ANTES` / `RECORDATORIO_VENTANA_MINUTOS` si el
      default no aplica para este negocio

## 5. `prompts/sistema.md`

- [ ] Nombre del negocio, dirección, especialidades/servicios que ofrece
- [ ] Cualquier dato propio de este negocio que el bot deba saber de memoria
      (no vía herramienta) — precios de consulta, si acepta seguro médico,
      etc.
- [ ] Confirmar que sigue el alcance ya definido (no da consejo clínico,
      deriva a un profesional) — esto no debería cambiar de cliente a
      cliente, pero conviene releerlo una vez por las dudas.

## 6. Deploy

- [ ] Nueva app en Coolify para este cliente (hoy es una instancia por
      cliente, no multi-tenant — ver "Hacia dónde va" en `AGENTS.md` si
      esto cambia en el futuro).
- [ ] Confirmar `running:healthy` antes de avisarle a nadie.
- [ ] Smoke test manual con un número de prueba real: agendar un turno,
      consultar franjas ocupadas, cancelar, reprogramar, mandar una foto
      sin texto (confirmar que no se queda callado), y si hay varios
      profesionales, pedir turno sin decir con cuál (confirmar que
      pregunta en vez de adivinar).

## 7. Entrega

- [ ] Mandarle al dueño el link de `/estadisticas?token=...` con su
      `DASHBOARD_SECRETO` — explicarle qué va a ver ahí (nuevos vs.
      recurrentes) y que al principio, con pocos datos, va a verse vacío.
- [ ] Si es prueba gratis: decirle explícitamente la fecha en la que se
      termina y qué tiene que hacer para seguir.

## 8. Seguimiento

- [ ] Si era prueba gratis: recordatorio a los 14 días para pasar a
      mensualidad.
- [ ] Si no sigue: apagar la instancia y aplicar la política de retención
      de datos (2 años — el script para esto todavía está pendiente, ver
      `AGENTS.md`).

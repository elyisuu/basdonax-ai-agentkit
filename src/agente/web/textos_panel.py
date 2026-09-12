"""Los textos fijos de /estadisticas y de la pantalla de /reservas/{accion}
("Listo", "Reserva aprobada"...) en los tres idiomas que soporta
IDIOMA_PANEL (config.py) — es, pt, en.

Esto es DISTINTO de mensajes.py: acá el idioma lo elige el negocio una
sola vez en el .env (IDIOMA_PANEL), a mano, porque es texto que lee EL
DUEÑO del negocio al abrir esos links — no hay ninguna conversación de la
que sacar el idioma, y no tendría sentido pedirle al modelo que adivine.
Lo que le llega al CLIENTE FINAL (los avisos de confirmar/rechazar, el
recordatorio) sigue siendo dinámico, vía mensajes.py.

Formato: TEXTOS[idioma][clave]. `t()` hace el .format(**kwargs) para las
claves que llevan un valor adentro (ver "ayuda_detalle", "algo_fallo").
Si falta una clave en un idioma (no debería pasar — hay un test que
compara las tres contra "es"), cae a la versión en español antes que
reventar la página entera.
"""

from __future__ import annotations

TEXTOS: dict[str, dict[str, str]] = {
    "es": {
        "html_lang": "es",
        # -- /estadisticas --
        "titulo_pagina": "Estadísticas",
        "subtitulo": "Turnos confirmados: cuántos, quiénes, y si vuelven.",
        "tarjeta_turnos_mes": "Turnos este mes",
        "tarjeta_nuevos": "Nuevos",
        "tarjeta_recurrentes": "Recurrentes",
        "tarjeta_total": "Total histórico",
        "encabezado_turnos_por_mes": "Turnos por mes",
        "col_mes": "Mes",
        "col_turnos": "Turnos",
        "col_nuevos": "Nuevos",
        "col_recurrentes": "Recurrentes",
        "vacio_turnos": "Todavía no hay turnos registrados.",
        "encabezado_detalle": "Detalle",
        "ayuda_detalle": "Últimos {n} turnos, el más reciente primero.",
        "col_nombre": "Nombre",
        "col_telefono": "Teléfono",
        "col_motivo": "Motivo",
        "col_fecha": "Fecha",
        "col_hora": "Hora",
        "chip_nueva": "Nueva",
        "chip_recurrente": "Recurrente",
        "chip_cancelada": "Cancelada",
        # -- /reservas/{accion} --
        "accion_desconocida": "Acción desconocida.",
        "sin_reserva_secreto": (
            "Este negocio no tiene la aprobación por link configurada "
            "(falta RESERVA_SECRETO en el .env)."
        ),
        "sin_calendario_para_reserva": (
            "Este negocio no tiene la aprobación por link configurada "
            "para esta reserva (faltan GOOGLE_CALENDAR_ID/"
            "GOOGLE_SERVICE_ACCOUNT_JSON en el .env, o el profesional "
            "del link no coincide con ninguno de PROFESIONALES)."
        ),
        "link_invalido": "Link inválido o vencido.",
        "ya_no_existe": "Esta reserva ya no existe (puede que se haya rechazado antes).",
        "ya_aprobada": "Esta reserva ya estaba aprobada. No hace falta hacer nada más.",
        "aprobada_avisada": "Reserva aprobada. Ya se le avisó a la persona.",
        "ya_rechazada": "Esta reserva ya había sido rechazada antes.",
        "ya_confirmada_no_rechazar": (
            "Esta reserva ya está confirmada, no se puede rechazar por "
            "este link. Para cancelarla, hay que hacerlo directo desde "
            "Google Calendar."
        ),
        "rechazada_avisada": "Reserva rechazada. Ya se le avisó a la persona.",
        "algo_fallo": "Algo falló: {detalle}",
        "listo_titulo": "Listo",
        "no_encontrado": "No encontrado.",
        "confirmar_titulo": "Confirmar",
        "confirmar_pregunta_aprobar": "¿Aprobar esta reserva?",
        "confirmar_pregunta_rechazar": "¿Rechazar esta reserva?",
        "confirmar_boton_aprobar": "Sí, aprobar",
        "confirmar_boton_rechazar": "Sí, rechazar",
        "confirmar_ayuda": (
            "Esta página no hace nada por sí sola — el turno recién se "
            "aprueba o rechaza al tocar el botón."
        ),
    },
    "pt": {
        "html_lang": "pt",
        "titulo_pagina": "Estatísticas",
        "subtitulo": "Marcações confirmadas: quantas, quem, e se voltam.",
        "tarjeta_turnos_mes": "Marcações este mês",
        "tarjeta_nuevos": "Novas",
        "tarjeta_recurrentes": "Recorrentes",
        "tarjeta_total": "Total histórico",
        "encabezado_turnos_por_mes": "Marcações por mês",
        "col_mes": "Mês",
        "col_turnos": "Marcações",
        "col_nuevos": "Novas",
        "col_recurrentes": "Recorrentes",
        "vacio_turnos": "Ainda não há marcações registadas.",
        "encabezado_detalle": "Detalhe",
        "ayuda_detalle": "Últimas {n} marcações, a mais recente primeiro.",
        "col_nombre": "Nome",
        "col_telefono": "Telefone",
        "col_motivo": "Motivo",
        "col_fecha": "Data",
        "col_hora": "Hora",
        "chip_nueva": "Nova",
        "chip_recurrente": "Recorrente",
        "chip_cancelada": "Cancelada",
        "accion_desconocida": "Ação desconhecida.",
        "sin_reserva_secreto": (
            "Este negócio não tem a aprovação por link configurada "
            "(falta RESERVA_SECRETO no .env)."
        ),
        "sin_calendario_para_reserva": (
            "Este negócio não tem a aprovação por link configurada para "
            "esta marcação (falta GOOGLE_CALENDAR_ID/"
            "GOOGLE_SERVICE_ACCOUNT_JSON no .env, ou o profissional do "
            "link não corresponde a nenhum de PROFESIONALES)."
        ),
        "link_invalido": "Link inválido ou expirado.",
        "ya_no_existe": "Esta marcação já não existe (pode ter sido rejeitada antes).",
        "ya_aprobada": "Esta marcação já estava aprovada. Não é preciso fazer mais nada.",
        "aprobada_avisada": "Marcação aprovada. Já foi avisado o cliente.",
        "ya_rechazada": "Esta marcação já tinha sido rejeitada antes.",
        "ya_confirmada_no_rechazar": (
            "Esta marcação já está confirmada, não pode ser rejeitada "
            "por este link. Para a cancelar, tem de ser feito diretamente "
            "no Google Calendar."
        ),
        "rechazada_avisada": "Marcação rejeitada. Já foi avisado o cliente.",
        "algo_fallo": "Ocorreu um erro: {detalle}",
        "listo_titulo": "Pronto",
        "no_encontrado": "Não encontrado.",
        "confirmar_titulo": "Confirmar",
        "confirmar_pregunta_aprobar": "Aprovar esta marcação?",
        "confirmar_pregunta_rechazar": "Rejeitar esta marcação?",
        "confirmar_boton_aprobar": "Sim, aprovar",
        "confirmar_boton_rechazar": "Sim, rejeitar",
        "confirmar_ayuda": (
            "Esta página não faz nada sozinha — a marcação só é aprovada "
            "ou rejeitada ao tocar no botão."
        ),
    },
    "en": {
        "html_lang": "en",
        "titulo_pagina": "Statistics",
        "subtitulo": "Confirmed appointments: how many, who, and if they come back.",
        "tarjeta_turnos_mes": "Appointments this month",
        "tarjeta_nuevos": "New",
        "tarjeta_recurrentes": "Returning",
        "tarjeta_total": "All-time total",
        "encabezado_turnos_por_mes": "Appointments by month",
        "col_mes": "Month",
        "col_turnos": "Appointments",
        "col_nuevos": "New",
        "col_recurrentes": "Returning",
        "vacio_turnos": "No appointments recorded yet.",
        "encabezado_detalle": "Detail",
        "ayuda_detalle": "Last {n} appointments, most recent first.",
        "col_nombre": "Name",
        "col_telefono": "Phone",
        "col_motivo": "Reason",
        "col_fecha": "Date",
        "col_hora": "Time",
        "chip_nueva": "New",
        "chip_recurrente": "Returning",
        "chip_cancelada": "Cancelled",
        "accion_desconocida": "Unknown action.",
        "sin_reserva_secreto": (
            "This business doesn't have link approval configured "
            "(RESERVA_SECRETO is missing from .env)."
        ),
        "sin_calendario_para_reserva": (
            "This business doesn't have link approval configured for "
            "this booking (GOOGLE_CALENDAR_ID/GOOGLE_SERVICE_ACCOUNT_JSON "
            "is missing from .env, or the link's professional doesn't "
            "match any in PROFESIONALES)."
        ),
        "link_invalido": "Invalid or expired link.",
        "ya_no_existe": "This booking no longer exists (it may have been declined before).",
        "ya_aprobada": "This booking was already approved. Nothing else to do.",
        "aprobada_avisada": "Booking approved. The customer has been notified.",
        "ya_rechazada": "This booking had already been declined before.",
        "ya_confirmada_no_rechazar": (
            "This booking is already confirmed, it can't be declined "
            "through this link. To cancel it, do it directly from "
            "Google Calendar."
        ),
        "rechazada_avisada": "Booking declined. The customer has been notified.",
        "algo_fallo": "Something went wrong: {detalle}",
        "listo_titulo": "Done",
        "no_encontrado": "Not found.",
        "confirmar_titulo": "Confirm",
        "confirmar_pregunta_aprobar": "Approve this booking?",
        "confirmar_pregunta_rechazar": "Decline this booking?",
        "confirmar_boton_aprobar": "Yes, approve",
        "confirmar_boton_rechazar": "Yes, decline",
        "confirmar_ayuda": (
            "This page doesn't do anything by itself — the booking is "
            "only approved or declined when you tap the button."
        ),
    },
}


def t(idioma: str, clave: str, **kwargs: object) -> str:
    """El texto de `clave` en `idioma` — cae a español si falta cualquiera
    de los dos, para que un IDIOMA_PANEL mal escrito o una clave nueva sin
    traducir no rompan la página entera."""
    texto = TEXTOS.get(idioma, TEXTOS["es"]).get(clave) or TEXTOS["es"][clave]
    return texto.format(**kwargs) if kwargs else texto

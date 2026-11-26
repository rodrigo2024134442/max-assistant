"""
Integração com o Google Calendar para o MAX.
Usa a autenticação partilhada (google_auth.py) e expõe funções simples
para criar e listar eventos.
"""

import datetime

from googleapiclient.discovery import build
from google_auth import obter_credenciais

TIMEZONE = "Europe/Lisbon"

_servico_calendar = None


def _obter_servico():
    global _servico_calendar
    if _servico_calendar is None:
        creds = obter_credenciais()
        _servico_calendar = build("calendar", "v3", credentials=creds)
    return _servico_calendar


def criar_evento_calendario(titulo: str, data_hora_inicio: str, data_hora_fim: str = "", descricao: str = ""):
    """
    Cria um evento no Google Calendar principal.

    titulo: nome do evento
    data_hora_inicio: no formato ISO, ex: '2026-08-10T15:00:00'
    data_hora_fim: no formato ISO (opcional; por defeito dura 1 hora)
    descricao: texto opcional
    """
    try:
        servico = _obter_servico()

        inicio_dt = datetime.datetime.fromisoformat(data_hora_inicio)
        if data_hora_fim:
            fim_dt = datetime.datetime.fromisoformat(data_hora_fim)
        else:
            fim_dt = inicio_dt + datetime.timedelta(hours=1)

        evento = {
            "summary": titulo,
            "description": descricao,
            "start": {"dateTime": inicio_dt.isoformat(), "timeZone": TIMEZONE},
            "end": {"dateTime": fim_dt.isoformat(), "timeZone": TIMEZONE},
        }

        resultado = servico.events().insert(calendarId="primary", body=evento).execute()
        link = resultado.get("htmlLink", "")
        return f"Evento '{titulo}' criado para {inicio_dt.strftime('%d/%m/%Y às %H:%M')}. Link: {link}"
    except FileNotFoundError as e:
        return str(e)
    except Exception as e:
        return f"Erro ao criar evento no calendário: {e}"


def listar_eventos_calendario(dias: int = 7):
    """Lista os próximos eventos do calendário principal, dentro do número de dias indicado."""
    try:
        servico = _obter_servico()

        agora = datetime.datetime.utcnow().isoformat() + "Z"
        limite = (datetime.datetime.utcnow() + datetime.timedelta(days=dias)).isoformat() + "Z"

        resultado = servico.events().list(
            calendarId="primary",
            timeMin=agora,
            timeMax=limite,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        eventos = resultado.get("items", [])
        if not eventos:
            return f"Não há eventos marcados nos próximos {dias} dias."

        linhas = []
        for evento in eventos:
            inicio = evento["start"].get("dateTime", evento["start"].get("date"))
            linhas.append(f"- {evento.get('summary', '(sem título)')} em {inicio}")

        return "\n".join(linhas)
    except FileNotFoundError as e:
        return str(e)
    except Exception as e:
        return f"Erro ao listar eventos do calendário: {e}"

"""
Integração com o Gmail para o MAX.
Usa a autenticação partilhada (google_auth.py) e expõe funções simples
para ler os emails mais recentes e enviar novos emails.
"""

import base64
from email.mime.text import MIMEText

from googleapiclient.discovery import build
from google_auth import obter_credenciais

_servico_gmail = None


def _obter_servico():
    global _servico_gmail
    if _servico_gmail is None:
        creds = obter_credenciais()
        _servico_gmail = build("gmail", "v1", credentials=creds)
    return _servico_gmail


def listar_emails_recentes(quantidade: int = 5, apenas_nao_lidos: bool = False):
    """
    Lista os emails mais recentes da caixa de entrada.

    quantidade: número de emails a devolver (por defeito 5)
    apenas_nao_lidos: se True, mostra só os não lidos
    """
    try:
        servico = _obter_servico()

        query = "is:unread" if apenas_nao_lidos else ""
        resultado = servico.users().messages().list(
            userId="me", labelIds=["INBOX"], q=query, maxResults=quantidade
        ).execute()

        mensagens = resultado.get("messages", [])
        if not mensagens:
            return "Não há emails novos." if apenas_nao_lidos else "A caixa de entrada está vazia."

        linhas = []
        for msg_ref in mensagens:
            msg = servico.users().messages().get(
                userId="me", id=msg_ref["id"], format="metadata",
                metadataHeaders=["From", "Subject"],
            ).execute()

            headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
            remetente = headers.get("From", "(desconhecido)")
            assunto = headers.get("Subject", "(sem assunto)")
            snippet = msg.get("snippet", "")

            linhas.append(f"De: {remetente}\nAssunto: {assunto}\nPrévia: {snippet}\n")

        return "\n".join(linhas)
    except FileNotFoundError as e:
        return str(e)
    except Exception as e:
        return f"Erro ao ler emails: {e}"


def enviar_email(destinatario: str, assunto: str, corpo: str):
    """
    Envia um email a partir da conta autenticada.

    destinatario: endereço de email de destino
    assunto: assunto do email
    corpo: texto do email
    """
    try:
        servico = _obter_servico()

        mensagem = MIMEText(corpo)
        mensagem["to"] = destinatario
        mensagem["subject"] = assunto

        corpo_codificado = base64.urlsafe_b64encode(mensagem.as_bytes()).decode()

        servico.users().messages().send(
            userId="me", body={"raw": corpo_codificado}
        ).execute()

        return f"Email enviado para {destinatario} com o assunto '{assunto}'."
    except FileNotFoundError as e:
        return str(e)
    except Exception as e:
        return f"Erro ao enviar email: {e}"

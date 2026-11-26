"""
Autenticação OAuth partilhada com a Google, usada tanto pelo Calendar
como pelo Gmail. Um único login autoriza os dois.

Requisitos:
    pip install google-auth google-auth-oauthlib google-api-python-client

Precisas de um ficheiro 'credentials.json' (das credenciais OAuth do Google
Cloud) na mesma pasta. Ver instruções completas na conversa.

IMPORTANTE: se já tinhas usado só o Calendar antes e agora estás a
adicionar o Gmail, APAGA o ficheiro 'token.json' antigo antes de correres
o MAX outra vez — o token antigo só tem autorização para o Calendar, e
tens de voltar a autorizar (uma vez) para incluíres também o Gmail.
"""

import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Todos os âmbitos de que o MAX precisa, de uma vez só.
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

CREDENTIALS_PATH = "credentials.json"
TOKEN_PATH = "token.json"

_credenciais_cache = None


def obter_credenciais():
    """Autentica (ou reutiliza o token guardado) e devolve as credenciais Google."""
    global _credenciais_cache
    if _credenciais_cache is not None and _credenciais_cache.valid:
        return _credenciais_cache

    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_PATH):
                raise FileNotFoundError(
                    f"Não encontrei '{CREDENTIALS_PATH}'. Segue as instruções "
                    "para criar as credenciais OAuth no Google Cloud e coloca "
                    "o ficheiro nesta pasta."
                )
            # Isto abre o browser (uma vez) para autorizares o acesso.
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_PATH, "w", encoding="utf-8") as token_file:
            token_file.write(creds.to_json())

    _credenciais_cache = creds
    return creds

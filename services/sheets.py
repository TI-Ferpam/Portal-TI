import re
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

ID_PLANILHA = "13Fu87VrDiC0NZuQw6zIphbvVkKfle6wEZ98vSjcdl2E"
ABA_AUDITORIA = "auditoria_admin"
HEADERS_AUDITORIA = [
    "timestamp",
    "usuario_admin",
    "evento",
    "ticket",
    "detalhes",
    "sessao",
]


@st.cache_resource(show_spinner=False)
def conectar_google_sheets():
    """Reutiliza o cliente gspread entre reruns para evitar reautenticação desnecessária."""
    creds_dict = dict(st.secrets["gcp_service_account"])

    if "private_key" in creds_dict:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=SCOPES,
    )
    return gspread.authorize(creds)


@st.cache_resource(show_spinner=False)
def _abrir_planilha():
    """Reutiliza o objeto Spreadsheet; as leituras das abas continuam controladas por cache_data."""
    client = conectar_google_sheets()
    return client.open_by_key(ID_PLANILHA)


def carregar_aba(nome_aba):
    """Carrega uma aba da planilha pelo nome e devolve um DataFrame."""
    planilha = _abrir_planilha()
    aba = planilha.worksheet(nome_aba)
    dados_brutos = aba.get_all_values()

    if not dados_brutos:
        return pd.DataFrame()

    headers = dados_brutos[0]
    linhas = dados_brutos[1:]
    return pd.DataFrame(linhas, columns=headers)


@st.cache_data(ttl=60, show_spinner=False)
def carregar_chamados():
    try:
        return carregar_aba("chamados")
    except Exception as e:
        st.error(f"Erro ao acessar a aba 'chamados' no Google Sheets: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=60, show_spinner=False)
def carregar_terceiros():
    try:
        return carregar_aba("terceiros")
    except Exception as e:
        st.error(f"Erro ao acessar a aba 'terceiros' no Google Sheets: {e}")
        return pd.DataFrame()


def _limpar_campo_auditoria(valor, limite):
    """Remove quebras de linha/controles e limita o tamanho antes de gravar."""
    texto = str(valor or "")
    texto = texto.replace("\x00", " ")
    texto = re.sub(r"[\r\n\t]+", " ", texto)
    texto = re.sub(r"\s{2,}", " ", texto).strip()
    return texto[:limite]


def _obter_ou_criar_aba_auditoria():
    """Obtém a aba de auditoria; cria com cabeçalho no primeiro uso."""
    planilha = _abrir_planilha()
    try:
        return planilha.worksheet(ABA_AUDITORIA)
    except gspread.WorksheetNotFound:
        try:
            aba = planilha.add_worksheet(
                title=ABA_AUDITORIA,
                rows=2000,
                cols=len(HEADERS_AUDITORIA),
            )
            aba.append_row(HEADERS_AUDITORIA, value_input_option="RAW")
            return aba
        except Exception:
            # Em caso de duas sessões tentarem criar ao mesmo tempo,
            # tenta novamente abrir a aba antes de propagar o erro.
            return planilha.worksheet(ABA_AUDITORIA)


def registrar_auditoria(usuario_admin, evento, ticket="", detalhes="", sessao=""):
    """
    Grava uma ação administrativa relevante.

    Nunca recebe ou grava senhas/tokens. O chamador deve enviar somente
    metadados operacionais curtos.
    """
    try:
        aba = _obter_ou_criar_aba_auditoria()
        agora = datetime.now(ZoneInfo("America/Araguaina")).isoformat(timespec="seconds")
        linha = [
            agora,
            _limpar_campo_auditoria(usuario_admin, 100),
            _limpar_campo_auditoria(evento, 80),
            _limpar_campo_auditoria(ticket, 80),
            _limpar_campo_auditoria(detalhes, 500),
            _limpar_campo_auditoria(sessao, 80),
        ]
        aba.append_row(linha, value_input_option="RAW")
        try:
            carregar_auditoria.clear()
        except Exception:
            pass
        return True
    except Exception:
        # Auditoria não pode derrubar o portal. A tela de auditoria continuará
        # informando ausência de registros caso a gravação falhe.
        return False


@st.cache_data(ttl=60, show_spinner=False)
def carregar_auditoria():
    """Carrega os registros de auditoria. Se a aba ainda não existir, retorna vazio."""
    try:
        planilha = _abrir_planilha()
        try:
            aba = planilha.worksheet(ABA_AUDITORIA)
        except gspread.WorksheetNotFound:
            return pd.DataFrame(columns=HEADERS_AUDITORIA)

        dados = aba.get_all_values()
        if not dados:
            return pd.DataFrame(columns=HEADERS_AUDITORIA)

        headers = dados[0]
        linhas = dados[1:]
        return pd.DataFrame(linhas, columns=headers)
    except Exception:
        return pd.DataFrame(columns=HEADERS_AUDITORIA)

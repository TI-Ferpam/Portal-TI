import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

ID_PLANILHA = "13Fu87VrDiC0NZuQw6zIphbvVkKfle6wEZ98vSjcdl2E"


def conectar_google_sheets():
    # Busca as credenciais do cofre secreto do Streamlit
    creds_dict = dict(st.secrets["gcp_service_account"])

    # Trata quebras de linha da private_key
    if "private_key" in creds_dict:
        creds_dict["private_key"] = creds_dict["private_key"].replace(
            "\\n",
            "\n"
        )

    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=SCOPES
    )

    client = gspread.authorize(creds)
    return client


def carregar_aba(nome_aba):
    """
    Carrega uma aba da planilha pelo nome e devolve um DataFrame.
    """
    client = conectar_google_sheets()

    planilha = client.open_by_key(ID_PLANILHA)
    aba = planilha.worksheet(nome_aba)

    dados_brutos = aba.get_all_values()

    if not dados_brutos:
        return pd.DataFrame()

    headers = dados_brutos[0]
    linhas = dados_brutos[1:]

    return pd.DataFrame(linhas, columns=headers)


@st.cache_data(ttl=60)
def carregar_chamados():
    try:
        return carregar_aba("chamados")

    except Exception as e:
        st.error(
            f"Erro ao acessar a aba 'chamados' no Google Sheets: {e}"
        )
        return pd.DataFrame()


@st.cache_data(ttl=60)
def carregar_terceiros():
    try:
        return carregar_aba("terceiros")

    except Exception as e:
        st.error(
            f"Erro ao acessar a aba 'terceiros' no Google Sheets: {e}"
        )
        return pd.DataFrame()

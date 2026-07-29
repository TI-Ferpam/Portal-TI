import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def conectar_google_sheets():
    # Busca as credenciais do cofre secreto do Streamlit
    creds_dict = dict(st.secrets["gcp_service_account"])

    # Trata quebras de linha da private_key
    if "private_key" in creds_dict:
        creds_dict["private_key"] = creds_dict["private_key"].replace(
            "\\n", "\n"
        )

    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client


@st.cache_data(ttl=60)
def carregar_chamados():
    try:
        client = conectar_google_sheets()
        
        # Abre a planilha pelo ID e seleciona especificamente a aba 'chamados'
        planilha = client.open_by_key(
            "13Fu87VrDiC0NZuQw6zIphbvVkKfle6wEZ98vSjcdl2E"
        ).worksheet("chamados")

        # Obtém todos os dados da aba em formato matriz (lista de listas)
        dados_brutos = planilha.get_all_values()

        if not dados_brutos:
            return pd.DataFrame()

        # Extrai a primeira linha como cabeçalho e o restante como dados
        headers = dados_brutos[0]
        linhas = dados_brutos[1:]

        # Cria o DataFrame usando as linhas e cabeçalhos
        df = pd.DataFrame(linhas, columns=headers)

        return df

    except Exception as e:
        st.error(f"Erro ao acessar a aba 'chamados' no Google Sheets: {e}")
        return pd.DataFrame()

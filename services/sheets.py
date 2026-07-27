import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def conectar_google_sheets():
    # O Python busca as credenciais diretamente do cofre secreto (Secrets) do Streamlit Cloud
    creds_dict = dict(st.secrets["gcp_service_account"])
    
    # Trata as quebras de linha da chave privada para não dar erro no Linux
    if "private_key" in creds_dict:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client

@st.cache_data(ttl=60)
def carregar_chamados():
    client = conectar_google_sheets()
    # Substitua pelo nome ou ID exato da sua planilha no Google Drive
    planilha = client.open_by_key("13Fu87VrDiC0NZuQw6zIphbvVkKfle6wEZ98vSjcdl2E").sheet1
    dados = planilha.get_all_records()
    return pd.DataFrame(dados)

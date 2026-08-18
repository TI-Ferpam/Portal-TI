import os
import re
import html
import hmac
import unicodedata
import uuid
import io
import math
import struct
import wave
from difflib import SequenceMatcher

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
from services.sheets import carregar_chamados

# Se o seu services.sheets já possuir uma função específica para a aba
# "terceiros", o dashboard também sabe aproveitá-la. Se não possuir,
# ele tenta obter a aba pelo retorno em dict de carregar_chamados().
try:
    from services.sheets import carregar_terceiros
except ImportError:
    carregar_terceiros = None

try:
    from services.sheets import carregar_auditoria, registrar_auditoria
except ImportError:
    carregar_auditoria = None
    registrar_auditoria = None

# ============================================================
# CONFIGURAÇÃO DA PÁGINA
# ============================================================

st.set_page_config(
    page_title="Portal de Chamados TI",
    page_icon="🎫",
    layout="wide",
    initial_sidebar_state="expanded",
)

LIMITE_ROADMAP_MINUTOS = 6 * 24 * 60  

MESES_DIC = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
}

# ============================================================
# FUNÇÃO AUXILIAR DE FORMATAÇÃO DE TEMPO
# ============================================================

def formatar_tempo(minutos):
    if pd.isna(minutos) or minutos is None or minutos < 0:
        return "N/A"
    minutos = int(round(minutos))
    dias = minutos // (24 * 60)
    horas = (minutos % (24 * 60)) // 60
    mins = minutos % 60
    
    if dias > 0:
        return f"{dias}d {horas}h {mins}m"
    elif horas > 0:
        return f"{horas}h {mins:02d}m"
    else:
        return f"{mins} min"

# ============================================================
# CARREGAMENTO E TRATAMENTO DE DADOS (CORRIGIDO)
# ============================================================

@st.cache_data(ttl=60, show_spinner=False)
def carregar_origem_planilha():
    """Evita buscar a mesma planilha duas vezes para chamados e terceiros."""
    return carregar_chamados()


@st.cache_data(ttl=60, show_spinner=False)
def carregar_dados():
    colunas_obrigatorias = [
        "id_chamado", "solicitante", "titulo", "ocorrencia", "status",
        "prioridade", "departamento", "tecnico", "cidade",
        "atividade_realizada", "nota_atendimento", "data_avaliacao", "comentario_avaliacao",
        "data_hora_abertura", "data_inicial", "data_tecnico", "data_conclusao", "data_final"
    ]

    try:
        data = carregar_origem_planilha()
        if isinstance(data, dict):
            df_raw = data.get("chamados", list(data.values())[0]).copy()
        elif isinstance(data, pd.DataFrame):
            df_raw = data.copy()
        else:
            df_raw = pd.DataFrame(data)

        if df_raw.empty:
            df_empty = pd.DataFrame(columns=colunas_obrigatorias)
            df_empty["nota_num"] = pd.Series(dtype=float)
            df_empty["sla_valido"] = pd.Series(dtype=bool)
            df_empty["eh_roadmap"] = pd.Series(dtype=bool)
            df_empty["tem_3_datas"] = pd.Series(dtype=bool)
            df_empty["ano_abertura"] = pd.Series(dtype=float)
            df_empty["mes_num_abertura"] = pd.Series(dtype=float)
            df_empty["mes_nome_abertura"] = pd.Series(dtype=str)
            df_empty["dt_aval_parsed"] = pd.Series(dtype="datetime64[ns]")
            return df_empty

        # Normalizar nomes de colunas
        df_raw.columns = [str(col).strip().lower() for col in df_raw.columns]
        df_raw = df_raw.loc[:, df_raw.columns != ""]
        df_raw = df_raw.loc[:, ~df_raw.columns.duplicated()]

        # Mapeamento estendido para evitar perda de colunas da planilha
        mapeamento_colunas = {
            "id": "id_chamado", "ticket": "id_chamado", "n_chamado": "id_chamado", "chamado": "id_chamado",
            "numero": "id_chamado", "num_chamado": "id_chamado", "protocolo": "id_chamado",
            "descricao": "ocorrencia", "detalhes": "ocorrencia", "problema": "ocorrencia",
            "solucao": "atividade_realizada", "resolucao": "atividade_realizada", "acao": "atividade_realizada",
            "nota": "nota_atendimento", "avaliacao": "nota_atendimento", "csat": "nota_atendimento",
            "nome": "solicitante", "usuario": "solicitante", "cliente": "solicitante",
            "assunto": "titulo", "resumo": "titulo", "nome_chamado": "titulo",
            "setor": "departamento", "area": "departamento",
            "analista": "tecnico", "atendente": "tecnico", "responsavel": "tecnico"
        }

        # Aplica o mapeamento apenas para colunas que realmente existem
        novos_nomes = {}
        for c in df_raw.columns:
            if c in mapeamento_colunas and mapeamento_colunas[c] not in df_raw.columns:
                novos_nomes[c] = mapeamento_colunas[c]
        df_raw = df_raw.rename(columns=novos_nomes)

        # Garante que todas as colunas obrigatórias existam
        for col in colunas_obrigatorias:
            if col not in df_raw.columns:
                df_raw[col] = ""

        # Limpeza genérica de textos
        for col in ["id_chamado", "solicitante", "titulo", "ocorrencia", "status", 
                    "prioridade", "departamento", "tecnico", "cidade", "atividade_realizada"]:
            df_raw[col] = df_raw[col].fillna("").astype(str).str.strip()
            df_raw[col] = df_raw[col].replace({"nan": "", "None": "", "null": "", "<NA>": ""})

        # Se id_chamado ficou vazio após limpeza, gera um ID baseado no índice da linha
        vazios_id = df_raw["id_chamado"] == ""
        if vazios_id.any():
            df_raw.loc[vazios_id, "id_chamado"] = [str(i + 1) for i in df_raw[vazios_id].index]

        # Se titulo ficou vazio, usa parte da ocorrência ou um padrão
        vazios_titulo = df_raw["titulo"] == ""
        if vazios_titulo.any():
            df_raw.loc[vazios_titulo, "titulo"] = df_raw.loc[vazios_titulo, "ocorrencia"].str[:40]
            df_raw.loc[df_raw["titulo"] == "", "titulo"] = "Chamado Sem Título"

        # Se status ficou vazio
        df_raw.loc[df_raw["status"] == "", "status"] = "Aberto"

        # Filtro de exclusão de técnico
        padrao_nunes = r"mat[h]?eus\s+nunes"
        df_raw = df_raw[~df_raw["tecnico"].str.contains(padrao_nunes, case=False, regex=True, na=False)]

        # Tratamento de Notas
        nota_limpa = df_raw["nota_atendimento"].astype(str).str.replace(",", ".", regex=False).str.strip()
        df_raw["nota_num"] = pd.to_numeric(nota_limpa, errors="coerce")

        # Tratamento de Datas
        df_raw["dt_abertura"] = pd.to_datetime(df_raw["data_hora_abertura"], errors="coerce", dayfirst=True).fillna(
            pd.to_datetime(df_raw["data_inicial"], errors="coerce", dayfirst=True)
        )
        df_raw["dt_tecnico"] = pd.to_datetime(df_raw["data_tecnico"], errors="coerce", dayfirst=True)
        df_raw["dt_conclusao_efetiva"] = pd.to_datetime(df_raw["data_conclusao"], errors="coerce", dayfirst=True).fillna(
            pd.to_datetime(df_raw["data_final"], errors="coerce", dayfirst=True)
        )
        
        df_raw["dt_aval_parsed"] = pd.to_datetime(df_raw["data_avaliacao"], errors="coerce", dayfirst=True).fillna(df_raw["dt_conclusao_efetiva"])

        df_raw["ano_abertura"] = df_raw["dt_abertura"].dt.year
        df_raw["mes_num_abertura"] = df_raw["dt_abertura"].dt.month
        df_raw["mes_nome_abertura"] = df_raw["mes_num_abertura"].map(MESES_DIC)

        df_raw["tem_3_datas"] = (
            df_raw["dt_abertura"].notna() & 
            df_raw["dt_tecnico"].notna() & 
            df_raw["dt_conclusao_efetiva"].notna()
        )

        df_raw["min_total"] = (df_raw["dt_conclusao_efetiva"] - df_raw["dt_abertura"]).dt.total_seconds() / 60.0
        df_raw["min_ate_tecnico"] = (df_raw["dt_tecnico"] - df_raw["dt_abertura"]).dt.total_seconds() / 60.0
        df_raw["min_resolucao"] = (df_raw["dt_conclusao_efetiva"] - df_raw["dt_tecnico"]).dt.total_seconds() / 60.0

        df_raw.loc[~df_raw["tem_3_datas"], ["min_ate_tecnico", "min_resolucao", "min_total"]] = None

        df_raw["sla_valido"] = (
            df_raw["tem_3_datas"] &
            (df_raw["min_total"] >= 0) &
            (df_raw["min_ate_tecnico"] >= 0) &
            (df_raw["min_resolucao"] >= 0)
        )

        df_raw["eh_roadmap"] = (df_raw["min_total"] > LIMITE_ROADMAP_MINUTOS)

        return df_raw

    except Exception as e:
        st.error(f"Erro ao carregar dados da planilha: {e}")
        df_err = pd.DataFrame(columns=colunas_obrigatorias)
        df_err["nota_num"] = pd.Series(dtype=float)
        df_err["sla_valido"] = pd.Series(dtype=bool)
        df_err["eh_roadmap"] = pd.Series(dtype=bool)
        df_err["tem_3_datas"] = pd.Series(dtype=bool)
        df_err["ano_abertura"] = pd.Series(dtype=float)
        df_err["mes_num_abertura"] = pd.Series(dtype=float)
        df_err["mes_nome_abertura"] = pd.Series(dtype=str)
        df_err["dt_aval_parsed"] = pd.Series(dtype="datetime64[ns]")
        return df_err

df = carregar_dados()


@st.cache_data(ttl=60, show_spinner=False)
def carregar_dados_terceiros():
    """
    Carrega a aba/tabela de terceiros.

    Otimização: quando services.sheets possui carregar_terceiros(), usa essa
    função diretamente em vez de consultar primeiro a origem de chamados.
    """
    colunas = [
        "id_terceiro", "id_chamado", "data_solicitação", "ultima_atualizacao",
        "nome_terceiro", "link", "id_ticket", "roadmap", "requisito"
    ]

    try:
        df_t = pd.DataFrame()

        if carregar_terceiros is not None:
            valor = carregar_terceiros()
            if isinstance(valor, dict):
                valor = valor.get(
                    "terceiros",
                    list(valor.values())[0] if valor else [],
                )
            df_t = valor.copy() if isinstance(valor, pd.DataFrame) else pd.DataFrame(valor)
        else:
            origem = carregar_origem_planilha()
            if isinstance(origem, dict):
                for chave in ["terceiros", "Terceiros", "TERCEIROS"]:
                    if chave in origem:
                        valor = origem[chave]
                        df_t = valor.copy() if isinstance(valor, pd.DataFrame) else pd.DataFrame(valor)
                        break

        if df_t.empty:
            return pd.DataFrame(columns=colunas)

        df_t.columns = [str(c).strip().lower() for c in df_t.columns]
        df_t = df_t.loc[:, df_t.columns != ""]
        df_t = df_t.loc[:, ~df_t.columns.duplicated()]

        mapa = {
            "terceiro": "nome_terceiro",
            "empresa": "nome_terceiro",
            "url": "link",
            "link_chamado": "link",
            "ticket": "id_ticket",
            "ticket_terceiro": "id_ticket",
            "id_appsheet": "id_chamado",
        }
        novos_nomes = {}
        for c in df_t.columns:
            if c in mapa and mapa[c] not in df_t.columns:
                novos_nomes[c] = mapa[c]
        df_t = df_t.rename(columns=novos_nomes)

        for col in colunas:
            if col not in df_t.columns:
                df_t[col] = ""

        for col in ["id_terceiro", "id_chamado", "nome_terceiro", "link", "id_ticket"]:
            df_t[col] = df_t[col].fillna("").astype(str).str.strip()
            df_t[col] = df_t[col].replace({"nan": "", "None": "", "null": "", "<NA>": ""})

        return df_t

    except Exception:
        return pd.DataFrame(columns=colunas)


df_terceiros = carregar_dados_terceiros()

# ============================================================
# CLASSIFICAÇÃO DE STATUS
# ============================================================

def classificar_status_grupo(status_str):
    if not status_str or str(status_str).strip() == "" or str(status_str).strip().lower() == "nan":
        return "Abertos"
    s = str(status_str).strip().casefold()
    concluidos_kw = ["concluído", "concluido", "finalizado", "fechado", "resolvido", "encerrado", "cancelado"]
    andamento_kw = ["em andamento", "em atendimento", "atendendo", "execução", "execucao", "iniciado", "aguardando", "terceiro", "solicitante"]

    if any(kw in s for kw in concluidos_kw):
        return "Concluídos"
    elif any(kw in s for kw in andamento_kw):
        return "Em Andamento"
    else:
        return "Abertos"

# ============================================================
# ESTADOS DA SESSÃO E AUXILIARES
# ============================================================

for key, val in [
    ("tela", "busca"), 
    ("ticket_aberto", None), 
    ("autenticado_admin", False),
    ("admin_usuario", ""),
    ("sessao_auditoria", ""),
    ("filtro_dash_tipo", None), 
    ("filtro_dash_valor", None),
    ("tecnico_sla_selecionado", None),
    ("central_terceiros_live", []),
]:
    if key not in st.session_state:
        st.session_state[key] = val

if not st.session_state.sessao_auditoria:
    st.session_state.sessao_auditoria = uuid.uuid4().hex[:16]


def registrar_auditoria_seguro(evento, ticket="", detalhes="", usuario=None):
    """Registra auditoria sem permitir que falhas de log derrubem o portal."""
    if registrar_auditoria is None:
        return False

    usuario_final = str(
        usuario if usuario is not None else st.session_state.get("admin_usuario", "admin")
    ).strip() or "admin"

    try:
        return bool(registrar_auditoria(
            usuario_admin=usuario_final,
            evento=str(evento or "")[:80],
            ticket=str(ticket or "")[:80],
            detalhes=str(detalhes or "")[:500],
            sessao=str(st.session_state.get("sessao_auditoria", ""))[:80],
        ))
    except Exception:
        return False


def abrir_ticket(ticket_id):
    ticket_limpo = str(ticket_id).strip()
    if st.session_state.get("autenticado_admin"):
        registrar_auditoria_seguro("ABRIR_TICKET_ADMIN", ticket=ticket_limpo)
    st.session_state.ticket_aberto = ticket_limpo
    st.session_state.tela = "ticket"

def voltar_busca():
    st.session_state.ticket_aberto = None
    st.session_state.tela = "busca"

def limpar_filtro_dash():
    st.session_state.filtro_dash_tipo = None
    st.session_state.filtro_dash_valor = None

lista_solicitantes_admin = sorted(list(set([s for s in df["solicitante"].unique() if s and s.casefold() != "nan"])), key=str.casefold)
lista_status_opcoes = ["Todos os Status"] + sorted(list(set([s for s in df["status"].unique() if s and s.casefold() != "nan"])), key=str.casefold)

AZUL_FERPAM = "#003399"
AZUL_FERPAM_HOVER = "#002266"

st.markdown(f"""
<style>
    header[data-testid="stHeader"] {{ background-color: transparent !important; }}
    footer {{ visibility: hidden; }}
    .stButton > button[data-testid="stBaseButton-primary"], button[kind="primary"] {{
        background-color: {AZUL_FERPAM} !important; border: 1px solid {AZUL_FERPAM} !important; color: #ffffff !important; border-radius: 8px !important; font-weight: 700 !important;
    }}
    .stButton > button[data-testid="stBaseButton-primary"]:hover, button[kind="primary"]:hover {{
        background-color: {AZUL_FERPAM_HOVER} !important; border-color: {AZUL_FERPAM_HOVER} !important;
    }}
    
    div[data-testid="stMetric"] {{ 
        border: 1px solid #334155 !important; 
        border-radius: 12px !important; 
        padding: 16px !important; 
        background-color: #1e293b !important;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); 
    }}
    div[data-testid="stMetric"] label, div[data-testid="stMetric"] [data-testid="stMetricLabel"] {{
        color: #94a3b8 !important;
    }}
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {{
        color: #f8fafc !important;
    }}
    
    button[data-baseweb="tab"] {{
        color: #e2e8f0 !important;
    }}
    button[data-baseweb="tab"][aria-selected="true"] {{
        background-color: #003399 !important;
        color: #ffffff !important;
        border-radius: 6px !important;
    }}


    /* ============================================================
       PAINEL ADMINISTRATIVO DO TICKET
       ============================================================ */
    .admin-summary-head {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 12px;
    }}

    .admin-summary-kicker {{
        color: #94a3b8;
        font-size: 0.78rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: .08em;
    }}

    .admin-summary-title {{
        color: #f8fafc;
        font-size: 1.08rem;
        font-weight: 800;
        margin-top: 2px;
    }}

    .admin-summary-ticket {{
        color: #93c5fd;
        background: rgba(37, 99, 235, .10);
        border: 1px solid rgba(59, 130, 246, .22);
        padding: 5px 10px;
        border-radius: 999px;
        font-size: .78rem;
        font-weight: 800;
        white-space: nowrap;
    }}

    .admin-summary-grid {{
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: 10px;
        margin: 10px 0 12px 0;
    }}

    .admin-summary-cell {{
        border: 1px solid rgba(148, 163, 184, .16);
        background: rgba(15, 23, 42, .42);
        border-radius: 12px;
        padding: 11px 12px;
        min-height: 68px;
    }}

    .admin-summary-label {{
        color: #94a3b8;
        font-size: .72rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: .06em;
        margin-bottom: 5px;
    }}

    .admin-summary-value {{
        color: #f8fafc;
        font-size: .94rem;
        font-weight: 750;
        line-height: 1.25;
        overflow-wrap: anywhere;
    }}

    .admin-summary-context {{
        border-top: 1px solid rgba(148, 163, 184, .14);
        margin-top: 4px;
        padding-top: 12px;
    }}

    .admin-summary-context-title {{
        color: #e2e8f0;
        font-size: .80rem;
        font-weight: 800;
        margin-bottom: 4px;
    }}

    .admin-summary-context-text {{
        color: #cbd5e1;
        font-size: .88rem;
        line-height: 1.48;
        overflow-wrap: anywhere;
    }}

    .admin-next-action {{
        border-radius: 12px;
        padding: 12px 14px;
        margin-top: 12px;
        border: 1px solid rgba(148, 163, 184, .16);
    }}

    .admin-next-action strong {{
        display: block;
        margin-bottom: 3px;
        color: #f8fafc;
    }}

    .admin-next-action span {{
        color: #cbd5e1;
        font-size: .88rem;
        line-height: 1.45;
    }}

    .admin-action-attention {{
        background: rgba(245, 158, 11, .09);
        border-left: 4px solid #f59e0b;
    }}

    .admin-action-wait {{
        background: rgba(59, 130, 246, .08);
        border-left: 4px solid #3b82f6;
    }}

    .admin-action-ok {{
        background: rgba(16, 185, 129, .08);
        border-left: 4px solid #10b981;
    }}

    .admin-action-info {{
        background: rgba(100, 116, 139, .08);
        border-left: 4px solid #64748b;
    }}

    .timeline-entry {{
        display: grid;
        grid-template-columns: 18px minmax(0, 1fr);
        gap: 10px;
        position: relative;
        padding-bottom: 12px;
    }}

    .timeline-entry:last-child {{
        padding-bottom: 0;
    }}

    .timeline-axis {{
        position: relative;
        display: flex;
        justify-content: center;
    }}

    .timeline-axis::after {{
        content: "";
        position: absolute;
        top: 17px;
        bottom: -13px;
        width: 2px;
        background: rgba(148, 163, 184, .18);
    }}

    .timeline-entry:last-child .timeline-axis::after {{
        display: none;
    }}

    .timeline-dot {{
        width: 10px;
        height: 10px;
        margin-top: 7px;
        border-radius: 50%;
        box-shadow: 0 0 0 4px rgba(148, 163, 184, .08);
        z-index: 1;
    }}

    .timeline-dot-ferpam {{
        background: #10b981;
    }}

    .timeline-dot-citel {{
        background: #3b82f6;
    }}

    .timeline-dot-user {{
        background: #f59e0b;
    }}

    .timeline-dot-third {{
        background: #a78bfa;
    }}

    .timeline-card {{
        background: rgba(15, 23, 42, .30);
        border: 1px solid rgba(148, 163, 184, .14);
        border-radius: 12px;
        padding: 10px 12px;
    }}

    .timeline-top {{
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 12px;
    }}

    .timeline-title {{
        color: #f8fafc;
        font-size: .91rem;
        font-weight: 800;
        line-height: 1.35;
    }}

    .timeline-date {{
        color: #94a3b8;
        font-size: .76rem;
        white-space: nowrap;
        margin-top: 1px;
    }}

    .timeline-origin {{
        display: inline-block;
        margin-top: 5px;
        padding: 2px 7px;
        border-radius: 999px;
        background: rgba(148, 163, 184, .09);
        color: #cbd5e1;
        font-size: .70rem;
        font-weight: 700;
    }}

    .timeline-description {{
        color: #cbd5e1;
        font-size: .84rem;
        line-height: 1.46;
        margin-top: 8px;
        overflow-wrap: anywhere;
    }}

    @media (max-width: 900px) {{
        .admin-summary-grid {{
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }}

        .timeline-top {{
            display: block;
        }}

        .timeline-date {{
            margin-top: 4px;
        }}
    }}



    /* ============================================================
       MODO TV
       ============================================================ */
    .tv-header {{
        display: flex;
        justify-content: space-between;
        align-items: flex-end;
        gap: 20px;
        margin-bottom: 16px;
    }}

    .tv-eyebrow {{
        color: #60a5fa;
        font-size: .78rem;
        font-weight: 800;
        letter-spacing: .10em;
        text-transform: uppercase;
        margin-bottom: 3px;
    }}

    .tv-title {{
        color: #f8fafc;
        font-size: 2rem;
        font-weight: 900;
        line-height: 1.05;
        letter-spacing: -.03em;
    }}

    .tv-clock {{
        color: #cbd5e1;
        font-size: .88rem;
        text-align: right;
        white-space: nowrap;
    }}

    .tv-kpi-grid {{
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 12px;
        margin: 8px 0 16px 0;
    }}

    .tv-kpi {{
        background: linear-gradient(180deg, rgba(30,41,59,.92), rgba(15,23,42,.88));
        border: 1px solid rgba(148,163,184,.16);
        border-radius: 15px;
        padding: 14px 16px;
        min-height: 96px;
        box-shadow: 0 10px 28px rgba(0,0,0,.10);
    }}

    .tv-kpi-label {{
        color: #94a3b8;
        font-size: .73rem;
        font-weight: 800;
        text-transform: uppercase;
        letter-spacing: .07em;
    }}

    .tv-kpi-value {{
        color: #f8fafc;
        font-size: 2rem;
        line-height: 1;
        font-weight: 900;
        margin-top: 9px;
    }}

    .tv-kpi-sub {{
        color: #94a3b8;
        font-size: .74rem;
        margin-top: 6px;
    }}

    .tv-section-title {{
        color: #f8fafc;
        font-size: 1.02rem;
        font-weight: 850;
        margin-bottom: 9px;
    }}

    .tv-alert {{
        border: 1px solid rgba(148,163,184,.14);
        border-radius: 12px;
        padding: 10px 12px;
        margin-bottom: 8px;
        background: rgba(15,23,42,.52);
    }}

    .tv-alert-new {{
        border-left: 4px solid #10b981;
        background: rgba(16,185,129,.07);
    }}

    .tv-alert-citel {{
        border-left: 4px solid #3b82f6;
        background: rgba(59,130,246,.07);
    }}

    .tv-alert-warning {{
        border-left: 4px solid #f59e0b;
        background: rgba(245,158,11,.07);
    }}

    .tv-alert-critical {{
        border-left: 4px solid #ef4444;
        background: rgba(239,68,68,.07);
    }}

    .tv-alert-title {{
        color: #f8fafc;
        font-size: .89rem;
        font-weight: 800;
        line-height: 1.35;
    }}

    .tv-alert-body {{
        color: #cbd5e1;
        font-size: .78rem;
        line-height: 1.42;
        margin-top: 3px;
    }}

    .tv-alert-meta {{
        color: #94a3b8;
        font-size: .69rem;
        margin-top: 5px;
    }}

    .tv-empty {{
        color: #94a3b8;
        font-size: .82rem;
        border: 1px dashed rgba(148,163,184,.20);
        border-radius: 12px;
        padding: 18px;
        text-align: center;
    }}

    .tv-live-pill {{
        display: inline-flex;
        align-items: center;
        gap: 7px;
        color: #86efac;
        background: rgba(34,197,94,.08);
        border: 1px solid rgba(34,197,94,.20);
        padding: 4px 9px;
        border-radius: 999px;
        font-size: .70rem;
        font-weight: 800;
    }}

    .tv-dot-live {{
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: #22c55e;
        box-shadow: 0 0 0 4px rgba(34,197,94,.10);
    }}

    .tv-auto-on {{
        color: #86efac;
    }}

    .tv-auto-off {{
        color: #fbbf24;
    }}

    @media (max-width: 1050px) {{
        .tv-kpi-grid {{
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }}

        .tv-title {{
            font-size: 1.55rem;
        }}
    }}

</style>
""", unsafe_allow_html=True)

# ============================================================
# MENU LATERAL & AUTENTICAÇÃO
# ============================================================

st.sidebar.image("https://cdn-icons-png.flaticon.com/512/1063/1063376.png", width=50)
st.sidebar.title("Portal TI")
st.sidebar.markdown("### 🔐 Autenticação Admin")

if not st.session_state.autenticado_admin:
    with st.sidebar.expander("🔑 Áreas Restritas (Técnicos/Admin)", expanded=False):
        usuario_login = st.text_input("Usuário", key="login_usr")
        senha_login = st.text_input("Senha", type="password", key="login_pwd")

        try:
            admin_user_config = str(st.secrets.get("ADMIN_USER", "")).strip()
            admin_pass_config = str(st.secrets.get("ADMIN_PASSWORD", ""))
        except Exception:
            admin_user_config = ""
            admin_pass_config = ""

        if not admin_user_config or not admin_pass_config:
            st.caption("⚠️ Login administrativo ainda não configurado nos Secrets.")

        if st.button("Entrar", type="primary", use_container_width=True):
            configurado = bool(admin_user_config and admin_pass_config)
            usuario_ok = configurado and hmac.compare_digest(usuario_login.strip(), admin_user_config)
            senha_ok = configurado and hmac.compare_digest(str(senha_login), admin_pass_config)

            if usuario_ok and senha_ok:
                st.session_state.autenticado_admin = True
                st.session_state.admin_usuario = admin_user_config
                registrar_auditoria_seguro(
                    "LOGIN_ADMIN",
                    detalhes="Login administrativo realizado com sucesso.",
                    usuario=admin_user_config,
                )
                st.success("Login efetuado!")
                st.rerun()
            elif not configurado:
                st.error("Configure ADMIN_USER e ADMIN_PASSWORD nos Secrets do Streamlit.")
            else:
                st.error("Usuário ou senha incorretos.")
else:
    nome_admin_exibicao = st.session_state.get("admin_usuario") or "ADMIN"
    st.sidebar.success(f"⚡ Conectado como {nome_admin_exibicao}")
    if st.sidebar.button("🚪 Sair do Modo Admin", use_container_width=True):
        registrar_auditoria_seguro("LOGOUT_ADMIN", detalhes="Sessão administrativa encerrada.")
        st.session_state.autenticado_admin = False
        st.session_state.admin_usuario = ""
        st.session_state.tela = "busca"
        limpar_filtro_dash()
        st.rerun()

st.sidebar.divider()
opcoes_menu = ["🔍 Consultar Chamados"]
if st.session_state.autenticado_admin:
    opcoes_menu.extend([
        "📊 Dashboard de Indicadores",
        "📺 Modo TV",
    ])

if st.session_state.tela in ["busca", "ticket"]:
    indice_menu = 0
elif st.session_state.tela == "tv" and st.session_state.autenticado_admin:
    indice_menu = 2
else:
    indice_menu = 1 if st.session_state.autenticado_admin else 0

opcao_menu = st.sidebar.radio(
    "📍 Navegação",
    opcoes_menu,
    index=indice_menu,
)

if opcao_menu == "📊 Dashboard de Indicadores" and st.session_state.tela != "dashboard":
    registrar_auditoria_seguro(
        "ABRIR_DASHBOARD",
        detalhes="Acesso ao dashboard administrativo.",
    )
    st.session_state.tela = "dashboard"

elif opcao_menu == "📺 Modo TV" and st.session_state.tela != "tv":
    registrar_auditoria_seguro(
        "ABRIR_MODO_TV",
        detalhes="Modo TV administrativo iniciado.",
    )
    st.session_state.tela = "tv"

elif opcao_menu == "🔍 Consultar Chamados" and st.session_state.tela in ["dashboard", "tv"]:
    st.session_state.tela = "busca"

# ============================================================
# FUNÇÕES DE RENDERIZAÇÃO
# ============================================================

def calcular_progresso(chamado):
    grupo = classificar_status_grupo(chamado.get("status", ""))
    tecnico = str(chamado.get("tecnico", "")).strip().casefold()
    atividade = str(chamado.get("atividade_realizada", "")).strip().casefold()
    if grupo == "Concluídos": return 100, "🟢 Chamado Finalizado"
    elif grupo == "Em Andamento": return (80, "🔵 Em Atendimento (Atividade Registrada)") if atividade and atividade != "nan" else (60, "🔵 Em Atendimento / Aguardando")
    elif tecnico and tecnico not in ["nan", "não atribuído", "nao atribuido", ""]: return 35, "🟡 Técnico Atribuído (Aguardando Início)"
    else: return 15, "🟠 Chamado Aberto na Fila"

def get_status_badge(status):
    status_clean = str(status).strip()
    if not status_clean:
        status_clean = "Aberto"
    grupo = classificar_status_grupo(status_clean)
    color, bg, icon = ("#10b981", "rgba(16, 185, 129, 0.12)", "🟢") if grupo == "Concluídos" else ((AZUL_FERPAM, "rgba(0, 51, 153, 0.12)", "🔵") if grupo == "Em Andamento" else ("#d97706", "rgba(217, 119, 6, 0.12)", "🟡"))
    return f"""<span style="background-color: {bg}; color: {color}; font-weight: 700; font-size: 0.82rem; padding: 4px 12px; border-radius: 20px; border: 1px solid {color}44; display: inline-flex; align-items: center; gap: 6px;">{icon} {status_clean}</span>"""

def render_barra_progresso(pct, texto_estagio):
    bar_color = "#10b981" if pct == 100 else (AZUL_FERPAM if pct >= 50 else "#d97706")
    return f"""
    <div style="margin-top: 10px; margin-bottom: 6px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <span style="font-size: 0.83rem; font-weight: 600; color: #94a3b8;">{texto_estagio}</span>
            <span style="font-size: 0.85rem; font-weight: 800; color: {bar_color}; background-color: {bar_color}18; padding: 2px 10px; border-radius: 12px;">{pct}%</span>
        </div>
        <div style="width: 100%; background-color: #334155; height: 10px; border-radius: 6px; overflow: hidden;">
            <div style="width: {pct}%; background-color: {bar_color}; height: 100%; border-radius: 6px;"></div>
        </div>
    </div>
    """

def render_estrelas(nota):
    try:
        val = max(1, min(5, int(float(nota))))
        return "⭐" * val + "☆" * (5 - val) + f" ({val}/5)"
    except (ValueError, TypeError):
        return None

def extrair_valor_clicado(event):
    if not event or "selection" not in event: return None
    points = event["selection"].get("points", [])
    if not points: return None
    p = points[0]
    if "customdata" in p and p["customdata"]:
        val = p["customdata"]
        return str(val[0]).strip() if isinstance(val, list) else str(val).strip()
    if "label" in p and p["label"] is not None: return str(p["label"]).strip()
    if "y" in p and isinstance(p["y"], str) and p["y"]: return str(p["y"]).strip()
    if "x" in p and isinstance(p["x"], str) and p["x"]: return str(p["x"]).strip()
    return None

def processar_clique_grafico(event, tipo_filtro):
    val = extrair_valor_clicado(event)
    if val and (st.session_state.filtro_dash_tipo != tipo_filtro or st.session_state.filtro_dash_valor != val):
        st.session_state.filtro_dash_tipo = tipo_filtro
        st.session_state.filtro_dash_valor = val
        st.rerun()


# ============================================================
# INTEGRAÇÃO CITEL / ZENDESK
# ============================================================

CITEL_API_BASE = "https://citelsoftware.zendesk.com/api/v2"


def obter_config_secreta(nome, padrao=""):
    """
    Procura primeiro no st.secrets e depois em variável de ambiente.
    Assim nenhuma senha precisa ficar escrita no código.
    """
    try:
        valor = st.secrets.get(nome, None)
        if valor is not None:
            return str(valor).strip()
    except Exception:
        pass
    return str(os.getenv(nome, padrao) or "").strip()


def extrair_id_ticket_citel(link, id_ticket=""):
    link = str(link or "").strip()
    achou = re.search(r"/requests/(\d+)", link, flags=re.IGNORECASE)
    if achou:
        return achou.group(1)

    valor = str(id_ticket or "").strip()
    if not valor or valor.casefold() in ["nan", "none", "null", "<na>"]:
        return None

    # Planilhas às vezes entregam 1261995 como "1261995.0".
    achou_num = re.search(r"(\d+)", valor)
    return achou_num.group(1) if achou_num else None


def localizar_terceiros_do_chamado(chamado):
    """
    A planilha usa terceiros.id_chamado -> chamados.id_appsheet.
    Mantém fallback pelo id_chamado visível caso a origem mude no futuro.
    """
    if df_terceiros.empty:
        return df_terceiros.iloc[0:0].copy()

    id_appsheet = str(chamado.get("id_appsheet", "") or "").strip()
    id_visivel = str(chamado.get("id_chamado", "") or "").strip()

    ids_validos = {x.casefold() for x in [id_appsheet, id_visivel] if x}
    if not ids_validos:
        return df_terceiros.iloc[0:0].copy()

    serie_id = df_terceiros["id_chamado"].fillna("").astype(str).str.strip().str.casefold()
    return df_terceiros[serie_id.isin(ids_validos)].copy()


def _auth_citel():
    """
    Formas aceitas, em ordem de preferência:
      1) CITEL_OAUTH_TOKEN
      2) CITEL_EMAIL + CITEL_API_TOKEN
      3) CITEL_EMAIL + CITEL_PASSWORD (conta de usuário final do portal)

    Para conta de usuário final, o acesso por senha depende de a instância
    Zendesk da Citel permitir autenticação de API por senha.
    """
    oauth_token = obter_config_secreta("CITEL_OAUTH_TOKEN")
    api_token = obter_config_secreta("CITEL_API_TOKEN")
    email = obter_config_secreta("CITEL_EMAIL")
    senha = obter_config_secreta("CITEL_PASSWORD")

    headers = {
        "Accept": "application/json",
        "User-Agent": "Ferpam-Portal-TI/1.0",
    }

    if oauth_token:
        headers["Authorization"] = f"Bearer {oauth_token}"
        return headers, None, None

    # Suporte opcional a API token. OAuth continua sendo a primeira opção.
    if email and api_token:
        return headers, (f"{email}/token", api_token), None

    # Compatibilidade com a conta de usuário final que já está funcionando
    # no portal da Ferpam. A instância da Citel precisa permitir acesso por senha.
    if email and senha:
        return headers, (email, senha), None

    return headers, None, (
        "Integração Citel não configurada. Defina CITEL_OAUTH_TOKEN ou "
        "CITEL_EMAIL + CITEL_API_TOKEN/CITEL_PASSWORD nos secrets do Streamlit."
    )


def _ultimo_comentario_citel(ticket_id, role, headers, auth):
    url = f"{CITEL_API_BASE}/requests/{ticket_id}/comments"
    params = {
        "role": role,
        "sort_by": "created_at",
        "sort_order": "desc",
        "per_page": 1,
    }

    resposta = requests.get(
        url,
        headers=headers,
        auth=auth,
        params=params,
        timeout=8,
    )

    if resposta.status_code == 401:
        raise RuntimeError("Credenciais da Citel recusadas pela API.")
    if resposta.status_code == 403:
        raise RuntimeError("A conta configurada não possui acesso a este chamado da Citel.")
    if resposta.status_code == 404:
        raise RuntimeError("Chamado não encontrado no portal da Citel.")
    if resposta.status_code == 429:
        raise RuntimeError("A Citel limitou temporariamente as consultas automáticas.")
    if not resposta.ok:
        raise RuntimeError(f"API da Citel respondeu HTTP {resposta.status_code}.")

    dados = resposta.json()
    comentarios = dados.get("comments", [])
    return comentarios[0] if comentarios else None


def _comentario_citel_indica_roadmap(comentario):
    """
    Regra operacional da Ferpam:
    se a ÚLTIMA mensagem pública da própria Citel contém a palavra
    'roadmap' (aceitando também 'road map'), o chamado é tratado
    como ROADMAP e não como 'aguardando Citel/TI'.
    """
    if not isinstance(comentario, dict):
        return False

    texto = str(
        comentario.get("plain_body")
        or comentario.get("body")
        or ""
    ).strip().casefold()

    if not texto:
        return False

    return bool(re.search(r"\broad\s*map\b", texto, flags=re.IGNORECASE))


@st.cache_data(ttl=55, show_spinner=False)
def consultar_vez_resposta_citel(ticket_id):
    """
    Classifica o chamado externo em:
      - roadmap
      - aguardando_ti
      - aguardando_citel

    ROADMAP tem prioridade sobre a regra de "quem falou por último":
    se a última mensagem da Citel contém 'roadmap', o ticket fica
    separado e não gera alerta de resposta pendente.

    A função é somente leitura.
    """
    ticket_id = str(ticket_id or "").strip()

    if not ticket_id:
        return {
            "ok": False,
            "estado": "indisponivel",
            "erro": "ID do chamado da Citel não identificado.",
        }

    headers, auth, erro_config = _auth_citel()

    if erro_config:
        return {
            "ok": False,
            "estado": "nao_configurado",
            "erro": erro_config,
        }

    try:
        ultimo_agent = _ultimo_comentario_citel(
            ticket_id,
            "agent",
            headers,
            auth,
        )
        ultimo_usuario = _ultimo_comentario_citel(
            ticket_id,
            "end_user",
            headers,
            auth,
        )

        data_agent = pd.to_datetime(
            ultimo_agent.get("created_at")
            if ultimo_agent else None,
            errors="coerce",
            utc=True,
        )
        data_usuario = pd.to_datetime(
            ultimo_usuario.get("created_at")
            if ultimo_usuario else None,
            errors="coerce",
            utc=True,
        )

        tem_agent = pd.notna(data_agent)
        tem_usuario = pd.notna(data_usuario)

        datas_validas = [
            dt
            for dt in [data_agent, data_usuario]
            if pd.notna(dt)
        ]

        ultima_interacao = (
            max(datas_validas)
            if datas_validas
            else None
        )

        ultima_data_iso = (
            ultima_interacao.isoformat()
            if ultima_interacao is not None
            else None
        )

        data_agent_iso = (
            data_agent.isoformat()
            if tem_agent
            else None
        )

        data_usuario_iso = (
            data_usuario.isoformat()
            if tem_usuario
            else None
        )

        # A regra de ROADMAP olha especificamente a última mensagem
        # enviada pela própria Citel.
        if _comentario_citel_indica_roadmap(ultimo_agent):
            return {
                "ok": True,
                "estado": "roadmap",
                "titulo": "Em Roadmap",
                "descricao": (
                    "A última mensagem da Citel identifica este chamado "
                    "como Roadmap. Não há resposta operacional pendente."
                ),
                "ultima_data": ultima_data_iso,
                "ultima_data_citel": data_agent_iso,
                "ultima_data_ferpam": data_usuario_iso,
                "roadmap_detectado": True,
            }

        if tem_agent and (
            not tem_usuario
            or data_agent > data_usuario
        ):
            return {
                "ok": True,
                "estado": "aguardando_ti",
                "titulo": "Citel respondeu — aguardando TI",
                "descricao": (
                    "A Citel foi a última a responder neste chamado."
                ),
                "ultima_data": ultima_data_iso,
                "ultima_data_citel": data_agent_iso,
                "ultima_data_ferpam": data_usuario_iso,
                "roadmap_detectado": False,
            }

        if tem_usuario:
            return {
                "ok": True,
                "estado": "aguardando_citel",
                "titulo": "Aguardando resposta da Citel",
                "descricao": (
                    "A TI/Ferpam foi a última a responder neste chamado."
                ),
                "ultima_data": ultima_data_iso,
                "ultima_data_citel": data_agent_iso,
                "ultima_data_ferpam": data_usuario_iso,
                "roadmap_detectado": False,
            }

        return {
            "ok": False,
            "estado": "sem_comentarios",
            "erro": "Nenhum comentário público foi retornado pela Citel.",
        }

    except requests.RequestException:
        return {
            "ok": False,
            "estado": "indisponivel",
            "erro": "Não foi possível conectar ao portal da Citel.",
        }

    except Exception as e:
        return {
            "ok": False,
            "estado": "indisponivel",
            "erro": str(e),
        }


def formatar_data_citel(valor):
    dt = pd.to_datetime(valor, errors="coerce", utc=True)
    if pd.isna(dt):
        return None

    # Tocantins / Brasília: UTC-3.
    dt_local = dt.tz_convert("America/Araguaina")
    return dt_local.strftime("%d/%m/%Y às %H:%M")


def _validar_resposta_citel(resposta):
    """Converte respostas HTTP da Citel em erros controlados e sem vazar credenciais."""
    if resposta.status_code == 401:
        raise RuntimeError("Credenciais da Citel recusadas pela API.")
    if resposta.status_code == 403:
        raise RuntimeError("A conta configurada não possui acesso a este chamado da Citel.")
    if resposta.status_code == 404:
        raise RuntimeError("Chamado não encontrado no portal da Citel.")
    if resposta.status_code == 429:
        raise RuntimeError("A Citel limitou temporariamente as consultas automáticas.")
    if not resposta.ok:
        raise RuntimeError(f"API da Citel respondeu HTTP {resposta.status_code}.")



@st.cache_data(ttl=55, show_spinner=False)
def consultar_status_request_citel(ticket_id):
    """
    Consulta apenas o status do Request na Citel/Zendesk.
    Não altera o chamado externo.
    """
    ticket_id = str(ticket_id or "").strip()

    if not ticket_id or not ticket_id.isdigit():
        return {
            "ok": False,
            "status": "",
            "resolvido": False,
            "erro": "ID do chamado da Citel inválido.",
        }

    headers, auth, erro_config = _auth_citel()
    if erro_config:
        return {
            "ok": False,
            "status": "",
            "resolvido": False,
            "erro": erro_config,
        }

    try:
        resposta = requests.get(
            f"{CITEL_API_BASE}/requests/{ticket_id}",
            headers=headers,
            auth=auth,
            timeout=8,
        )
        _validar_resposta_citel(resposta)

        request_data = resposta.json().get("request", {})
        status = str(request_data.get("status", "") or "").strip().casefold()
        solved_flag = request_data.get("solved") is True

        return {
            "ok": True,
            "status": status,
            "resolvido": bool(solved_flag or status in {"solved", "closed"}),
            "updated_at": request_data.get("updated_at"),
        }

    except requests.RequestException:
        return {
            "ok": False,
            "status": "",
            "resolvido": False,
            "erro": "Não foi possível conectar ao portal da Citel.",
        }
    except Exception as e:
        return {
            "ok": False,
            "status": "",
            "resolvido": False,
            "erro": str(e),
        }


def _status_ferpam_aguardando_terceiro(status):
    texto = _normalizar_sem_acento(status).casefold().strip()
    return "aguardando terceiro" in texto


def _rotulo_status_citel(status):
    mapa = {
        "new": "Novo",
        "open": "Aberto",
        "pending": "Pendente",
        "hold": "Em espera",
        "solved": "Resolvido",
        "closed": "Fechado",
    }
    valor = str(status or "").strip().casefold()
    return mapa.get(valor, valor.title() if valor else "-")

def _listar_comentarios_citel_por_papel(ticket_id, role, headers, auth):
    """
    Lista comentários públicos do request para um único papel.

    role='agent'    -> comentários da Citel
    role='end_user' -> comentários da Ferpam/TI (requester/collaborators)

    O endpoint /requests é a visão do usuário final no Zendesk e, portanto,
    não expõe notas privadas de agentes.
    """
    url = f"{CITEL_API_BASE}/requests/{ticket_id}/comments"
    comentarios_encontrados = []

    # Limite defensivo: evita um ticket anormal gerar dezenas de requisições.
    # 20 páginas x 100 comentários por papel = até 4.000 mensagens combinadas.
    max_paginas = 20
    por_pagina = 100
    truncado = False

    for pagina in range(1, max_paginas + 1):
        params = {
            "role": role,
            "sort_by": "created_at",
            "sort_order": "asc",
            "per_page": por_pagina,
            "page": pagina,
        }

        resposta = requests.get(
            url,
            headers=headers,
            auth=auth,
            params=params,
            timeout=10,
        )
        _validar_resposta_citel(resposta)

        dados = resposta.json()
        pagina_comentarios = dados.get("comments", [])
        if not isinstance(pagina_comentarios, list):
            pagina_comentarios = []

        for comentario in pagina_comentarios:
            if not isinstance(comentario, dict):
                continue

            # Copiamos somente os campos necessários para o modal.
            # Não armazenamos credenciais, headers, cookies ou HTML do Zendesk.
            comentarios_encontrados.append({
                "id": comentario.get("id"),
                "created_at": comentario.get("created_at"),
                "plain_body": comentario.get("plain_body") or comentario.get("body") or "",
                "attachments": comentario.get("attachments") or [],
                "papel": role,
            })

        if len(pagina_comentarios) < por_pagina:
            break

        if pagina == max_paginas:
            truncado = True

    return comentarios_encontrados, truncado


@st.cache_data(ttl=60, show_spinner=False)
def consultar_historico_citel(ticket_id):
    """
    Busca o histórico público do chamado da Citel para exibição somente leitura.

    Segurança:
    - usa credenciais exclusivamente no servidor;
    - não devolve senha/token para a interface;
    - usa a Requests API, que representa a visão de usuário final e não inclui
      notas privadas de agentes;
    - mantém em memória/cache apenas conteúdo necessário para exibição.
    """
    ticket_id = str(ticket_id or "").strip()
    if not ticket_id or not ticket_id.isdigit():
        return {
            "ok": False,
            "erro": "ID do chamado da Citel inválido.",
            "mensagens": [],
        }

    headers, auth, erro_config = _auth_citel()
    if erro_config:
        return {
            "ok": False,
            "erro": erro_config,
            "mensagens": [],
        }

    try:
        mensagens_citel, truncado_citel = _listar_comentarios_citel_por_papel(
            ticket_id,
            "agent",
            headers,
            auth,
        )
        mensagens_ferpam, truncado_ferpam = _listar_comentarios_citel_por_papel(
            ticket_id,
            "end_user",
            headers,
            auth,
        )

        mensagens = mensagens_citel + mensagens_ferpam

        # Remove possíveis duplicidades pelo ID do comentário sem alterar a ordem.
        unicos = {}
        sem_id = []
        for mensagem in mensagens:
            msg_id = mensagem.get("id")
            if msg_id is None:
                sem_id.append(mensagem)
            else:
                unicos[str(msg_id)] = mensagem

        mensagens = list(unicos.values()) + sem_id

        # Conversa na ordem cronológica. Datas inválidas ficam no fim.
        def chave_data(item):
            dt = pd.to_datetime(item.get("created_at"), errors="coerce", utc=True)
            if pd.isna(dt):
                return pd.Timestamp.max.tz_localize("UTC")
            return dt

        mensagens.sort(key=chave_data)

        return {
            "ok": True,
            "mensagens": mensagens,
            "truncado": bool(truncado_citel or truncado_ferpam),
        }

    except requests.RequestException:
        return {
            "ok": False,
            "erro": "Não foi possível conectar ao portal da Citel.",
            "mensagens": [],
        }
    except Exception as e:
        return {
            "ok": False,
            "erro": str(e),
            "mensagens": [],
        }


def _texto_comentario_seguro(valor):
    """Normaliza o texto sem interpretar HTML enviado pelo sistema externo."""
    texto = str(valor or "").replace("\x00", "").strip()

    # Proteção de interface contra um comentário excepcionalmente gigantesco.
    limite = 30000
    if len(texto) > limite:
        texto = texto[:limite] + "\n\n[Mensagem muito longa; exibindo somente os primeiros 30.000 caracteres.]"

    return texto


def _renderizar_texto_comentario_seguro(texto):
    """Renderiza texto externo com escape HTML e quebra de linha visual."""
    texto_escapado = html.escape(str(texto or ""), quote=True).replace("\n", "<br>")
    st.markdown(
        f"<div style='white-space:normal; overflow-wrap:anywhere; line-height:1.55;'>{texto_escapado}</div>",
        unsafe_allow_html=True,
    )


def _nomes_anexos_seguros(anexos):
    """
    Retorna apenas os nomes dos anexos.
    Não disponibilizamos content_url no portal para não repassar URLs/tokens
    de download do sistema externo aos usuários do dashboard.
    """
    nomes = []
    if not isinstance(anexos, list):
        return nomes

    for anexo in anexos[:20]:
        if not isinstance(anexo, dict):
            continue
        nome = str(anexo.get("file_name") or anexo.get("name") or "Anexo").strip()
        if nome:
            nomes.append(nome[:180])

    return nomes


def _conteudo_modal_historico_citel(ticket_id, link=""):
    st.caption(
        "Somente as mensagens públicas visíveis para a conta da Ferpam no portal da Citel são exibidas aqui."
    )

    with st.spinner("Buscando histórico no portal da Citel..."):
        historico = consultar_historico_citel(ticket_id)

    if not historico.get("ok"):
        st.error("Não foi possível carregar o histórico da Citel agora.")
        if st.session_state.get("autenticado_admin"):
            st.caption(f"Admin: {historico.get('erro', 'Erro não identificado')}")
        return

    mensagens = historico.get("mensagens", [])

    if not mensagens:
        st.info("Nenhuma mensagem pública foi encontrada neste chamado da Citel.")
    else:
        st.caption(f"{len(mensagens)} mensagem(ns) encontrada(s).")

        if historico.get("truncado"):
            st.warning(
                "Este chamado possui um histórico muito grande. Por segurança, "
                "o portal limitou a quantidade consultada nesta visualização."
            )

        for indice, mensagem in enumerate(mensagens):
            papel = mensagem.get("papel")
            eh_citel = papel == "agent"
            autor = "Citel" if eh_citel else "TI / Ferpam"
            icone = "🔵" if eh_citel else "🟢"
            data_str = formatar_data_citel(mensagem.get("created_at")) or "Data não informada"
            texto = _texto_comentario_seguro(mensagem.get("plain_body"))
            anexos = _nomes_anexos_seguros(mensagem.get("attachments"))

            with st.container(border=True):
                col_autor, col_data = st.columns([6, 4])
                with col_autor:
                    st.markdown(f"**{icone} {autor}**")
                with col_data:
                    st.caption(data_str)

                # O texto externo é escapado antes de qualquer renderização HTML,
                # então tags e scripts vindos do sistema externo permanecem texto.
                if texto:
                    _renderizar_texto_comentario_seguro(texto)
                else:
                    st.caption("Mensagem sem conteúdo textual.")

                if anexos:
                    st.caption("📎 Anexo(s): " + " • ".join(anexos))

    st.divider()
    col_info, col_acao = st.columns([7, 3])
    with col_info:
        st.caption(f"Chamado externo Citel #{ticket_id} • visualização somente leitura")
    with col_acao:
        if link:
            st.link_button(
                "🔗 Abrir na Citel",
                link,
                use_container_width=True,
            )


# Modal nativo do Streamlit. O fallback impede o app inteiro de quebrar caso
# uma instalação antiga do Streamlit seja usada por engano.
if hasattr(st, "dialog"):
    @st.dialog("💬 Histórico do chamado com a Citel", width="large")
    def abrir_historico_citel_dialog(ticket_id, link=""):
        _conteudo_modal_historico_citel(ticket_id, link)
else:
    def abrir_historico_citel_dialog(ticket_id, link=""):
        st.error(
            "A versão instalada do Streamlit não possui suporte a janela modal (st.dialog). "
            "Atualize o Streamlit para usar o histórico em janela."
        )


def render_acompanhamento_citel(chamado):
    vinculados = localizar_terceiros_do_chamado(chamado)
    if vinculados.empty:
        return

    citel = vinculados[
        vinculados["nome_terceiro"].fillna("").astype(str).str.contains("citel", case=False, na=False)
        | vinculados["link"].fillna("").astype(str).str.contains("citelsoftware", case=False, na=False)
    ].copy()

    if citel.empty:
        return

    # Não polui chamados já concluídos com um "aguardando" antigo.
    if classificar_status_grupo(chamado.get("status", "")) == "Concluídos":
        return

    st.divider()
    st.subheader("🌐 Acompanhamento com a Citel")

    for idx_citel, item in citel.reset_index(drop=True).iterrows():
        link = str(item.get("link", "") or "").strip()
        ticket_citel = extrair_id_ticket_citel(link, item.get("id_ticket", ""))

        with st.container(border=True):
            col_estado, col_acoes = st.columns([7, 3])

            with col_estado:
                if ticket_citel:
                    st.caption(f"Chamado Citel #{ticket_citel}")

                resultado_citel = consultar_vez_resposta_citel(ticket_citel)

                if resultado_citel.get("ok") and resultado_citel.get("estado") == "roadmap":
                    st.info("🟣 **Chamado em Roadmap na Citel**")
                    st.write(
                        "A Citel informou que este chamado está em Roadmap. "
                        "Neste momento não há resposta pendente da TI nem da Citel."
                    )

                elif resultado_citel.get("ok") and resultado_citel.get("estado") == "aguardando_citel":
                    st.warning("🟡 **Aguardando resposta da Citel**")
                    st.write("A nossa TI já respondeu. Agora estamos esperando o retorno da Citel.")

                elif resultado_citel.get("ok") and resultado_citel.get("estado") == "aguardando_ti":
                    st.info("🔵 **Citel respondeu — aguardando TI**")
                    st.write("A Citel já respondeu no chamado externo. Agora o retorno está com a nossa TI.")

                else:
                    st.info("⚪ **Não foi possível verificar a resposta da Citel agora.**")
                    if st.session_state.get("autenticado_admin"):
                        st.caption(f"Admin: {resultado_citel.get('erro', 'Erro não identificado')}")

                data_str = formatar_data_citel(resultado_citel.get("ultima_data"))
                if data_str:
                    st.caption(f"Última interação considerada: {data_str}")

            with col_acoes:
                st.write("")

                if ticket_citel:
                    if st.button(
                        "💬 Ver histórico",
                        key=f"btn_hist_citel_{ticket_citel}_{idx_citel}",
                        use_container_width=True,
                        help="Abre somente as mensagens públicas do chamado da Citel.",
                    ):
                        if st.session_state.get("autenticado_admin"):
                            registrar_auditoria_seguro(
                                "VER_HISTORICO_CITEL",
                                ticket=str(chamado.get("id_chamado", "")),
                                detalhes=f"Chamado externo Citel #{ticket_citel}",
                            )
                        abrir_historico_citel_dialog(ticket_citel, link)

                if link:
                    st.link_button(
                        "🔗 Abrir na Citel",
                        link,
                        use_container_width=True,
                    )


# ============================================================
# FERRAMENTAS ADMINISTRATIVAS / INTELIGÊNCIA OPERACIONAL
# ============================================================

STOPWORDS_PROBLEMAS = {
    "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "da", "do", "das", "dos",
    "e", "em", "no", "na", "nos", "nas", "para", "por", "com", "sem", "ao", "aos", "que",
    "se", "me", "meu", "minha", "meus", "minhas", "favor", "favor", "solicito", "solicita",
    "solicitacao", "solicitação", "preciso", "necessario", "necessário", "chamado", "ticket",
    "erro", "problema", "ajuda", "suporte", "ti", "nao", "não", "esta", "está", "foi", "ser",
    "pra", "pro", "pela", "pelo", "uma", "usuario", "usuário", "sistema"
}

DIAS_SEMANA = {
    0: "Segunda",
    1: "Terça",
    2: "Quarta",
    3: "Quinta",
    4: "Sexta",
    5: "Sábado",
    6: "Domingo",
}


def _normalizar_sem_acento(valor):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    return "".join(c for c in texto if not unicodedata.combining(c))


def _tokens_problema(valor):
    texto = _normalizar_sem_acento(valor).casefold()
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    tokens = []
    for token in texto.split():
        if len(token) < 3 or token.isdigit() or token in STOPWORDS_PROBLEMAS:
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens


def _assinatura_problema(linha):
    titulo = str(linha.get("titulo", "") or "").strip()
    ocorrencia = str(linha.get("ocorrencia", "") or "").strip()
    tokens = _tokens_problema(titulo)
    if len(tokens) < 2:
        tokens = _tokens_problema(f"{titulo} {ocorrencia[:250]}")
    if not tokens:
        return ""
    # Ordenação torna títulos como "Impressora caixa" e "Caixa impressora" equivalentes.
    return " ".join(sorted(tokens[:5]))


@st.cache_data(ttl=180, show_spinner=False)
def obter_problemas_recorrentes(df_base, minimo=2, limite=15):
    if df_base.empty:
        return pd.DataFrame(columns=["Problema", "Quantidade", "Exemplo", "Departamentos", "Tickets"])

    trabalho = df_base.copy()
    trabalho["_assinatura"] = trabalho.apply(_assinatura_problema, axis=1)
    trabalho = trabalho[trabalho["_assinatura"] != ""]
    if trabalho.empty:
        return pd.DataFrame(columns=["Problema", "Quantidade", "Exemplo", "Departamentos", "Tickets"])

    linhas = []
    for assinatura, grupo in trabalho.groupby("_assinatura"):
        qtd = len(grupo)
        if qtd < minimo:
            continue
        titulos = [str(v).strip() for v in grupo["titulo"].tolist() if str(v).strip()]
        exemplo = titulos[0] if titulos else assinatura.title()
        departamentos = sorted({str(v).strip() for v in grupo["departamento"].tolist() if str(v).strip()})
        tickets = [str(v).strip() for v in grupo["id_chamado"].tolist() if str(v).strip()]
        linhas.append({
            "Problema": assinatura,
            "Quantidade": qtd,
            "Exemplo": exemplo[:120],
            "Departamentos": ", ".join(departamentos[:4]) or "-",
            "Tickets": ", ".join(tickets[:8]),
        })

    if not linhas:
        return pd.DataFrame(columns=["Problema", "Quantidade", "Exemplo", "Departamentos", "Tickets"])

    return pd.DataFrame(linhas).sort_values(["Quantidade", "Problema"], ascending=[False, True]).head(limite)


def _similaridade_problemas(tokens_a, tokens_b, texto_a="", texto_b=""):
    set_a, set_b = set(tokens_a), set(tokens_b)
    if not set_a or not set_b:
        return 0.0
    jaccard = len(set_a & set_b) / max(1, len(set_a | set_b))
    seq = SequenceMatcher(None, texto_a, texto_b).ratio() if texto_a and texto_b else 0.0
    return max(jaccard, seq * 0.85)


@st.cache_data(ttl=120, show_spinner=False)
def detectar_possiveis_recorrencias(df_base, dias=7, minimo=3, limite_registros=250):
    if df_base.empty or "dt_abertura" not in df_base.columns:
        return []

    agora = pd.Timestamp.now()
    inicio = agora - pd.Timedelta(days=int(dias))
    recente = df_base[df_base["dt_abertura"].notna() & (df_base["dt_abertura"] >= inicio)].copy()
    recente = recente.sort_values("dt_abertura", ascending=False).head(limite_registros)
    if recente.empty:
        return []

    itens = []
    for _, row in recente.iterrows():
        titulo = str(row.get("titulo", "") or "").strip()
        ocorrencia = str(row.get("ocorrencia", "") or "").strip()
        texto = f"{titulo} {ocorrencia[:300]}".strip()
        tokens = _tokens_problema(texto)
        if not tokens:
            continue
        itens.append({
            "ticket": str(row.get("id_chamado", "") or "").strip(),
            "titulo": titulo or "Sem título",
            "departamento": str(row.get("departamento", "") or "").strip(),
            "data": row.get("dt_abertura"),
            "tokens": tokens,
            "texto_norm": " ".join(tokens),
        })

    grupos = []
    for item in itens:
        melhor_indice = None
        melhor_score = 0.0
        for i, grupo in enumerate(grupos):
            representante = grupo[0]
            score = _similaridade_problemas(
                item["tokens"],
                representante["tokens"],
                item["texto_norm"],
                representante["texto_norm"],
            )
            if score > melhor_score:
                melhor_score = score
                melhor_indice = i

        if melhor_indice is not None and melhor_score >= 0.52:
            grupos[melhor_indice].append(item)
        else:
            grupos.append([item])

    grupos_validos = [g for g in grupos if len(g) >= int(minimo)]
    grupos_validos.sort(key=lambda g: (len(g), max(x["data"] for x in g if pd.notna(x["data"]))), reverse=True)
    return grupos_validos[:10]


def calcular_backlog_ate(df_base, fim_periodo):
    if df_base.empty:
        return 0
    abriu = df_base["dt_abertura"].notna() & (df_base["dt_abertura"] <= fim_periodo)
    ainda_nao_fechou = df_base["dt_conclusao_efetiva"].isna() | (df_base["dt_conclusao_efetiva"] > fim_periodo)
    return int((abriu & ainda_nao_fechou).sum())


@st.cache_data(ttl=180, show_spinner=False)
def metricas_mes(df_base, periodo):
    inicio = periodo.to_timestamp(how="start")
    fim = periodo.to_timestamp(how="end")
    abertos = df_base[df_base["dt_abertura"].notna() & (df_base["dt_abertura"] >= inicio) & (df_base["dt_abertura"] <= fim)]
    concluidos = df_base[
        df_base["dt_conclusao_efetiva"].notna()
        & (df_base["dt_conclusao_efetiva"] >= inicio)
        & (df_base["dt_conclusao_efetiva"] <= fim)
    ]
    avaliados = df_base[
        df_base["dt_aval_parsed"].notna()
        & (df_base["dt_aval_parsed"] >= inicio)
        & (df_base["dt_aval_parsed"] <= fim)
        & df_base["nota_num"].notna()
        & (df_base["nota_num"] > 0)
    ]
    sla_mes = abertos[abertos["sla_valido"] == True]

    return {
        "abertos": len(abertos),
        "concluidos": len(concluidos),
        "backlog": calcular_backlog_ate(df_base, fim),
        "sla_medio": sla_mes["min_total"].mean() if not sla_mes.empty else None,
        "csat": avaliados["nota_num"].mean() if not avaliados.empty else None,
        "avaliacoes": len(avaliados),
    }


def _delta_num(atual, anterior, sufixo=""):
    if atual is None or anterior is None or pd.isna(atual) or pd.isna(anterior):
        return None
    diff = atual - anterior
    sinal = "+" if diff > 0 else ""
    return f"{sinal}{diff:.1f}{sufixo}" if isinstance(diff, float) else f"{sinal}{diff}{sufixo}"


@st.cache_data(ttl=120, show_spinner=False)
def montar_base_terceiros_admin(df_chamados, df_terceiros_base):
    """Monta a base administrativa de terceiros com merge vetorizado."""
    colunas_saida = [
        "id_chamado", "ticket_ferpam", "titulo", "status_ferpam", "grupo_status",
        "tecnico", "departamento", "nome_terceiro", "link", "id_ticket", "roadmap",
        "data_solicitação", "ultima_atualizacao"
    ]

    if df_terceiros_base.empty:
        return pd.DataFrame(columns=colunas_saida)

    terceiros = df_terceiros_base.copy()
    chamados = df_chamados.copy()

    for col in ["id_appsheet", "id_chamado", "titulo", "status", "tecnico", "departamento"]:
        if col not in chamados.columns:
            chamados[col] = ""

    terceiros["_join_key"] = (
        terceiros["id_chamado"].fillna("").astype(str).str.strip().str.casefold()
    )

    campos_chamado = ["id_chamado", "titulo", "status", "tecnico", "departamento"]

    mapa_app = chamados[["id_appsheet"] + campos_chamado].copy()
    mapa_app["_join_key"] = mapa_app["id_appsheet"].fillna("").astype(str).str.strip().str.casefold()

    mapa_visivel = chamados[campos_chamado].copy()
    mapa_visivel["_join_key"] = mapa_visivel["id_chamado"].fillna("").astype(str).str.strip().str.casefold()

    mapa_app = mapa_app.drop(columns=["id_appsheet"])
    mapa = pd.concat([mapa_app, mapa_visivel], ignore_index=True)
    mapa = mapa[mapa["_join_key"] != ""].drop_duplicates("_join_key", keep="first")

    merged = terceiros.merge(
        mapa,
        how="left",
        on="_join_key",
        suffixes=("_terceiro", "_chamado"),
    )

    status = merged["status"].fillna("").astype(str).str.strip()

    saida = pd.DataFrame({
        "id_chamado": merged["id_chamado_terceiro"].fillna("").astype(str).str.strip(),
        "ticket_ferpam": merged["id_chamado_chamado"].fillna("").astype(str).str.strip(),
        "titulo": merged["titulo"].fillna("").astype(str).str.strip(),
        "status_ferpam": status,
        "grupo_status": status.map(lambda s: classificar_status_grupo(s) if s else "Não localizado"),
        "tecnico": merged["tecnico"].fillna("").astype(str).str.strip(),
        "departamento": merged["departamento"].fillna("").astype(str).str.strip(),
        "nome_terceiro": merged["nome_terceiro"].fillna("").astype(str).str.strip().replace("", "Não informado"),
        "link": merged["link"].fillna("").astype(str).str.strip(),
        "id_ticket": merged["id_ticket"].fillna("").astype(str).str.strip(),
        "roadmap": merged["roadmap"].fillna("").astype(str).str.strip(),
        "data_solicitação": merged["data_solicitação"].fillna("").astype(str).str.strip(),
        "ultima_atualizacao": merged["ultima_atualizacao"].fillna("").astype(str).str.strip(),
    })

    return saida[colunas_saida]


def _resumo_texto(valor, limite=260):
    texto = re.sub(r"\s+", " ", str(valor or "")).strip()
    if len(texto) > limite:
        return texto[: limite - 1].rstrip() + "…"
    return texto


def _dados_resumo_automatico_chamado(chamado):
    """
    Monta os dados do resumo em formato estruturado para evitar um paredão de texto.
    A consulta da Citel, quando existir, continua sendo somente leitura e usa cache.
    """
    ticket = str(chamado.get("id_chamado", "") or "").strip()
    status = str(chamado.get("status", "") or "Aberto").strip()
    prioridade = str(chamado.get("prioridade", "") or "Não informada").strip()
    tecnico = str(chamado.get("tecnico", "") or "Não atribuído").strip()
    solicitante = str(chamado.get("solicitante", "") or "Não informado").strip()
    departamento = str(chamado.get("departamento", "") or "Não informado").strip()
    titulo = _resumo_texto(chamado.get("titulo", "Sem título"), 180)
    atividade = _resumo_texto(chamado.get("atividade_realizada", ""), 420)
    ocorrencia = _resumo_texto(chamado.get("ocorrencia", ""), 420)

    abertura = chamado.get("dt_abertura")
    if pd.notna(abertura):
        try:
            abertura_str = pd.Timestamp(abertura).strftime("%d/%m/%Y às %H:%M")
        except Exception:
            abertura_str = "Não informada"
    else:
        abertura_str = "Não informada"

    proxima_acao = "Acompanhar o atendimento conforme o status atual."
    acao_titulo = "Próxima ação"
    acao_tipo = "info"
    grupo = classificar_status_grupo(status)

    if grupo == "Concluídos":
        acao_titulo = "Chamado finalizado"
        proxima_acao = "Nenhuma ação operacional pendente foi identificada."
        acao_tipo = "ok"
    elif not tecnico or tecnico.casefold() in {"não atribuído", "nao atribuido", "nan"}:
        acao_titulo = "Ação da TI necessária"
        proxima_acao = "Atribuir um técnico responsável para este chamado."
        acao_tipo = "attention"
    elif "solicitante" in status.casefold():
        acao_titulo = "Aguardando solicitante"
        proxima_acao = "O próximo retorno está com o solicitante."
        acao_tipo = "wait"

    ticket_citel = None
    estado_citel = None

    vinculados = localizar_terceiros_do_chamado(chamado)
    if not vinculados.empty:
        citel = vinculados[
            vinculados["nome_terceiro"].fillna("").astype(str).str.contains("citel", case=False, na=False)
            | vinculados["link"].fillna("").astype(str).str.contains("citelsoftware", case=False, na=False)
        ]

        if not citel.empty:
            item = citel.iloc[0]
            ticket_citel = extrair_id_ticket_citel(
                item.get("link", ""),
                item.get("id_ticket", ""),
            )
            situacao = consultar_vez_resposta_citel(ticket_citel)
            estado_citel = situacao.get("estado") if situacao.get("ok") else None

            if situacao.get("ok") and situacao.get("estado") == "roadmap":
                acao_titulo = "Roadmap na Citel"
                proxima_acao = (
                    f"O chamado externo #{ticket_citel} está em Roadmap. "
                    "Não há retorno operacional pendente neste momento."
                )
                acao_tipo = "info"

            elif situacao.get("ok") and situacao.get("estado") == "aguardando_ti":
                acao_titulo = "Citel respondeu — ação da TI"
                proxima_acao = (
                    f"A Citel respondeu no chamado #{ticket_citel}. "
                    "O próximo retorno está com a TI/Ferpam."
                )
                acao_tipo = "attention"

            elif situacao.get("ok") and situacao.get("estado") == "aguardando_citel":
                acao_titulo = "Aguardando Citel"
                proxima_acao = (
                    f"A TI/Ferpam já respondeu no chamado externo #{ticket_citel}. "
                    "Agora estamos aguardando a Citel."
                )
                acao_tipo = "wait"

    return {
        "ticket": ticket,
        "status": status,
        "prioridade": prioridade,
        "tecnico": tecnico,
        "solicitante": solicitante,
        "departamento": departamento,
        "titulo": titulo,
        "atividade": atividade,
        "ocorrencia": ocorrencia,
        "abertura": abertura_str,
        "acao_titulo": acao_titulo,
        "proxima_acao": proxima_acao,
        "acao_tipo": acao_tipo,
        "ticket_citel": ticket_citel,
        "estado_citel": estado_citel,
    }


def gerar_resumo_automatico_chamado(chamado):
    """
    Mantida por compatibilidade. Retorna uma versão textual curta,
    mas a interface administrativa usa o resumo estruturado.
    """
    dados = _dados_resumo_automatico_chamado(chamado)

    partes = [
        f"Chamado #{dados['ticket']}: {dados['titulo']}.",
        f"Status: {dados['status']}.",
        f"Técnico: {dados['tecnico']}.",
        dados["proxima_acao"],
    ]
    return " ".join(partes)


def _normalizar_data_timeline(valor):
    """
    Normaliza toda data da timeline para UTC.

    O Google Sheets entrega datas internas sem timezone (horário local de
    Tocantins/Brasília), enquanto o Zendesk/Citel entrega ISO com timezone.
    Sem normalizar, o Pandas tenta comparar Timestamp naive com aware e gera:
    TypeError: Cannot compare tz-naive and tz-aware timestamps.
    """
    if valor is None:
        return None

    try:
        if isinstance(valor, str) and not valor.strip():
            return None
    except Exception:
        pass

    try:
        dt = pd.to_datetime(valor, errors="coerce", dayfirst=True)
    except Exception:
        return None

    if pd.isna(dt):
        return None

    try:
        dt = pd.Timestamp(dt)
    except Exception:
        return None

    try:
        if dt.tzinfo is None:
            # Datas internas da planilha representam horário local.
            dt = dt.tz_localize(
                "America/Araguaina",
                ambiguous="NaT",
                nonexistent="shift_forward",
            )
            if pd.isna(dt):
                return None
        return dt.tz_convert("UTC")
    except Exception:
        # Fallback defensivo para versões diferentes do pandas.
        try:
            if dt.tzinfo is None:
                dt = dt.tz_localize("America/Araguaina")
            return dt.tz_convert("UTC")
        except Exception:
            return None


def _adicionar_evento_timeline(eventos, data, origem, titulo, descricao=""):
    dt = _normalizar_data_timeline(data)
    if dt is None:
        return

    eventos.append({
        "data": dt,
        "origem": str(origem or "Não informado").strip(),
        "titulo": str(titulo or "Evento").strip(),
        "descricao": _resumo_texto(descricao, 1000),
    })


def montar_linha_tempo_unica(chamado, incluir_citel=False):
    eventos = []

    _adicionar_evento_timeline(
        eventos,
        chamado.get("dt_abertura"),
        "Ferpam",
        "Chamado aberto",
        chamado.get("ocorrencia", ""),
    )

    _adicionar_evento_timeline(
        eventos,
        chamado.get("dt_tecnico"),
        "Ferpam",
        "Atendimento técnico iniciado",
        f"Técnico: {chamado.get('tecnico') or 'Não informado'}",
    )

    vinculados = localizar_terceiros_do_chamado(chamado)

    for _, terceiro in vinculados.iterrows():
        nome = str(
            terceiro.get("nome_terceiro", "") or "Terceiro"
        ).strip() or "Terceiro"

        _adicionar_evento_timeline(
            eventos,
            terceiro.get("data_solicitação"),
            nome,
            f"Terceiro acionado: {nome}",
            f"Ticket externo: {terceiro.get('id_ticket') or '-'}",
        )

        _adicionar_evento_timeline(
            eventos,
            terceiro.get("ultima_atualizacao"),
            nome,
            f"Atualização registrada — {nome}",
            "Última atualização registrada na planilha de terceiros.",
        )

        eh_citel = (
            "citel" in nome.casefold()
            or "citelsoftware" in str(terceiro.get("link", "")).casefold()
        )

        if incluir_citel and eh_citel:
            ticket_citel = extrair_id_ticket_citel(
                terceiro.get("link", ""),
                terceiro.get("id_ticket", ""),
            )
            historico = consultar_historico_citel(ticket_citel)

            if historico.get("ok"):
                for mensagem in historico.get("mensagens", []):
                    papel = mensagem.get("papel")
                    autor = "Citel" if papel == "agent" else "TI / Ferpam"

                    _adicionar_evento_timeline(
                        eventos,
                        mensagem.get("created_at"),
                        autor,
                        f"Mensagem pública — {autor}",
                        mensagem.get("plain_body", ""),
                    )

    atividade = str(chamado.get("atividade_realizada", "") or "").strip()
    if atividade:
        # Só usa a conclusão como momento da atividade se a data existir.
        # Evita criar evento com data inventada.
        _adicionar_evento_timeline(
            eventos,
            chamado.get("dt_conclusao_efetiva"),
            "Ferpam",
            "Atividade / resolução registrada",
            atividade,
        )

    _adicionar_evento_timeline(
        eventos,
        chamado.get("dt_conclusao_efetiva"),
        "Ferpam",
        "Chamado concluído",
        f"Status: {chamado.get('status') or '-'}",
    )

    nota = chamado.get("nota_num")
    if pd.notna(nota):
        try:
            nota_float = float(nota)
        except (TypeError, ValueError):
            nota_float = 0

        if nota_float > 0:
            _adicionar_evento_timeline(
                eventos,
                chamado.get("dt_aval_parsed"),
                "Solicitante",
                f"Atendimento avaliado: {nota_float:.0f}/5",
                chamado.get("comentario_avaliacao", ""),
            )

    # Todas as datas já estão timezone-aware em UTC.
    eventos.sort(key=lambda e: e["data"])
    return eventos


def _classe_timeline_origem(origem):
    origem_cf = str(origem or "").casefold()

    if "citel" in origem_cf:
        return "timeline-dot-citel"

    if "ferpam" in origem_cf or origem_cf == "ti":
        return "timeline-dot-ferpam"

    if "solicitante" in origem_cf:
        return "timeline-dot-user"

    return "timeline-dot-third"


def _render_evento_timeline(evento):
    data = evento.get("data")
    if data is None:
        return

    try:
        data_local = pd.Timestamp(data).tz_convert("America/Araguaina")
        data_str = data_local.strftime("%d/%m/%Y às %H:%M")
    except Exception:
        data_str = "Data não informada"

    titulo = html.escape(str(evento.get("titulo", "Evento") or "Evento"), quote=True)
    origem = html.escape(str(evento.get("origem", "Não informado") or "Não informado"), quote=True)
    descricao = html.escape(str(evento.get("descricao", "") or ""), quote=True)
    descricao = descricao.replace("\n", "<br>")

    classe_dot = _classe_timeline_origem(evento.get("origem"))

    descricao_html = ""
    if descricao:
        descricao_html = f'<div class="timeline-description">{descricao}</div>'

    st.markdown(
        f"""
        <div class="timeline-entry">
            <div class="timeline-axis">
                <div class="timeline-dot {classe_dot}"></div>
            </div>
            <div class="timeline-card">
                <div class="timeline-top">
                    <div class="timeline-title">{titulo}</div>
                    <div class="timeline-date">{html.escape(data_str)}</div>
                </div>
                <div class="timeline-origin">{origem}</div>
                {descricao_html}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_resumo_admin_chamado(chamado):
    dados = _dados_resumo_automatico_chamado(chamado)

    ticket = html.escape(dados["ticket"], quote=True)
    titulo = html.escape(dados["titulo"], quote=True)
    status = html.escape(dados["status"], quote=True)
    prioridade = html.escape(dados["prioridade"], quote=True)
    tecnico = html.escape(dados["tecnico"], quote=True)
    abertura = html.escape(dados["abertura"], quote=True)
    solicitante = html.escape(dados["solicitante"], quote=True)
    departamento = html.escape(dados["departamento"], quote=True)
    ocorrencia = html.escape(dados["ocorrencia"], quote=True)
    atividade = html.escape(dados["atividade"], quote=True)
    acao_titulo = html.escape(dados["acao_titulo"], quote=True)
    proxima_acao = html.escape(dados["proxima_acao"], quote=True)

    classe_acao = {
        "attention": "admin-action-attention",
        "wait": "admin-action-wait",
        "ok": "admin-action-ok",
        "info": "admin-action-info",
    }.get(dados["acao_tipo"], "admin-action-info")

    contexto = (
        f"<strong>{solicitante}</strong> • {departamento}"
        if solicitante or departamento
        else "Solicitante/departamento não informados"
    )

    atividade_html = ""
    if atividade:
        atividade_html = f"""
        <div class="admin-summary-context">
            <div class="admin-summary-context-title">Última atividade registrada</div>
            <div class="admin-summary-context-text">{atividade}</div>
        </div>
        """

    ocorrencia_html = ""
    if ocorrencia:
        ocorrencia_html = f"""
        <div class="admin-summary-context">
            <div class="admin-summary-context-title">Contexto do chamado</div>
            <div class="admin-summary-context-text">{ocorrencia}</div>
        </div>
        """

    st.markdown(
        f"""
        <div class="admin-summary-head">
            <div>
                <div class="admin-summary-kicker">Resumo operacional</div>
                <div class="admin-summary-title">{titulo}</div>
            </div>
            <div class="admin-summary-ticket">#{ticket}</div>
        </div>

        <div class="admin-summary-grid">
            <div class="admin-summary-cell">
                <div class="admin-summary-label">Status</div>
                <div class="admin-summary-value">{status}</div>
            </div>
            <div class="admin-summary-cell">
                <div class="admin-summary-label">Prioridade</div>
                <div class="admin-summary-value">{prioridade}</div>
            </div>
            <div class="admin-summary-cell">
                <div class="admin-summary-label">Técnico</div>
                <div class="admin-summary-value">{tecnico}</div>
            </div>
            <div class="admin-summary-cell">
                <div class="admin-summary-label">Aberto em</div>
                <div class="admin-summary-value">{abertura}</div>
            </div>
        </div>

        <div class="admin-summary-context">
            <div class="admin-summary-context-title">Solicitante / Departamento</div>
            <div class="admin-summary-context-text">{contexto}</div>
        </div>

        {ocorrencia_html}
        {atividade_html}

        <div class="admin-next-action {classe_acao}">
            <strong>{acao_titulo}</strong>
            <span>{proxima_acao}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_ferramentas_admin_ticket(chamado):
    if not st.session_state.get("autenticado_admin"):
        return

    st.divider()
    st.markdown("### 🧠 Painel administrativo do chamado")

    with st.container(border=True):
        render_resumo_admin_chamado(chamado)

    ticket = str(chamado.get("id_chamado", "") or "").strip()
    chave_timeline = f"timeline_citel_{ticket}"

    if chave_timeline not in st.session_state:
        st.session_state[chave_timeline] = False

    with st.expander("🕓 Histórico consolidado do chamado", expanded=False):
        vinculados = localizar_terceiros_do_chamado(chamado)

        tem_citel = False
        if not vinculados.empty:
            tem_citel = bool((
                vinculados["nome_terceiro"]
                .fillna("")
                .astype(str)
                .str.contains("citel", case=False, na=False)
                |
                vinculados["link"]
                .fillna("")
                .astype(str)
                .str.contains("citelsoftware", case=False, na=False)
            ).any())

        if tem_citel:
            col_t1, col_t2 = st.columns([7, 3])

            with col_t1:
                if st.session_state[chave_timeline]:
                    st.caption(
                        "Exibindo eventos internos + mensagens públicas da Citel."
                    )
                else:
                    st.caption(
                        "Exibindo eventos internos. Inclua a Citel para ver a conversa externa na mesma timeline."
                    )

            with col_t2:
                if not st.session_state[chave_timeline]:
                    if st.button(
                        "🌐 Incluir Citel",
                        key=f"btn_timeline_citel_{ticket}",
                        use_container_width=True,
                    ):
                        st.session_state[chave_timeline] = True
                        registrar_auditoria_seguro(
                            "CARREGAR_TIMELINE_CITEL",
                            ticket=ticket,
                            detalhes=(
                                "Mensagens públicas da Citel incluídas "
                                "na linha do tempo administrativa."
                            ),
                        )
                        st.rerun()
                else:
                    if st.button(
                        "Ocultar Citel",
                        key=f"btn_timeline_ocultar_{ticket}",
                        use_container_width=True,
                    ):
                        st.session_state[chave_timeline] = False
                        st.rerun()

        eventos = montar_linha_tempo_unica(
            chamado,
            incluir_citel=st.session_state[chave_timeline],
        )

        if not eventos:
            st.info(
                "Não há datas suficientes para montar o histórico deste chamado."
            )
        else:
            # Legenda simples para facilitar leitura sem ocupar espaço.
            st.caption("🟢 TI/Ferpam   •   🔵 Citel   •   🟠 Solicitante   •   🟣 Outros terceiros")

            for evento in eventos:
                _render_evento_timeline(evento)



# ============================================================
# MODO TV / MONITORAMENTO OPERACIONAL
# ============================================================

def _secret_int(nome, padrao, minimo=None, maximo=None):
    try:
        valor = int(
            str(st.secrets.get(nome, padrao)).strip()
        )
    except Exception:
        valor = int(padrao)

    if minimo is not None:
        valor = max(minimo, valor)

    if maximo is not None:
        valor = min(maximo, valor)

    return valor


TV_REFRESH_SECONDS = _secret_int(
    "TV_REFRESH_SECONDS",
    60,
    minimo=30,
    maximo=600,
)

TV_ALERTA_DIAS = _secret_int(
    "TV_ALERTA_DIAS",
    5,
    minimo=1,
    maximo=90,
)

TV_MAX_CITEL = _secret_int(
    "TV_MAX_CITEL",
    50,
    minimo=5,
    maximo=100,
)

CITEL_ALERTA_SEM_INTERACAO_DIAS = _secret_int(
    "CITEL_ALERTA_SEM_INTERACAO_DIAS",
    15,
    minimo=1,
    maximo=180,
)


def _lookup_chamados_tv(df_chamados):
    lookup = {}

    for _, chamado in df_chamados.iterrows():
        for valor in [
            chamado.get("id_appsheet", ""),
            chamado.get("id_chamado", ""),
        ]:
            chave = str(
                valor or ""
            ).strip().casefold()

            if chave and chave not in lookup:
                lookup[chave] = chamado

    return lookup


def _citel_ativos_tv(
    df_chamados,
    df_terceiros_atual,
):
    if (
        df_chamados.empty
        or df_terceiros_atual.empty
    ):
        return []

    lookup = _lookup_chamados_tv(df_chamados)
    registros = []
    vistos = set()

    for _, terceiro in df_terceiros_atual.iterrows():
        nome = str(
            terceiro.get("nome_terceiro", "") or ""
        ).strip()

        link = str(
            terceiro.get("link", "") or ""
        ).strip()

        eh_citel = (
            "citel" in nome.casefold()
            or "citelsoftware" in link.casefold()
        )

        if not eh_citel:
            continue

        chave_interna = str(
            terceiro.get("id_chamado", "") or ""
        ).strip().casefold()

        chamado = lookup.get(chave_interna)

        if chamado is None:
            continue

        if classificar_status_grupo(
            chamado.get("status", "")
        ) == "Concluídos":
            continue

        ticket_citel = extrair_id_ticket_citel(
            link,
            terceiro.get("id_ticket", ""),
        )

        if not ticket_citel:
            continue

        ticket_ferpam = str(
            chamado.get("id_chamado", "") or ""
        ).strip()

        chave_unica = (
            ticket_ferpam,
            ticket_citel,
        )

        if chave_unica in vistos:
            continue

        vistos.add(chave_unica)

        registros.append({
            "ticket_ferpam": ticket_ferpam,
            "ticket_citel": ticket_citel,
            "titulo": str(
                chamado.get("titulo", "") or ""
            ).strip(),
            "status": str(
                chamado.get("status", "") or ""
            ).strip(),
            "tecnico": str(
                chamado.get("tecnico", "") or ""
            ).strip(),
            "departamento": str(
                chamado.get("departamento", "") or ""
            ).strip(),
            "link": link,
        })

    return registros


def _mapa_ultima_atualizacao_terceiro_tv(
    df_terceiros_atual,
):
    mapa = {}

    if df_terceiros_atual.empty:
        return mapa

    for _, terceiro in df_terceiros_atual.iterrows():
        chave = str(
            terceiro.get("id_chamado", "") or ""
        ).strip().casefold()

        if not chave:
            continue

        datas = []

        for campo in [
            "ultima_atualizacao",
            "data_solicitação",
        ]:
            dt = _normalizar_data_timeline(
                terceiro.get(campo)
            )

            if dt is not None:
                datas.append(dt)

        if not datas:
            continue

        maior = max(datas)
        atual = mapa.get(chave)

        if atual is None or maior > atual:
            mapa[chave] = maior

    return mapa


def _chamados_parados_tv(
    df_chamados,
    df_terceiros_atual,
    agora_utc,
):
    """
    Aviso interno de chamado parado.

    Como a planilha não possui timestamp individual de cada texto de
    atividade_realizada, são usadas somente datas efetivamente registradas:
    abertura, início técnico e movimentação da aba terceiros.
    """
    mapa_terceiro = (
        _mapa_ultima_atualizacao_terceiro_tv(
            df_terceiros_atual
        )
    )

    alertas = []

    for _, chamado in df_chamados.iterrows():
        if classificar_status_grupo(
            chamado.get("status", "")
        ) == "Concluídos":
            continue

        datas = []

        for campo in [
            "dt_abertura",
            "dt_tecnico",
        ]:
            dt = _normalizar_data_timeline(
                chamado.get(campo)
            )

            if dt is not None:
                datas.append(dt)

        for valor_id in [
            chamado.get("id_appsheet", ""),
            chamado.get("id_chamado", ""),
        ]:
            chave = str(
                valor_id or ""
            ).strip().casefold()

            if (
                chave
                and chave in mapa_terceiro
            ):
                datas.append(
                    mapa_terceiro[chave]
                )

        if not datas:
            continue

        ultima = max(datas)

        dias = int(
            max(
                0,
                (
                    agora_utc - ultima
                ).total_seconds() // 86400,
            )
        )

        if dias < TV_ALERTA_DIAS:
            continue

        alertas.append({
            "ticket": str(
                chamado.get(
                    "id_chamado",
                    "",
                ) or ""
            ).strip(),
            "titulo": str(
                chamado.get(
                    "titulo",
                    "",
                ) or "Sem título"
            ).strip(),
            "status": str(
                chamado.get(
                    "status",
                    "",
                ) or ""
            ).strip(),
            "tecnico": str(
                chamado.get(
                    "tecnico",
                    "",
                ) or "Não atribuído"
            ).strip(),
            "dias": dias,
            "ultima": ultima,
        })

    alertas.sort(
        key=lambda x: (
            x["dias"],
            x["ultima"],
        ),
        reverse=True,
    )

    return alertas


def _adicionar_evento_tv(
    tipo,
    ticket,
    titulo,
    detalhe="",
):
    agora = pd.Timestamp.now(tz="UTC")

    eventos = list(
        st.session_state.get(
            "tv_eventos_recentes",
            [],
        )
    )

    assinatura = (
        f"{tipo}|{ticket}|{titulo}"
    )

    for evento in eventos:
        if (
            evento.get("assinatura")
            == assinatura
        ):
            return

    eventos.append({
        "tipo": tipo,
        "ticket": str(ticket or ""),
        "titulo": str(titulo or ""),
        "detalhe": str(detalhe or ""),
        "detectado_em": agora.isoformat(),
        "assinatura": assinatura,
    })

    limite = (
        agora
        - pd.Timedelta(minutes=20)
    )

    eventos_filtrados = []

    for evento in eventos:
        dt = pd.to_datetime(
            evento.get("detectado_em"),
            errors="coerce",
            utc=True,
        )

        if (
            pd.notna(dt)
            and dt >= limite
        ):
            eventos_filtrados.append(
                evento
            )

    st.session_state.tv_eventos_recentes = (
        eventos_filtrados[-30:]
    )


def _status_eh_pendente_tv(status):
    """
    Para o bloco 'Aconteceu agora', um ticket novo só permanece enquanto
    estiver no grupo de chamados abertos/pendentes.

    Assim que virar Em Andamento, Aguardando Terceiros, Aguardando
    Solicitante, Concluído etc., ele some do aviso de novo chamado.
    """
    return classificar_status_grupo(status) == "Abertos"


def _limpar_novos_chamados_nao_pendentes_tv(df_chamados):
    """
    Remove imediatamente do 'Aconteceu agora' os eventos de novo chamado
    cujo ticket deixou de estar pendente.

    Eventos de Citel/Roadmap não são afetados.
    """
    if df_chamados.empty:
        return

    status_por_ticket = {
        str(row.get("id_chamado", "") or "").strip(): row.get("status", "")
        for _, row in df_chamados.iterrows()
    }

    eventos = list(
        st.session_state.get(
            "tv_eventos_recentes",
            [],
        )
    )

    filtrados = []

    for evento in eventos:
        if evento.get("tipo") != "novo_chamado":
            filtrados.append(evento)
            continue

        ticket = str(
            evento.get("ticket", "") or ""
        ).strip()

        status_atual = status_por_ticket.get(ticket)

        # Se o ticket nem existe mais na base, também não faz sentido
        # manter o aviso na TV.
        if status_atual is None:
            continue

        if _status_eh_pendente_tv(status_atual):
            filtrados.append(evento)

    st.session_state.tv_eventos_recentes = filtrados


@st.cache_data(show_spinner=False)
def _gerar_ding_tv():
    """
    Gera em memória um ding curto de duas notas.
    Não depende de MP3, CDN ou arquivo externo.
    """
    sample_rate = 22050
    duracao_total = 0.42
    total_samples = int(sample_rate * duracao_total)

    buffer = io.BytesIO()

    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)

        frames = bytearray()

        for i in range(total_samples):
            t = i / sample_rate

            # Duas frequências suaves para parecer um ding, não um alarme.
            tom_1 = math.sin(2 * math.pi * 880 * t)
            tom_2 = math.sin(2 * math.pi * 1320 * t)

            # Envelope: entrada rápida e queda suave.
            ataque = min(1.0, t / 0.018)
            queda = math.exp(-6.8 * t)
            envelope = ataque * queda

            valor = 0.38 * envelope * (
                0.72 * tom_1
                + 0.28 * tom_2
            )

            amostra = int(
                max(-1.0, min(1.0, valor))
                * 32767
            )

            frames.extend(
                struct.pack("<h", amostra)
            )

        wav_file.writeframes(bytes(frames))

    return buffer.getvalue()


def _tocar_ding_novo_chamado_tv():
    """
    O autoplay do navegador pode exigir que o usuário tenha interagido
    previamente com a página. Entrar no Modo TV normalmente já conta
    como essa interação.
    """
    st.audio(
        _gerar_ding_tv(),
        format="audio/wav",
        autoplay=True,
    )


def _detectar_novos_chamados_tv(
    df_chamados,
):
    """
    Retorna a lista de tickets NOVOS e ainda PENDENTES detectados neste ciclo.

    O retorno permite tocar o som somente uma vez, exatamente no ciclo
    em que o ticket apareceu pela primeira vez.
    """
    ids_atuais = {
        str(v).strip()
        for v
        in df_chamados[
            "id_chamado"
        ].fillna("").astype(str)
        if str(v).strip()
    }

    anterior = st.session_state.get(
        "tv_snapshot_ids"
    )

    if anterior is None:
        st.session_state.tv_snapshot_ids = (
            list(ids_atuais)
        )
        return []

    novos = (
        ids_atuais - set(anterior)
    )

    novos_pendentes = []

    if novos:
        lookup = {
            str(
                r.get(
                    "id_chamado",
                    "",
                ) or ""
            ).strip(): r
            for _, r
            in df_chamados.iterrows()
        }

        for ticket in sorted(novos):
            chamado = lookup.get(ticket)

            if chamado is None:
                continue

            # Se o ticket apareceu na planilha já como Em Andamento,
            # Aguardando Terceiro etc., não entra como "novo pendente"
            # e não toca som.
            if not _status_eh_pendente_tv(
                chamado.get("status", "")
            ):
                continue

            titulo = str(
                chamado.get(
                    "titulo",
                    "",
                )
                or "Novo chamado"
            )

            _adicionar_evento_tv(
                "novo_chamado",
                ticket,
                f"Novo chamado #{ticket}",
                titulo,
            )

            novos_pendentes.append(ticket)

    st.session_state.tv_snapshot_ids = (
        list(ids_atuais)
    )

    return novos_pendentes


def _processar_citel_tv(
    df_chamados,
    df_terceiros_atual,
    agora_utc,
):
    """
    Consulta SOMENTE leitura.

    Retorna:
      - quem está aguardando quem;
      - quais chamados são Roadmap;
      - há quantos dias não existe nenhuma interação pública
        (nem da Citel nem da Ferpam).

    Nenhuma mensagem é enviada à Citel.
    """
    ativos = _citel_ativos_tv(
        df_chamados,
        df_terceiros_atual,
    )

    resultados = []
    estados_atuais = {}

    for item in ativos[:TV_MAX_CITEL]:
        ticket_citel = (
            item["ticket_citel"]
        )
        ticket_ferpam = (
            item["ticket_ferpam"]
        )

        situacao = (
            consultar_vez_resposta_citel(
                ticket_citel
            )
        )

        estado = (
            situacao.get("estado")
            if situacao.get("ok")
            else "indisponivel"
        )

        chave_estado = (
            f"{ticket_ferpam}|"
            f"{ticket_citel}"
        )

        estados_atuais[
            chave_estado
        ] = estado

        ultima_data = pd.to_datetime(
            situacao.get("ultima_data"),
            errors="coerce",
            utc=True,
        )

        dias_sem_interacao = None

        if pd.notna(ultima_data):
            dias_sem_interacao = int(
                max(
                    0,
                    (
                        agora_utc
                        - ultima_data
                    ).total_seconds()
                    // 86400,
                )
            )

        resultados.append({
            **item,
            "estado": estado,
            "titulo_estado": (
                situacao.get("titulo")
                if situacao.get("ok")
                else "Não foi possível consultar"
            ),
            "ultima_data": ultima_data,
            "dias_sem_interacao": (
                dias_sem_interacao
            ),
            "roadmap": (
                estado == "roadmap"
            ),
        })

    anterior = st.session_state.get(
        "tv_snapshot_citel"
    )

    if anterior is not None:
        for chave, estado in (
            estados_atuais.items()
        ):
            estado_antigo = anterior.get(
                chave
            )

            ticket_ferpam, ticket_citel = (
                chave.split("|", 1)
            )

            if (
                estado == "aguardando_ti"
                and estado_antigo
                != "aguardando_ti"
            ):
                _adicionar_evento_tv(
                    "citel_respondeu",
                    ticket_ferpam,
                    (
                        "Citel respondeu no "
                        f"chamado #{ticket_citel}"
                    ),
                    (
                        "O retorno agora está "
                        "com a TI. "
                        f"Ticket Ferpam "
                        f"#{ticket_ferpam}."
                    ),
                )

            elif (
                estado == "roadmap"
                and estado_antigo
                != "roadmap"
            ):
                _adicionar_evento_tv(
                    "citel_roadmap",
                    ticket_ferpam,
                    (
                        f"Chamado Citel "
                        f"#{ticket_citel} "
                        "entrou em Roadmap"
                    ),
                    (
                        "O ticket foi separado "
                        "dos chamados com resposta "
                        "pendente."
                    ),
                )

    st.session_state.tv_snapshot_citel = (
        estados_atuais
    )

    return resultados, len(ativos)


def _html_tv_alerta(
    classe,
    titulo,
    corpo="",
    meta="",
):
    titulo = html.escape(
        str(titulo or ""),
        quote=True,
    )
    corpo = html.escape(
        str(corpo or ""),
        quote=True,
    )
    meta = html.escape(
        str(meta or ""),
        quote=True,
    )

    corpo_html = (
        f'<div class="tv-alert-body">'
        f'{corpo}</div>'
        if corpo
        else ""
    )

    meta_html = (
        f'<div class="tv-alert-meta">'
        f'{meta}</div>'
        if meta
        else ""
    )

    return f"""
    <div class="tv-alert {classe}">
        <div class="tv-alert-title">
            {titulo}
        </div>
        {corpo_html}
        {meta_html}
    </div>
    """


def _render_lista_tv(
    itens_html,
    vazio,
):
    if not itens_html:
        st.markdown(
            (
                '<div class="tv-empty">'
                f'{html.escape(vazio)}'
                '</div>'
            ),
            unsafe_allow_html=True,
        )
        return

    for bloco in itens_html:
        st.markdown(
            bloco,
            unsafe_allow_html=True,
        )


def _normalizar_snapshot_citel_tv(resultados, agora_utc):
    """
    Recalcula apenas o número de dias usando o último snapshot já salvo.
    Não faz nenhuma chamada ao portal da Citel.
    """
    saida = []

    for item in list(resultados or []):
        registro = dict(item)

        ultima_data = pd.to_datetime(
            registro.get("ultima_data"),
            errors="coerce",
            utc=True,
        )

        dias_sem_interacao = None

        if pd.notna(ultima_data):
            dias_sem_interacao = int(
                max(
                    0,
                    (
                        agora_utc - ultima_data
                    ).total_seconds() // 86400,
                )
            )

        registro["ultima_data"] = ultima_data
        registro["dias_sem_interacao"] = dias_sem_interacao
        saida.append(registro)

    return saida


def _atualizar_snapshot_citel_tv(df_chamados, agora_utc):
    """
    Atualização MANUAL da Citel.

    Esta função é a única chamada pelo Modo TV que consulta o portal externo.
    O refresh automático de 60 segundos não passa por aqui.
    """
    # A aba terceiros só precisa ser atualizada quando o Admin pede
    # uma nova leitura da Citel.
    df_terc_atual = carregar_dados_terceiros()

    # Força leitura nova do estado externo quando o botão é pressionado.
    try:
        consultar_vez_resposta_citel.clear()
    except Exception:
        pass

    resultados, total_ativos = _processar_citel_tv(
        df_chamados,
        df_terc_atual,
        agora_utc,
    )

    agora_local = agora_utc.tz_convert(
        "America/Araguaina"
    )

    st.session_state["tv_citel_resultados_manual"] = resultados
    st.session_state["tv_citel_total_ativos_manual"] = total_ativos
    st.session_state["tv_citel_atualizado_em"] = agora_local.isoformat()

    registrar_auditoria_seguro(
        "ATUALIZAR_CITEL_MODO_TV",
        detalhes=(
            f"Consulta manual do Modo TV realizada para "
            f"{total_ativos} chamado(s) ativo(s) da Citel."
        ),
    )

    return resultados, total_ativos


def render_conteudo_modo_tv():
    agora_utc = pd.Timestamp.now(
        tz="UTC"
    )

    agora_local = agora_utc.tz_convert(
        "America/Araguaina"
    )

    # ========================================================
    # REFRESH AUTOMÁTICO RÁPIDO
    # ========================================================
    # Aqui carregamos SOMENTE a base interna de chamados.
    # Não consultamos a API da Citel e não recarregamos a aba terceiros.
    df_tv = carregar_dados()

    # Primeiro remove da TV qualquer aviso de ticket novo que já foi
    # assumido/tratado e deixou de estar pendente.
    _limpar_novos_chamados_nao_pendentes_tv(
        df_tv
    )

    novos_pendentes = _detectar_novos_chamados_tv(
        df_tv
    )

    # Toca UMA vez por ciclo, mesmo que vários chamados tenham entrado
    # juntos. O aviso visual continua mostrando cada ticket separadamente.
    if novos_pendentes:
        _tocar_ding_novo_chamado_tv()

    # Para o alerta interno de chamados parados, usamos as datas
    # do próprio chamado. Isso mantém o refresh leve.
    parados = _chamados_parados_tv(
        df_tv,
        pd.DataFrame(),
        agora_utc,
    )

    df_tv_status = df_tv.copy()

    if not df_tv_status.empty:
        df_tv_status[
            "grupo_status_tv"
        ] = df_tv_status[
            "status"
        ].apply(
            classificar_status_grupo
        )

    abertos = (
        int(
            (
                df_tv_status[
                    "grupo_status_tv"
                ]
                == "Abertos"
            ).sum()
        )
        if "grupo_status_tv"
        in df_tv_status.columns
        else 0
    )

    andamento = (
        int(
            (
                df_tv_status[
                    "grupo_status_tv"
                ]
                == "Em Andamento"
            ).sum()
        )
        if "grupo_status_tv"
        in df_tv_status.columns
        else 0
    )

    # ========================================================
    # CABEÇALHO
    # ========================================================
    st.markdown(
        f"""
        <div class="tv-header">
            <div>
                <div class="tv-eyebrow">
                    Central de Operação • TI Ferpam
                </div>
                <div class="tv-title">
                    📺 Modo TV
                </div>
                <div style="margin-top:8px;">
                    <span class="tv-live-pill">
                        <span class="tv-dot-live"></span>
                        Chamados internos atualizam a cada
                        {TV_REFRESH_SECONDS}s
                    </span>
                </div>
            </div>
            <div class="tv-clock">
                Última leitura interna<br>
                <strong>
                    {agora_local.strftime("%d/%m/%Y • %H:%M:%S")}
                </strong>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ========================================================
    # CITEL MANUAL
    # ========================================================
    col_citel_btn, col_citel_info = st.columns(
        [2.2, 7.8]
    )

    with col_citel_btn:
        atualizar_citel = st.button(
            "🔄 Atualizar Citel",
            key="btn_tv_atualizar_citel_manual",
            type="primary",
            use_container_width=True,
        )

    if atualizar_citel:
        with st.spinner(
            "Consultando os chamados ativos da Citel..."
        ):
            _atualizar_snapshot_citel_tv(
                df_tv,
                agora_utc,
            )

        st.toast(
            "Situação da Citel atualizada.",
            icon="✅",
        )

    snapshot_bruto = st.session_state.get(
        "tv_citel_resultados_manual",
        [],
    )

    citel_resultados = _normalizar_snapshot_citel_tv(
        snapshot_bruto,
        agora_utc,
    )

    total_citel_ativos = int(
        st.session_state.get(
            "tv_citel_total_ativos_manual",
            0,
        )
        or 0
    )

    citel_atualizado_em = pd.to_datetime(
        st.session_state.get(
            "tv_citel_atualizado_em"
        ),
        errors="coerce",
    )

    citel_consultado = bool(
        snapshot_bruto
        or st.session_state.get(
            "tv_citel_atualizado_em"
        )
    )

    with col_citel_info:
        if citel_consultado and pd.notna(
            citel_atualizado_em
        ):
            st.caption(
                "Citel fora do refresh automático • "
                f"última consulta manual: "
                f"{citel_atualizado_em.strftime('%d/%m/%Y às %H:%M:%S')} "
                f"• {total_citel_ativos} chamado(s) ativo(s) consultado(s)"
            )
        else:
            st.caption(
                "A Citel não é consultada automaticamente. "
                "Clique em **Atualizar Citel** quando quiser buscar "
                "respostas, Roadmaps e chamados há 15+ dias sem interação."
            )

    # ========================================================
    # ESTADOS DO ÚLTIMO SNAPSHOT DA CITEL
    # ========================================================
    citel_aguardando_ti = [
        r
        for r in citel_resultados
        if r.get("estado")
        == "aguardando_ti"
    ]

    citel_roadmap = [
        r
        for r in citel_resultados
        if r.get("estado")
        == "roadmap"
    ]

    citel_sem_interacao = [
        r
        for r in citel_resultados
        if (
            r.get("estado") != "roadmap"
            and r.get("estado")
            in {
                "aguardando_ti",
                "aguardando_citel",
            }
            and r.get(
                "dias_sem_interacao"
            ) is not None
            and r.get(
                "dias_sem_interacao"
            )
            >= CITEL_ALERTA_SEM_INTERACAO_DIAS
        )
    ]

    # ========================================================
    # KPIs
    # ========================================================
    k1, k2, k3, k4, k5 = st.columns(5)

    with k1:
        st.metric(
            "Abertos",
            abertos,
        )

    with k2:
        st.metric(
            "Em andamento",
            andamento,
        )

    with k3:
        st.metric(
            "🔵 Citel respondeu",
            (
                len(citel_aguardando_ti)
                if citel_consultado
                else "—"
            ),
        )

    with k4:
        st.metric(
            "🟣 Em Roadmap",
            (
                len(citel_roadmap)
                if citel_consultado
                else "—"
            ),
        )

    with k5:
        st.metric(
            (
                "⏳ Citel "
                f"{CITEL_ALERTA_SEM_INTERACAO_DIAS}+ dias"
            ),
            (
                len(citel_sem_interacao)
                if citel_consultado
                else "—"
            ),
        )

    st.caption(
        (
            "Os dois primeiros indicadores são atualizados automaticamente. "
            "Os indicadores da Citel usam somente a última consulta manual."
        )
    )

    # ========================================================
    # ACONTECEU AGORA
    # ========================================================
    # Garante também no momento da renderização que um ticket assumido
    # não fique aparecendo até o próximo ciclo.
    _limpar_novos_chamados_nao_pendentes_tv(
        df_tv
    )

    eventos = list(
        st.session_state.get(
            "tv_eventos_recentes",
            [],
        )
    )
    eventos.reverse()

    if eventos:
        st.markdown(
            (
                '<div class="tv-section-title">'
                "⚡ Aconteceu agora"
                "</div>"
            ),
            unsafe_allow_html=True,
        )

        blocos_eventos = []

        for evento in eventos[:6]:
            tipo = evento.get("tipo")

            if tipo == "novo_chamado":
                classe = "tv-alert-new"

            elif tipo == "citel_respondeu":
                classe = "tv-alert-citel"

            elif tipo == "citel_roadmap":
                classe = "tv-alert-warning"

            else:
                classe = "tv-alert-warning"

            detectado = pd.to_datetime(
                evento.get(
                    "detectado_em"
                ),
                errors="coerce",
                utc=True,
            )

            detectado_str = ""

            if pd.notna(detectado):
                detectado_str = (
                    detectado
                    .tz_convert(
                        "America/Araguaina"
                    )
                    .strftime("%H:%M")
                )

            blocos_eventos.append(
                _html_tv_alerta(
                    classe,
                    evento.get("titulo"),
                    evento.get("detalhe"),
                    (
                        "Detectado às "
                        f"{detectado_str}"
                        if detectado_str
                        else ""
                    ),
                )
            )

        _render_lista_tv(
            blocos_eventos,
            (
                "Nenhum evento novo "
                "detectado nos últimos minutos."
            ),
        )

    # ========================================================
    # QUADROS OPERACIONAIS
    # ========================================================
    (
        col_citel,
        col_roadmap,
        col_15d,
        col_parados,
    ) = st.columns(4)

    with col_citel:
        st.markdown(
            (
                '<div class="tv-section-title">'
                "🔵 Citel respondeu"
                "</div>"
            ),
            unsafe_allow_html=True,
        )

        if not citel_consultado:
            _render_lista_tv(
                [],
                "Clique em Atualizar Citel para consultar.",
            )
        else:
            blocos = []

            for item in (
                citel_aguardando_ti[:8]
            ):
                data_str = "-"

                if pd.notna(
                    item.get("ultima_data")
                ):
                    data_str = (
                        item["ultima_data"]
                        .tz_convert(
                            "America/Araguaina"
                        )
                        .strftime(
                            "%d/%m às %H:%M"
                        )
                    )

                blocos.append(
                    _html_tv_alerta(
                        "tv-alert-citel",
                        (
                            f"FerPam "
                            f"#{item['ticket_ferpam']} "
                            "• Citel "
                            f"#{item['ticket_citel']}"
                        ),
                        (
                            item.get("titulo")
                            or "Sem título"
                        ),
                        (
                            "Última resposta: "
                            f"{data_str} • Técnico: "
                            f"{item.get('tecnico') or 'Não atribuído'}"
                        ),
                    )
                )

            _render_lista_tv(
                blocos,
                (
                    "Nenhuma resposta da Citel "
                    "aguardando a TI."
                ),
            )

    with col_roadmap:
        st.markdown(
            (
                '<div class="tv-section-title">'
                "🟣 Em Roadmap"
                "</div>"
            ),
            unsafe_allow_html=True,
        )

        if not citel_consultado:
            _render_lista_tv(
                [],
                "Clique em Atualizar Citel para consultar.",
            )
        else:
            blocos = []

            for item in citel_roadmap[:8]:
                data_str = "-"

                if pd.notna(
                    item.get("ultima_data")
                ):
                    data_str = (
                        item["ultima_data"]
                        .tz_convert(
                            "America/Araguaina"
                        )
                        .strftime(
                            "%d/%m às %H:%M"
                        )
                    )

                blocos.append(
                    _html_tv_alerta(
                        "tv-alert-warning",
                        (
                            f"FerPam "
                            f"#{item['ticket_ferpam']} "
                            "• Citel "
                            f"#{item['ticket_citel']}"
                        ),
                        (
                            item.get("titulo")
                            or "Sem título"
                        ),
                        (
                            "Roadmap detectado pela "
                            "última mensagem da Citel • "
                            f"Última interação: {data_str}"
                        ),
                    )
                )

            _render_lista_tv(
                blocos,
                (
                    "Nenhum chamado ativo da "
                    "Citel identificado como Roadmap."
                ),
            )

    with col_15d:
        st.markdown(
            (
                '<div class="tv-section-title">'
                "⏳ Citel sem atualização • "
                f"{CITEL_ALERTA_SEM_INTERACAO_DIAS}+ dias"
                "</div>"
            ),
            unsafe_allow_html=True,
        )

        if not citel_consultado:
            _render_lista_tv(
                [],
                "Clique em Atualizar Citel para consultar.",
            )
        else:
            blocos = []

            for item in (
                citel_sem_interacao[:8]
            ):
                lado = (
                    "última fala: Citel"
                    if item.get("estado")
                    == "aguardando_ti"
                    else "última fala: TI/Ferpam"
                )

                blocos.append(
                    _html_tv_alerta(
                        "tv-alert-critical",
                        (
                            f"FerPam "
                            f"#{item['ticket_ferpam']} "
                            "• "
                            f"{item['dias_sem_interacao']} dias"
                        ),
                        (
                            item.get("titulo")
                            or "Sem título"
                        ),
                        (
                            f"Citel "
                            f"#{item['ticket_citel']} "
                            f"• {lado} • nenhuma "
                            "nova interação desde então"
                        ),
                    )
                )

            _render_lista_tv(
                blocos,
                (
                    "Nenhum chamado da Citel "
                    f"com {CITEL_ALERTA_SEM_INTERACAO_DIAS}+ "
                    "dias sem interação."
                ),
            )

    with col_parados:
        st.markdown(
            (
                '<div class="tv-section-title">'
                "⚠️ Chamados parados • "
                f"{TV_ALERTA_DIAS}+ dias"
                "</div>"
            ),
            unsafe_allow_html=True,
        )

        blocos = []

        for item in parados[:8]:
            blocos.append(
                _html_tv_alerta(
                    (
                        "tv-alert-critical"
                        if item["dias"] >= 10
                        else "tv-alert-warning"
                    ),
                    (
                        f"Chamado "
                        f"#{item['ticket']} "
                        "• "
                        f"{item['dias']} dias"
                    ),
                    (
                        item.get("titulo")
                        or "Sem título"
                    ),
                    (
                        f"{item.get('status') or '-'} "
                        "• Técnico: "
                        f"{item.get('tecnico') or 'Não atribuído'}"
                    ),
                )
            )

        _render_lista_tv(
            blocos,
            (
                "Nenhum chamado com "
                f"{TV_ALERTA_DIAS}+ dias "
                "sem movimentação datada."
            ),
        )

    # ========================================================
    # CHAMADOS RECENTES
    # ========================================================
    st.divider()

    st.markdown(
        (
            '<div class="tv-section-title">'
            "🆕 Chamados mais recentes"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    if df_tv.empty:
        st.info(
            "Nenhum chamado disponível."
        )

    else:
        recentes = (
            df_tv[
                df_tv[
                    "dt_abertura"
                ].notna()
            ]
            .sort_values(
                "dt_abertura",
                ascending=False,
            )
            .head(8)
        )

        cols = st.columns(4)

        for pos, (
            _,
            chamado,
        ) in enumerate(
            recentes.iterrows()
        ):
            with cols[pos % 4]:
                ticket = str(
                    chamado.get(
                        "id_chamado",
                        "",
                    ) or ""
                )

                titulo = _resumo_texto(
                    chamado.get(
                        "titulo",
                        "Sem título",
                    ),
                    85,
                )

                status = str(
                    chamado.get(
                        "status",
                        "",
                    )
                    or "Aberto"
                )

                tecnico = str(
                    chamado.get(
                        "tecnico",
                        "",
                    )
                    or "Não atribuído"
                )

                dt = (
                    _normalizar_data_timeline(
                        chamado.get(
                            "dt_abertura"
                        )
                    )
                )

                dt_str = "-"

                if dt is not None:
                    dt_str = (
                        dt.tz_convert(
                            "America/Araguaina"
                        )
                        .strftime(
                            "%d/%m • %H:%M"
                        )
                    )

                st.markdown(
                    _html_tv_alerta(
                        "tv-alert-new",
                        (
                            f"#{ticket} "
                            f"• {titulo}"
                        ),
                        status,
                        (
                            f"{dt_str} "
                            f"• {tecnico}"
                        ),
                    ),
                    unsafe_allow_html=True,
                )

    if (
        citel_consultado
        and total_citel_ativos > TV_MAX_CITEL
    ):
        st.caption(
            (
                f"⚠️ Existem "
                f"{total_citel_ativos} "
                "chamados ativos da Citel. "
                "A consulta manual processa no máximo "
                f"{TV_MAX_CITEL} por vez."
            )
        )



def render_modo_tv():
    if not st.session_state.get(
        "autenticado_admin"
    ):
        st.error(
            "⛔ O Modo TV é exclusivo "
            "para o Admin."
        )
        return

    st.markdown(
        """
        <style>
            section[data-testid="stSidebar"] {
                display: none !important;
            }

            [data-testid="collapsedControl"] {
                display: none !important;
            }

            header[data-testid="stHeader"] {
                display: none !important;
            }

            /* O som de novo chamado toca sem exibir o player na TV. */
            div[data-testid="stAudio"] {
                display: none !important;
            }

            .block-container {
                padding-top: 1.1rem !important;
                padding-left: 1.5rem !important;
                padding-right: 1.5rem !important;
                max-width: 100% !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

    _, col_sair = st.columns(
        [9, 1]
    )

    with col_sair:
        if st.button(
            "← Dashboard",
            key="btn_sair_modo_tv",
            use_container_width=True,
        ):
            st.session_state.tela = (
                "dashboard"
            )
            st.rerun()

    fragment = getattr(
        st,
        "fragment",
        None,
    )

    if fragment is None:
        fragment = getattr(
            st,
            "experimental_fragment",
            None,
        )

    if fragment is None:
        st.warning(
            (
                "Sua versão do Streamlit "
                "não possui suporte a fragments. "
                "O Modo TV está funcionando, "
                "mas sem atualização automática."
            )
        )
        render_conteudo_modo_tv()
        return

    @fragment(
        run_every=TV_REFRESH_SECONDS
    )
    def _tv_live_fragment():
        render_conteudo_modo_tv()

    _tv_live_fragment()


# ============================================================
# TELA DETALHES DO TICKET
# ============================================================

if st.session_state.tela == "ticket" and st.session_state.ticket_aberto is not None:
    ticket_id = str(st.session_state.ticket_aberto).strip()
    resultado = df[df["id_chamado"].str.casefold() == ticket_id.casefold()]
    if resultado.empty:
        st.error(f"Não foi possível encontrar o ticket #{ticket_id}.")
        st.button("← Voltar", on_click=voltar_busca)
        st.stop()

    chamado = resultado.iloc[0]
    percentual, etapa_nome = calcular_progresso(chamado)
    st.button("← Voltar", on_click=voltar_busca)
    st.title(f"🎫 Ticket #{ticket_id}")
    st.caption(f"Solicitante: {chamado.get('solicitante', 'N/A')}")
    st.subheader("📌 Progresso da Resolução")
    st.markdown(render_barra_progresso(percentual, etapa_nome), unsafe_allow_html=True)
    
    if chamado.get("eh_roadmap"):
        st.warning("🚀 **Este chamado é considerado ROADMAP (Tempo total superior a 6 dias).**")

    # Se este chamado estiver vinculado à Citel, mostra apenas de quem é a vez
    # de responder no chamado externo.
    render_acompanhamento_citel(chamado)

    st.divider()

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**Status Atual**")
        st.markdown(get_status_badge(chamado["status"]), unsafe_allow_html=True)
        st.write("")
        st.markdown("**👤 Solicitante**")
        st.write(chamado.get("solicitante") or "-")
    with col2:
        st.markdown("**⚠️ Prioridade**")
        st.write(chamado.get("prioridade") or "-")
        st.markdown("**🏢 Departamento**")
        st.write(chamado.get("departamento") or "-")
    with col3:
        st.markdown("**👨‍💻 Técnico Responsável**")
        st.write(chamado.get("tecnico") or "Ainda não atribuído")
        st.markdown("**📍 Cidade**")
        st.write(chamado.get("cidade") or "-")

    st.divider()

    st.subheader("⏱️ Tempos de Atendimento do Chamado")
    if chamado.get("sla_valido"):
        t1, t2, t3 = st.columns(3)
        with t1:
            st.metric("⏳ Tempo até Atendimento", formatar_tempo(chamado.get("min_ate_tecnico")))
        with t2:
            st.metric("🔧 Tempo Execução/Técnico", formatar_tempo(chamado.get("min_resolucao")))
        with t3:
            st.metric("🏁 Tempo Total de Conclusão", formatar_tempo(chamado.get("min_total")))
    else:
        st.info("ℹ️ Para exibir as métricas completas de SLA, é necessário que as 3 datas (Abertura, Início Técnico e Conclusão) estejam registradas na planilha.")

    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("📋 Detalhes da Solicitação")
        st.markdown(f"**Título:** {chamado.get('titulo') or '-'}")
        ocorrencia = str(chamado.get("ocorrencia", "")).strip()
        st.info(ocorrencia if ocorrencia and ocorrencia.casefold() != "nan" else "Nenhuma descrição fornecida.")
    with col_b:
        st.subheader("🔧 Resolução / Atividade Realizada")
        atividade = str(chamado.get("atividade_realizada", "")).strip()
        st.success(atividade if atividade and atividade.casefold() != "nan" else "Ainda não há atividades registradas para este chamado.")

    # Ferramentas extras visíveis somente no modo administrativo.
    render_ferramentas_admin_ticket(chamado)

    nota = chamado.get("nota_atendimento", "")
    data_aval = str(chamado.get("data_avaliacao", "")).strip()
    coment_aval = str(chamado.get("comentario_avaliacao", "")).strip()

    if (pd.notna(chamado.get("nota_num")) and chamado.get("nota_num") > 0) or (coment_aval and coment_aval.casefold() != "nan"):
        st.divider()
        st.subheader("⭐ Avaliação do Atendimento")
        col_eval1, col_eval2 = st.columns([1, 2])
        with col_eval1:
            if pd.notna(chamado.get("nota_num")):
                estrelas = render_estrelas(chamado["nota_num"])
                if estrelas: st.markdown(f"### {estrelas}")
            if data_aval and data_aval.casefold() != "nan":
                st.caption(f"🗓️ Avaliado em: {data_aval}")
        with col_eval2:
            if coment_aval and coment_aval.casefold() != "nan":
                st.markdown("💬 **Comentário do Solicitante:**")
                st.write(f'"{coment_aval}"')
    st.stop()

# ============================================================
# TELA DE BUSCA DE CHAMADOS
# ============================================================

if st.session_state.tela == "busca":
    st.title("🎫 Portal de Consulta de Chamados")
    if not st.session_state.autenticado_admin:
        st.write("Digite o **Número do Chamado** ou o **Seu Nome** e escolha o status para consultar.")
        c1, c2, c3 = st.columns([1.5, 2, 1.5])
        with c1: input_ticket = st.text_input("Número do Chamado", placeholder="Ex.: 933")
        with c2: input_nome = st.text_input("Seu Nome (Solicitante)", placeholder="Ex.: Carla")
        with c3: input_status = st.selectbox("Status / Pendência", options=lista_status_opcoes, key="usr_status")
        btn_pesquisar = st.button("🔍 Pesquisar Chamado", type="primary", use_container_width=True)

        if btn_pesquisar or input_ticket.strip() or input_nome.strip() or input_status != "Todos os Status":
            res = df.copy()
            if input_ticket.strip(): res = res[res["id_chamado"].str.contains(input_ticket.strip(), case=False, na=False)]
            if input_nome.strip(): res = res[res["solicitante"].str.contains(input_nome.strip(), case=False, na=False)]
            if input_status != "Todos os Status": res = res[res["status"].str.casefold() == input_status.casefold()]

            st.divider()
            if not input_ticket.strip() and not input_nome.strip() and input_status == "Todos os Status":
                st.info("💡 Informe o número do ticket, seu nome ou escolha um status para iniciar.")
            elif res.empty:
                st.warning("Nenhum chamado foi encontrado com esses critérios.")
            else:
                st.subheader(f"Localizado(s) {len(res)} chamado(s):")
                for idx, cham in res.reset_index(drop=True).iterrows():
                    t_id = str(cham["id_chamado"]).strip()
                    pct, status_txt = calcular_progresso(cham)
                    badge_html = get_status_badge(cham.get("status", ""))
                    bar_html = render_barra_progresso(pct, status_txt)
                    
                    solic = cham.get('solicitante') or 'Não Informado'
                    dep = cham.get('departamento') or 'Geral'
                    tit = cham.get('titulo') or 'Sem Título'
                    
                    with st.container(border=True):
                        col1, col2 = st.columns([7, 3])
                        with col1:
                            st.markdown(f"""
                            <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 6px;">
                                <span style="font-size: 1.2rem; font-weight: 800;">🎫 #{t_id}</span>
                                {badge_html}
                            </div>
                            <div style="font-size: 1rem; font-weight: 700; margin-bottom: 4px;">{tit}</div>
                            <div style="font-size: 0.85rem; color: #94a3b8;">👤 {solic} | 🏢 {dep}</div>
                            """, unsafe_allow_html=True)
                            st.markdown(bar_html, unsafe_allow_html=True)
                        with col2:
                            st.write("")
                            st.write("")
                            st.button("👁️ Ver detalhes", key=f"btn_usr_{t_id}_{idx}", on_click=abrir_ticket, args=(t_id,), use_container_width=True)
    else:
        st.write("🔧 **Painel Admin**: Filtragem global de chamados.")
        c1, c2, c3 = st.columns([1.5, 2, 1.5])
        with c1: input_ticket_admin = st.text_input("Número do Ticket", placeholder="Ex.: 933")
        with c2: input_solic_admin = st.selectbox("Filtrar por Solicitante", options=["Todos"] + lista_solicitantes_admin)
        with c3: input_status_admin = st.selectbox("Status / Pendência", options=lista_status_opcoes, key="adm_status")
        res = df.copy()
        if input_ticket_admin.strip(): res = res[res["id_chamado"].str.contains(input_ticket_admin.strip(), case=False, na=False)]
        if input_solic_admin != "Todos": res = res[res["solicitante"].str.casefold() == input_solic_admin.casefold()]
        if input_status_admin != "Todos os Status": res = res[res["status"].str.casefold() == input_status_admin.casefold()]

        st.divider()
        if res.empty:
            st.warning("Nenhum chamado encontrado com estes filtros.")
        else:
            st.subheader(f"Total na consulta: {len(res)} chamado(s)")
            for idx, cham in res.reset_index(drop=True).iterrows():
                t_id = str(cham["id_chamado"]).strip()
                pct, status_txt = calcular_progresso(cham)
                badge_html = get_status_badge(cham.get("status", ""))
                bar_html = render_barra_progresso(pct, status_txt)
                
                solic = cham.get('solicitante') or 'Não Informado'
                dep = cham.get('departamento') or 'Geral'
                tit = cham.get('titulo') or 'Sem Título'

                with st.container(border=True):
                    col1, col2 = st.columns([7, 3])
                    with col1:
                        st.markdown(f"""
                        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 6px;">
                            <span style="font-size: 1.2rem; font-weight: 800;">🎫 #{t_id}</span>
                            {badge_html}
                        </div>
                        <div style="font-size: 1rem; font-weight: 700;">{tit}</div>
                        <div style="font-size: 0.85rem; color: #94a3b8;">👤 {solic} | 🏢 {dep}</div>
                        """, unsafe_allow_html=True)
                        st.markdown(bar_html, unsafe_allow_html=True)
                    with col2:
                        st.write("")
                        st.write("")
                        st.button("👁️ Ver detalhes", key=f"btn_adm_{t_id}_{idx}", on_click=abrir_ticket, args=(t_id,), use_container_width=True)

# ============================================================
# TELA MODO TV
# ============================================================

if st.session_state.tela == "tv":
    if not st.session_state.autenticado_admin:
        st.session_state.tela = "busca"
        st.error("⛔ Acesso negado ao Modo TV.")
        st.stop()

    render_modo_tv()
    st.stop()


# ============================================================
# TELA DASHBOARD DE INDICADORES
# ============================================================

if st.session_state.tela == "dashboard":
    if not st.session_state.autenticado_admin:
        st.error("⛔ Acesso Negado! Faça login como admin no menu lateral para visualizar o Dashboard.")
        st.stop()

    st.title("📊 Dashboard & Indicadores de TI")

    def aplicar_layout_plotly(fig):
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#f8fafc"),
            margin=dict(t=30, b=20, l=20, r=20)
        )
        return fig

    tab_op, tab_sla, tab_csat, tab_reviews, tab_gestao = st.tabs([
        "📊 Operação & Volumetria", 
        "⏱️ SLAs & Médias de Tempo",
        "⭐ Satisfação & Notas (CSAT)", 
        "💬 Feed de Reviews & Feedback",
        "🧠 Gestão TI"
    ])

    # ============================================================
    # TAB 1: OPERAÇÃO & VOLUMETRIA
    # ============================================================
    with tab_op:
        st.caption("⚡ **Filtre por Ano/Mês** ou clique nos gráficos para detalhar a operação!")

        anos_disponiveis = sorted([int(a) for a in df["ano_abertura"].dropna().unique()], reverse=True)
        opcoes_anos = ["Todos os Anos"] + anos_disponiveis
        
        f_col1, f_col2, f_col3 = st.columns([2, 2, 4])
        with f_col1:
            ano_sel = st.selectbox("📅 Escolha o Ano", options=opcoes_anos, index=0)

        if ano_sel == "Todos os Anos":
            df_ano = df.copy()
        else:
            df_ano = df[df["ano_abertura"] == ano_sel]

        meses_nums = sorted([int(m) for m in df_ano["mes_num_abertura"].dropna().unique()])
        opcoes_meses = ["Todos os Meses"] + [MESES_DIC[m] for m in meses_nums if m in MESES_DIC]

        with f_col2:
            mes_sel = st.selectbox("🗓️ Escolha o Mês", options=opcoes_meses, index=0)

        df_op_base = df_ano.copy()
        if mes_sel != "Todos os Meses":
            df_op_base = df_op_base[df_op_base["mes_nome_abertura"] == mes_sel]

        st.divider()

        # Base do período selecionado (Ano/Mês).
        df_dash_base = df_op_base.copy()
        df_dash_base["grupo_status"] = df_dash_base["status"].apply(classificar_status_grupo)

        # O filtro clicado agora é aplicado ANTES dos KPIs e dos gráficos.
        # Assim toda a visualização se recalcula, e não apenas a tabela final.
        tipo_f = st.session_state.filtro_dash_tipo
        val_f = st.session_state.filtro_dash_valor

        df_dash = df_dash_base.copy()

        if tipo_f and val_f:
            if tipo_f == "status_grupo":
                df_dash = df_dash[df_dash["grupo_status"] == val_f]
            elif tipo_f == "status":
                df_dash = df_dash[df_dash["status"].str.casefold() == str(val_f).casefold()]
            elif tipo_f == "prioridade":
                df_dash = df_dash[df_dash["prioridade"].str.casefold() == str(val_f).casefold()]
            elif tipo_f == "departamento":
                df_dash = df_dash[df_dash["departamento"].str.casefold() == str(val_f).casefold()]
            elif tipo_f == "tecnico":
                df_dash = df_dash[df_dash["tecnico"].str.casefold() == str(val_f).casefold()]
            elif tipo_f == "titulo":
                df_dash = df_dash[df_dash["titulo"].str.casefold() == str(val_f).casefold()]

        # Todos os componentes abaixo usam a MESMA base filtrada.
        df_filtrado_exibir = df_dash.copy()

        total_chamados = len(df_dash)
        concluidos = len(df_dash[df_dash["grupo_status"] == "Concluídos"])
        em_andamento = len(df_dash[df_dash["grupo_status"] == "Em Andamento"])
        pendentes = len(df_dash[df_dash["grupo_status"] == "Abertos"])
        taxa_conclusao = (concluidos / total_chamados * 100) if total_chamados > 0 else 0

        m1, m2, m3, m4, m5 = st.columns(5)

        with m1:
            st.metric("Total Chamados", total_chamados)
            if st.button("👁️ Ver Todos", key="btn_kpi_total", use_container_width=True):
                limpar_filtro_dash()
                st.rerun()

        with m2:
            st.metric("🟢 Concluídos", concluidos)
            if st.button("🔍 Concluídos", key="btn_kpi_concluidos", use_container_width=True, type=("primary" if st.session_state.filtro_dash_valor == "Concluídos" else "secondary")):
                st.session_state.filtro_dash_tipo = "status_grupo"
                st.session_state.filtro_dash_valor = "Concluídos"
                st.rerun()

        with m3:
            st.metric("🔵 Em Andamento", em_andamento)
            if st.button("🔍 Ver Andamento", key="btn_kpi_andamento", use_container_width=True, type=("primary" if st.session_state.filtro_dash_valor == "Em Andamento" else "secondary")):
                st.session_state.filtro_dash_tipo = "status_grupo"
                st.session_state.filtro_dash_valor = "Em Andamento"
                st.rerun()

        with m4:
            st.metric("🟡 Abertos", pendentes)
            if st.button("🔍 Abertos", key="btn_kpi_abertos", use_container_width=True, type=("primary" if st.session_state.filtro_dash_valor == "Abertos" else "secondary")):
                st.session_state.filtro_dash_tipo = "status_grupo"
                st.session_state.filtro_dash_valor = "Abertos"
                st.rerun()

        with m5:
            st.metric("📈 Taxa Resolução", f"{taxa_conclusao:.1f}%")

        df_andamento_only = df_dash[df_dash["grupo_status"] == "Em Andamento"]
        detalhe_status_andamento = df_andamento_only["status"].replace("", "Em Atendimento").value_counts()

        st.markdown("#### 📂 Divisão dos Chamados Em Andamento por Status:")
        if not detalhe_status_andamento.empty:
            cols_sub = st.columns(min(len(detalhe_status_andamento), 6))
            for i, (st_nome, st_qtd) in enumerate(detalhe_status_andamento.items()):
                col_target = cols_sub[i % len(cols_sub)]
                with col_target:
                    is_active = (st.session_state.filtro_dash_tipo == "status" and st.session_state.filtro_dash_valor == st_nome)
                    btn_type = "primary" if is_active else "secondary"
                    if st.button(f"📌 {st_nome}\n\n**{st_qtd}**", key=f"btn_sub_st_{i}", use_container_width=True, type=btn_type):
                        st.session_state.filtro_dash_tipo = "status"
                        st.session_state.filtro_dash_valor = st_nome
                        st.rerun()
        else:
            st.info("Nenhum chamado em andamento no momento.")

        st.divider()

        if tipo_f and val_f:
            nomes_filtros = {
                "status_grupo": "STATUS",
                "status": "STATUS",
                "prioridade": "PRIORIDADE",
                "departamento": "DEPARTAMENTO",
                "tecnico": "TÉCNICO",
                "titulo": "TÍTULO",
            }
            nome_filtro_ativo = nomes_filtros.get(tipo_f, str(tipo_f).upper())
            st.info(
                f"🔎 **Filtro ativo no Dashboard:** {nome_filtro_ativo} = "
                f"**{val_f}** ({len(df_filtrado_exibir)} chamados)"
            )
            if st.button("❌ Limpar Filtro Selecionado", type="secondary"):
                limpar_filtro_dash()
                st.rerun()

        g1, g2 = st.columns(2)
        with g1:
            st.subheader("🍩 Distribuição por Status")
            st_counts = df_dash["status"].replace("", "Não informado").value_counts().reset_index()
            st_counts.columns = ["Status", "Quantidade"]
            fig_status = px.pie(
                st_counts, names="Status", values="Quantidade",
                hole=0.5, color_discrete_sequence=px.colors.qualitative.Set2
            )
            fig_status = aplicar_layout_plotly(fig_status)
            ev_status = st.plotly_chart(fig_status, use_container_width=True, on_select="rerun", selection_mode="points")
            processar_clique_grafico(ev_status, "status")

        with g2:
            st.subheader("📊 Distribuição por Prioridade")
            prio_counts = df_dash["prioridade"].replace("", "Não informada").value_counts().reset_index()
            prio_counts.columns = ["Prioridade", "Quantidade"]
            fig_prio = px.bar(
                prio_counts, x="Prioridade", y="Quantidade",
                color="Prioridade", color_discrete_sequence=px.colors.qualitative.Pastel
            )
            fig_prio = aplicar_layout_plotly(fig_prio)
            ev_prio = st.plotly_chart(fig_prio, use_container_width=True, on_select="rerun", selection_mode="points")
            processar_clique_grafico(ev_prio, "prioridade")

        g3, g4 = st.columns(2)
        with g3:
            st.subheader("🏢 Top Departamentos")
            dep_counts = df_dash["departamento"].replace("", "Outros").value_counts().head(10).reset_index()
            dep_counts.columns = ["Departamento", "Quantidade"]
            fig_dep = px.bar(
                dep_counts, x="Quantidade", y="Departamento",
                orientation="h", color_discrete_sequence=["#38bdf8"]
            )
            fig_dep = aplicar_layout_plotly(fig_dep)
            ev_dep = st.plotly_chart(fig_dep, use_container_width=True, on_select="rerun", selection_mode="points")
            processar_clique_grafico(ev_dep, "departamento")

        with g4:
            st.subheader("👨‍💻 Chamados por Técnico")
            tec_counts = df_dash["tecnico"].replace("", "Não Atribuído").value_counts().head(10).reset_index()
            tec_counts.columns = ["Técnico", "Quantidade"]
            fig_tec = px.bar(
                tec_counts, x="Quantidade", y="Técnico",
                orientation="h", color_discrete_sequence=[AZUL_FERPAM]
            )
            fig_tec = aplicar_layout_plotly(fig_tec)
            ev_tec = st.plotly_chart(fig_tec, use_container_width=True, on_select="rerun", selection_mode="points")
            processar_clique_grafico(ev_tec, "tecnico")

        st.divider()

        st.subheader("🏷️ Chamados por Título")
        st.caption(
            "Clique em uma barra para filtrar todo o dashboard por aquele título."
        )

        titulo_counts = (
            df_dash["titulo"]
            .replace("", "Sem título")
            .value_counts()
            .reset_index()
        )
        titulo_counts.columns = ["Título", "Quantidade"]

        if not titulo_counts.empty:
            limite_titulos_grafico = 15
            titulo_counts_grafico = titulo_counts.head(limite_titulos_grafico).copy()
            titulo_counts_grafico = titulo_counts_grafico.sort_values(
                "Quantidade", ascending=True
            )

            altura_titulos = max(
                360,
                min(680, 90 + len(titulo_counts_grafico) * 34)
            )

            fig_titulos = px.bar(
                titulo_counts_grafico,
                x="Quantidade",
                y="Título",
                orientation="h",
                text="Quantidade",
                custom_data=["Título"],
                color_discrete_sequence=[AZUL_FERPAM],
            )

            fig_titulos.update_traces(
                textposition="outside",
                cliponaxis=False,
                hovertemplate="<b>%{y}</b><br>Chamados: %{x}<extra></extra>",
            )

            fig_titulos.update_layout(
                height=altura_titulos,
                showlegend=False,
                margin=dict(l=20, r=45, t=10, b=20),
                yaxis=dict(title="", automargin=True),
                xaxis=dict(title="Quantidade de chamados", rangemode="tozero"),
            )

            fig_titulos = aplicar_layout_plotly(fig_titulos)

            ev_titulos = st.plotly_chart(
                fig_titulos,
                use_container_width=True,
                on_select="rerun",
                selection_mode="points",
                key="grafico_titulos_dashboard",
            )

            processar_clique_grafico(ev_titulos, "titulo")

            if len(titulo_counts) > limite_titulos_grafico:
                st.caption(
                    f"Exibindo os {limite_titulos_grafico} títulos mais frequentes "
                    f"de {len(titulo_counts)} títulos encontrados."
                )

            with st.expander("📋 Ver ranking completo de títulos", expanded=False):
                ranking_titulos = titulo_counts.copy()
                ranking_titulos.insert(
                    0,
                    "Posição",
                    range(1, len(ranking_titulos) + 1)
                )
                st.dataframe(
                    ranking_titulos,
                    use_container_width=True,
                    hide_index=True,
                )
        else:
            st.info("Nenhum título encontrado para os critérios selecionados.")

        st.divider()

        st.subheader("📋 Detalhamento dos Chamados (Consulta Rápida)")
        if not df_filtrado_exibir.empty:
            df_table = df_filtrado_exibir[[
                "id_chamado", "status", "solicitante", "titulo", "tecnico", "departamento"
            ]].copy()
            df_table.columns = ["Ticket", "Status", "Solicitante", "Título", "Técnico", "Departamento"]
            st.dataframe(df_table, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum chamado para exibir na tabela com os critérios selecionados.")

    # ============================================================
    # TAB 2: SLAs & TEMPOS MÉDIOS
    # ============================================================
    with tab_sla:
        st.subheader("⏱️ SLA & Métricas de Tempo (Chamados Operacionais)")
        st.caption("Esta aba exibe as métricas limpas, ignorando chamados de longa duração catalogados como **Roadmap**.")
        
        df_sla_base = df[df["sla_valido"] == True].copy()
        
        df_sla_operacional = df_sla_base[df_sla_base["eh_roadmap"] == False]
        df_roadmap = df_sla_base[df_sla_base["eh_roadmap"] == True]
        
        if df_sla_operacional.empty:
            st.warning("Não há chamados operacionais com as 3 datas completas para gerar estatísticas de SLA.")
        else:
            s1, s2, s3 = st.columns(3)
            with s1:
                st.metric("⏱️ Méd. Tempo até Atendimento", formatar_tempo(df_sla_operacional["min_ate_tecnico"].mean()))
            with s2:
                st.metric("🔧 Méd. Tempo de Execução", formatar_tempo(df_sla_operacional["min_resolucao"].mean()))
            with s3:
                st.metric("🏁 Méd. Tempo Total de Conclusão", formatar_tempo(df_sla_operacional["min_total"].mean()))

            st.divider()

            st.subheader("👨‍💻 Desempenho e SLA Operacional por Técnico")
            st.caption("Clique no número de chamados de um técnico para visualizar a lista completa dos seus tickets operacionais.")
            
            df_tec_sla = (
                df_sla_operacional.groupby("tecnico")
                .agg(
                    Chamados=("id_chamado", "count"),
                    min_resp=("min_ate_tecnico", "mean"),
                    min_exec=("min_resolucao", "mean"),
                    min_total=("min_total", "mean")
                )
                .reset_index()
            )
            
            df_tec_sla = df_tec_sla[df_tec_sla["tecnico"].str.strip() != ""].sort_values(by="Chamados", ascending=False)
            
            if not df_tec_sla.empty:
                col_t1, col_t2 = st.columns([1.3, 1])
                
                with col_t1:
                    c_head1, c_head2, c_head3, c_head4, c_head5 = st.columns([2.5, 1.5, 2, 2, 2])
                    c_head1.markdown("**Técnico**")
                    c_head2.markdown("**Chamados**")
                    c_head3.markdown("**Atendimento**")
                    c_head4.markdown("**Execução**")
                    c_head5.markdown("**Total**")
                    
                    st.divider()
                    
                    for idx_tec, r_tec in df_tec_sla.iterrows():
                        t_nome = r_tec["tecnico"]
                        t_qtd = int(r_tec["Chamados"])
                        t_resp = formatar_tempo(r_tec["min_resp"])
                        t_exec = formatar_tempo(r_tec["min_exec"])
                        t_tot = formatar_tempo(r_tec["min_total"])
                        
                        is_sel = (st.session_state.tecnico_sla_selecionado == t_nome)
                        btn_tipo = "primary" if is_sel else "secondary"
                        
                        c_r1, c_r2, c_r3, c_r4, c_r5 = st.columns([2.5, 1.5, 2, 2, 2])
                        c_r1.write(f"**{t_nome}**")
                        
                        if c_r2.button(f"🔍 {t_qtd}", key=f"btn_tec_sla_{idx_tec}", type=btn_tipo, use_container_width=True):
                            if is_sel:
                                st.session_state.tecnico_sla_selecionado = None
                            else:
                                st.session_state.tecnico_sla_selecionado = t_nome
                            st.rerun()
                            
                        c_r3.write(t_resp)
                        c_r4.write(t_exec)
                        c_r5.write(t_tot)
                    
                with col_t2:
                    fig_sla_tec = px.bar(
                        df_tec_sla,
                        x="tecnico",
                        y="min_total",
                        title="Tempo Médio Total de Conclusão",
                        labels={"min_total": "Minutos", "tecnico": "Técnico"},
                        color="tecnico",
                        color_discrete_sequence=[AZUL_FERPAM, "#38bdf8", "#10b981"]
                    )
                    fig_sla_tec = aplicar_layout_plotly(fig_sla_tec)
                    fig_sla_tec.update_layout(showlegend=False)
                    ev_sla = st.plotly_chart(fig_sla_tec, use_container_width=True, on_select="rerun", selection_mode="points")
                    
                    tec_graf = extrair_valor_clicado(ev_sla)
                    if tec_graf and tec_graf != st.session_state.tecnico_sla_selecionado:
                        st.session_state.tecnico_sla_selecionado = tec_graf
                        st.rerun()

            if st.session_state.tecnico_sla_selecionado:
                tec_ativo = st.session_state.tecnico_sla_selecionado
                st.divider()
                
                col_titulo_filtro, col_btn_fechar = st.columns([8, 2])
                with col_titulo_filtro:
                    st.markdown(f"### 📋 Chamados Operacionais de **{tec_ativo}**")
                with col_btn_fechar:
                    if st.button("❌ Limpar Seleção", use_container_width=True):
                        st.session_state.tecnico_sla_selecionado = None
                        st.rerun()
                
                df_tec_chamados = df_sla_operacional[df_sla_operacional["tecnico"].str.casefold() == tec_ativo.casefold()]
                
                if df_tec_chamados.empty:
                    st.info(f"Nenhum chamado operacional encontrado para {tec_ativo}.")
                else:
                    st.caption(f"Exibindo **{len(df_tec_chamados)}** chamado(s) com SLA calculado:")
                    
                    for idx_c, item_c in df_tec_chamados.reset_index(drop=True).iterrows():
                        t_id_c = str(item_c["id_chamado"]).strip()
                        tit_c = item_c.get("titulo") or "Sem título"
                        solic_c = item_c.get("solicitante") or "-"
                        
                        t_resp_c = formatar_tempo(item_c.get("min_ate_tecnico"))
                        t_exec_c = formatar_tempo(item_c.get("min_resolucao"))
                        t_tot_c = formatar_tempo(item_c.get("min_total"))
                        
                        with st.container(border=True):
                            col_c1, col_c2, col_c3 = st.columns([5, 3, 2])
                            with col_c1:
                                st.markdown(f"**🎫 #{t_id_c} - {tit_c}**")
                                st.caption(f"👤 Solicitante: **{solic_c}** | 🏢 {item_c.get('departamento') or '-'}")
                            with col_c2:
                                st.markdown(f"⏱️ **Atend.:** {t_resp_c} | 🔧 **Exec.:** {t_exec_c}")
                                st.markdown(f"🏁 **Total:** `{t_tot_c}`")
                            with col_c3:
                                st.write("")
                                st.button("👁️ Ver detalhes", key=f"btn_sla_dt_{t_id_c}_{idx_c}", on_click=abrir_ticket, args=(t_id_c,), use_container_width=True)

        st.divider()

        st.subheader("🚀 Projetos & Chamados de Roadmap (> 6 dias)")
        if df_roadmap.empty:
            st.info("Nenhum chamado categorizado como Roadmap no período.")
        else:
            st.caption(f"Total de chamados de Roadmap identificados: **{len(df_roadmap)}**")
            rm1, rm2, rm3 = st.columns(3)
            with rm1:
                st.metric("⏱️ Méd. Resposta Roadmap", formatar_tempo(df_roadmap["min_ate_tecnico"].mean()))
            with rm2:
                st.metric("🔧 Méd. Execução Roadmap", formatar_tempo(df_roadmap["min_resolucao"].mean()))
            with rm3:
                st.metric("🏁 Méd. Total Conclusão Roadmap", formatar_tempo(df_roadmap["min_total"].mean()))

    # ============================================================
    # TAB 3: SATISFAÇÃO & NOTAS (CSAT)
    # ============================================================
    with tab_csat:
        st.subheader("⭐ Indicadores de Satisfação do Usuário (CSAT)")
        
        df_avaliados = df[df["nota_num"].notna() & (df["nota_num"] > 0)].copy()

        if df_avaliados.empty:
            st.warning("Nenhum atendimento avaliado foi encontrado até o momento.")
        else:
            c_m1, c_m2, c_m3 = st.columns(3)
            media_csat = df_avaliados["nota_num"].mean()
            total_aval = len(df_avaliados)
            otimos = len(df_avaliados[df_avaliados["nota_num"] >= 4])
            pct_otimo = (otimos / total_aval * 100) if total_aval > 0 else 0

            with c_m1:
                st.metric("⭐ Média CSAT Geral", f"{media_csat:.2f} / 5.00")
            with c_m2:
                st.metric("💬 Total de Avaliações", total_aval)
            with c_m3:
                st.metric("💚 Atendimentos Ótimos (4-5★)", f"{pct_otimo:.1f}%")

            st.divider()

            csat_g1, csat_g2 = st.columns(2)
            with csat_g1:
                st.subheader("📊 Distribuição das Notas (Estrelas)")
                nota_dist = df_avaliados["nota_num"].value_counts().reset_index()
                nota_dist.columns = ["Nota", "Quantidade"]
                nota_dist = nota_dist.sort_values(by="Nota", ascending=False)
                fig_notas = px.bar(
                    nota_dist, x="Nota", y="Quantidade",
                    color="Nota", color_continuous_scale=px.colors.sequential.Teal
                )
                fig_notas = aplicar_layout_plotly(fig_notas)
                st.plotly_chart(fig_notas, use_container_width=True)

            with csat_g2:
                st.subheader("👨‍💻 Média de CSAT por Técnico")
                tec_csat = df_avaliados.groupby("tecnico")["nota_num"].mean().reset_index()
                tec_csat.columns = ["Técnico", "Média CSAT"]
                tec_csat = tec_csat.sort_values(by="Média CSAT", ascending=True)
                fig_tec_csat = px.bar(
                    tec_csat, x="Média CSAT", y="Técnico",
                    orientation="h", color="Média CSAT", color_continuous_scale="Blues"
                )
                fig_tec_csat = aplicar_layout_plotly(fig_tec_csat)
                st.plotly_chart(fig_tec_csat, use_container_width=True)

    # ============================================================
    # TAB 4: FEED DE REVIEWS & FEEDBACK
    # ============================================================
    with tab_reviews:
        st.subheader("💬 Histórico Recente de Feedbacks dos Usuários")
        
        df_feed = df[
            (df["nota_num"].notna() & (df["nota_num"] > 0)) |
            (df["comentario_avaliacao"].str.strip() != "")
        ].copy()

        df_feed = df_feed.sort_values(by="dt_aval_parsed", ascending=False)

        if df_feed.empty:
            st.info("Nenhuma avaliação com comentário foi enviada recentemente.")
        else:
            for idx, item in df_feed.iterrows():
                t_id = str(item["id_chamado"]).strip()
                n_str = render_estrelas(item.get("nota_num"))
                texto_aval = str(item.get("comentario_avaliacao", "")).strip()
                data_aval_str = item.get("data_avaliacao", "Data N/D")

                with st.container(border=True):
                    col1, col2 = st.columns([8, 2])
                    with col1:
                        st.markdown(f"**🎫 #{t_id} | {item.get('titulo') or 'Sem Título'}**")
                        if n_str:
                            st.markdown(f"**Avaliação:** {n_str}")
                        if texto_aval and texto_aval.casefold() != "nan":
                            st.markdown(f"> *\"{texto_aval}\"*")
                        st.caption(f"👤 Solicitante: **{item.get('solicitante') or '-'}** | 👨‍💻 Técnico: **{item.get('tecnico') or 'Não informado'}**")
                    with col2:
                        st.write("")
                        st.caption(f"📅 {data_aval_str}")
                        st.button("👁️ Ver Ticket", key=f"btn_feed_{t_id}_{idx}", on_click=abrir_ticket, args=(t_id,), use_container_width=True)

    # ============================================================
    # TAB 5: GESTÃO TI - ADMINISTRATIVO
    # ============================================================
    with tab_gestao:
        st.subheader("🧠 Gestão TI — visão administrativa")
        st.caption("Tendências, recorrências, terceiros e auditoria. Esta área só existe no modo Admin.")

        sub_tend, sub_rec, sub_terc, sub_aud = st.tabs([
            "📈 Tendências & Demanda",
            "♻️ Recorrências",
            "🌐 Central de Terceiros",
            "🛡️ Auditoria",
        ])

        # --------------------------------------------------------
        # TENDÊNCIAS & DEMANDA
        # --------------------------------------------------------
        with sub_tend:
            st.markdown("### 📈 Evolução de chamados ao longo do tempo")
            df_datas = df[df["dt_abertura"].notna()].copy()
            if df_datas.empty:
                st.info("Não há datas de abertura suficientes para montar a evolução.")
            else:
                granularidade = st.radio(
                    "Agrupamento",
                    ["Mensal", "Semanal"],
                    horizontal=True,
                    key="gestao_granularidade",
                )

                if granularidade == "Semanal":
                    abertos = df_datas.set_index("dt_abertura").resample("W-MON")["id_chamado"].count().rename("Abertos")
                    concl_base = df[df["dt_conclusao_efetiva"].notna()].copy()
                    concluidos = concl_base.set_index("dt_conclusao_efetiva").resample("W-MON")["id_chamado"].count().rename("Concluídos")
                else:
                    abertos = df_datas.assign(periodo=df_datas["dt_abertura"].dt.to_period("M")).groupby("periodo")["id_chamado"].count().rename("Abertos")
                    concl_base = df[df["dt_conclusao_efetiva"].notna()].copy()
                    concluidos = concl_base.assign(periodo=concl_base["dt_conclusao_efetiva"].dt.to_period("M")).groupby("periodo")["id_chamado"].count().rename("Concluídos")

                evol = pd.concat([abertos, concluidos], axis=1).fillna(0).sort_index()
                if granularidade == "Mensal":
                    evol.index = evol.index.astype(str)
                else:
                    evol.index = pd.to_datetime(evol.index).strftime("%d/%m/%Y")
                evol_reset = evol.reset_index().rename(columns={evol.index.name or "index": "Período"})
                if "Período" not in evol_reset.columns:
                    evol_reset = evol_reset.rename(columns={evol_reset.columns[0]: "Período"})
                evol_long = evol_reset.melt(id_vars="Período", value_vars=["Abertos", "Concluídos"], var_name="Tipo", value_name="Quantidade")
                fig_evol = px.line(evol_long, x="Período", y="Quantidade", color="Tipo", markers=True)
                fig_evol = aplicar_layout_plotly(fig_evol)
                st.plotly_chart(fig_evol, use_container_width=True)

            st.divider()
            st.markdown("### 📅 Comparação mês contra mês")
            periodos = sorted(df["dt_abertura"].dropna().dt.to_period("M").unique(), reverse=True)
            if not periodos:
                st.info("Não há meses suficientes para comparação.")
            else:
                labels_periodo = {p: f"{MESES_DIC.get(p.month, p.month)}/{p.year}" for p in periodos}
                periodo_sel = st.selectbox(
                    "Mês de referência",
                    options=periodos,
                    format_func=lambda p: labels_periodo[p],
                    key="gestao_mes_comparacao",
                )
                periodo_ant = periodo_sel - 1
                met_atual = metricas_mes(df, periodo_sel)
                met_ant = metricas_mes(df, periodo_ant)

                mc1, mc2, mc3, mc4, mc5 = st.columns(5)
                with mc1:
                    st.metric("Chamados abertos", met_atual["abertos"], delta=met_atual["abertos"] - met_ant["abertos"])
                with mc2:
                    st.metric("Concluídos no mês", met_atual["concluidos"], delta=met_atual["concluidos"] - met_ant["concluidos"])
                with mc3:
                    st.metric("Backlog no fim do mês", met_atual["backlog"], delta=met_atual["backlog"] - met_ant["backlog"], delta_color="inverse")
                with mc4:
                    sla_atual = formatar_tempo(met_atual["sla_medio"]) if met_atual["sla_medio"] is not None and pd.notna(met_atual["sla_medio"]) else "N/A"
                    sla_ant = met_ant["sla_medio"]
                    delta_sla = None
                    if met_atual["sla_medio"] is not None and sla_ant is not None and pd.notna(met_atual["sla_medio"]) and pd.notna(sla_ant):
                        delta_sla = formatar_tempo(abs(met_atual["sla_medio"] - sla_ant))
                        if met_atual["sla_medio"] > sla_ant:
                            delta_sla = "+" + delta_sla
                        elif met_atual["sla_medio"] < sla_ant:
                            delta_sla = "-" + delta_sla
                    st.metric("Tempo médio total", sla_atual, delta=delta_sla, delta_color="inverse")
                with mc5:
                    csat_atual = f"{met_atual['csat']:.2f}/5" if met_atual["csat"] is not None and pd.notna(met_atual["csat"]) else "N/A"
                    delta_csat = None
                    if met_atual["csat"] is not None and met_ant["csat"] is not None and pd.notna(met_atual["csat"]) and pd.notna(met_ant["csat"]):
                        delta_csat = f"{met_atual['csat'] - met_ant['csat']:+.2f}"
                    st.metric("CSAT", csat_atual, delta=delta_csat)
                st.caption(
                    f"Comparando {labels_periodo[periodo_sel]} com {MESES_DIC.get(periodo_ant.month, periodo_ant.month)}/{periodo_ant.year}. "
                    f"Avaliações no mês atual: {met_atual['avaliacoes']}."
                )

            st.divider()
            st.markdown("### 🕐 Horários de maior demanda")
            df_hora = df[df["dt_abertura"].notna()].copy()
            if df_hora.empty:
                st.info("Não há datas/horários suficientes para montar o mapa de calor.")
            else:
                df_hora["dia_num"] = df_hora["dt_abertura"].dt.dayofweek
                df_hora["Dia"] = df_hora["dia_num"].map(DIAS_SEMANA)
                df_hora["Hora"] = df_hora["dt_abertura"].dt.hour
                pivot = df_hora.pivot_table(index="Dia", columns="Hora", values="id_chamado", aggfunc="count", fill_value=0)
                ordem_dias = [DIAS_SEMANA[i] for i in range(7)]
                pivot = pivot.reindex(ordem_dias, fill_value=0).reindex(columns=list(range(24)), fill_value=0)
                fig_heat = go.Figure(data=go.Heatmap(
                    z=pivot.values,
                    x=[f"{h:02d}h" for h in pivot.columns],
                    y=pivot.index.tolist(),
                    hovertemplate="%{y} às %{x}: %{z} chamado(s)<extra></extra>",
                ))
                fig_heat.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#f8fafc"),
                    margin=dict(t=20, b=20, l=20, r=20),
                    xaxis_title="Hora de abertura",
                    yaxis_title="Dia da semana",
                )
                st.plotly_chart(fig_heat, use_container_width=True)

        # --------------------------------------------------------
        # RECORRÊNCIAS
        # --------------------------------------------------------
        with sub_rec:
            st.markdown("### ♻️ Problemas recorrentes")
            col_rec1, col_rec2 = st.columns([2, 2])
            with col_rec1:
                minimo_rec = st.selectbox("Mínimo de ocorrências", [2, 3, 4, 5], index=1, key="min_recorrencia")
            with col_rec2:
                periodo_rec = st.selectbox("Período analisado", ["Todo histórico", "Últimos 90 dias", "Últimos 30 dias"], key="periodo_recorrencia")

            df_rec = df.copy()
            agora_rec = pd.Timestamp.now()
            if periodo_rec == "Últimos 90 dias":
                df_rec = df_rec[df_rec["dt_abertura"].notna() & (df_rec["dt_abertura"] >= agora_rec - pd.Timedelta(days=90))]
            elif periodo_rec == "Últimos 30 dias":
                df_rec = df_rec[df_rec["dt_abertura"].notna() & (df_rec["dt_abertura"] >= agora_rec - pd.Timedelta(days=30))]

            recorrentes = obter_problemas_recorrentes(df_rec, minimo=minimo_rec, limite=20)
            if recorrentes.empty:
                st.info("Nenhum agrupamento recorrente relevante apareceu com os critérios atuais.")
            else:
                st.dataframe(
                    recorrentes[["Quantidade", "Exemplo", "Departamentos", "Tickets"]],
                    use_container_width=True,
                    hide_index=True,
                )
                st.caption("Agrupamento heurístico por termos relevantes do título/descrição; serve para encontrar padrões, não como classificação definitiva.")

            st.divider()
            st.markdown("### 🚨 Possível problema recorrente — detecção automática")
            c_auto1, c_auto2 = st.columns(2)
            with c_auto1:
                janela_auto = st.selectbox("Janela recente", [2, 3, 7, 14, 30], index=2, format_func=lambda x: f"Últimos {x} dias", key="janela_auto")
            with c_auto2:
                minimo_auto = st.selectbox("Chamados parecidos para alertar", [3, 4, 5], index=0, key="minimo_auto")

            alertas = detectar_possiveis_recorrencias(df, dias=janela_auto, minimo=minimo_auto)
            if not alertas:
                st.success("Nenhum agrupamento recente forte o bastante para gerar alerta automático.")
            else:
                st.warning(f"Foram encontrados {len(alertas)} possível(is) grupo(s) de chamados semelhantes na janela selecionada.")
                for i, grupo in enumerate(alertas, start=1):
                    titulos = [g["titulo"] for g in grupo]
                    departamentos = sorted({g["departamento"] for g in grupo if g["departamento"]})
                    tickets = [g["ticket"] for g in grupo if g["ticket"]]
                    with st.container(border=True):
                        st.markdown(f"**🚨 Grupo {i}: {len(grupo)} chamados possivelmente relacionados**")
                        st.write(titulos[0][:180])
                        st.caption(
                            f"Tickets: {', '.join(tickets[:12]) or '-'} | Departamentos: {', '.join(departamentos[:6]) or '-'}"
                        )

        # --------------------------------------------------------
        # CENTRAL DE TERCEIROS
        # --------------------------------------------------------
        with sub_terc:
            st.markdown(
                "### 🌐 Central de Terceiros"
            )

            base_terc = (
                montar_base_terceiros_admin(df, df_terceiros)
            )

            if base_terc.empty:
                st.info(
                    "Nenhum vínculo com terceiros foi encontrado."
                )

            else:
                ativos_terc = base_terc[
                    base_terc[
                        "grupo_status"
                    ] != "Concluídos"
                ].copy()

                citel_ativos = ativos_terc[
                    ativos_terc[
                        "nome_terceiro"
                    ].str.contains(
                        "citel",
                        case=False,
                        na=False,
                    )
                    |
                    ativos_terc[
                        "link"
                    ].str.contains(
                        "citelsoftware",
                        case=False,
                        na=False,
                    )
                ].copy()

                t1, t2, t3, t4 = (
                    st.columns(4)
                )

                with t1:
                    st.metric(
                        "Vínculos com terceiros",
                        len(base_terc),
                    )

                with t2:
                    st.metric(
                        "Chamados ainda ativos",
                        len(ativos_terc),
                    )

                with t3:
                    st.metric(
                        "Empresas terceiras",
                        base_terc[
                            "nome_terceiro"
                        ].nunique(),
                    )

                with t4:
                    st.metric(
                        "Chamados ativos da Citel",
                        len(citel_ativos),
                    )

                terc_counts = (
                    base_terc[
                        "nome_terceiro"
                    ]
                    .replace(
                        "",
                        "Não informado",
                    )
                    .value_counts()
                    .reset_index()
                )

                terc_counts.columns = [
                    "Terceiro",
                    "Quantidade",
                ]

                fig_terc = px.bar(
                    terc_counts,
                    x="Quantidade",
                    y="Terceiro",
                    orientation="h",
                )

                fig_terc = (
                    aplicar_layout_plotly(
                        fig_terc
                    )
                )

                st.plotly_chart(
                    fig_terc,
                    use_container_width=True,
                )

                st.markdown(
                    "#### Situação dos chamados vinculados"
                )

                tabela_terc = base_terc[[
                    "ticket_ferpam",
                    "status_ferpam",
                    "nome_terceiro",
                    "id_ticket",
                    "tecnico",
                    "departamento",
                ]].copy()

                tabela_terc.columns = [
                    "Ticket Ferpam",
                    "Status Ferpam",
                    "Terceiro",
                    "Ticket Terceiro",
                    "Técnico",
                    "Departamento",
                ]

                st.dataframe(
                    tabela_terc,
                    use_container_width=True,
                    hide_index=True,
                )

                st.divider()

                st.markdown(
                    "#### 🔄 Situação ao vivo da Citel"
                )

                st.caption(
                    (
                        "Roadmap é identificado pela última "
                        "mensagem da própria Citel. "
                        "Se essa mensagem contém 'roadmap', "
                        "o ticket fica separado e não entra "
                        "como resposta pendente."
                    )
                )

                col_live1, col_live2 = (
                    st.columns([3, 7])
                )

                with col_live1:
                    atualizar_live = (
                        st.button(
                            "🔄 Consultar Citel agora",
                            type="primary",
                            use_container_width=True,
                            key="btn_central_citel",
                        )
                    )

                with col_live2:
                    st.caption(
                        (
                            f"{len(citel_ativos)} "
                            "chamado(s) ativo(s) "
                            "da Citel encontrado(s)."
                        )
                    )

                if atualizar_live:
                    registrar_auditoria_seguro(
                        "ATUALIZAR_CENTRAL_TERCEIROS",
                        detalhes=(
                            "Consulta ao vivo de "
                            f"{len(citel_ativos)} "
                            "vínculos ativos da Citel."
                        ),
                    )

                    resultados_live = []
                    limite_live = 60
                    agora_live = pd.Timestamp.now(
                        tz="UTC"
                    )

                    # Botão manual deve buscar o estado atual, não um snapshot
                    # ainda dentro do TTL das consultas externas.
                    try:
                        consultar_vez_resposta_citel.clear()
                    except Exception:
                        pass
                    try:
                        consultar_status_request_citel.clear()
                    except Exception:
                        pass

                    for _, item in (
                        citel_ativos
                        .head(limite_live)
                        .iterrows()
                    ):
                        ticket_citel = (
                            extrair_id_ticket_citel(
                                item.get(
                                    "link",
                                    "",
                                ),
                                item.get(
                                    "id_ticket",
                                    "",
                                ),
                            )
                        )

                        situacao = (
                            consultar_vez_resposta_citel(
                                ticket_citel
                            )
                        )

                        status_ferpam_item = str(
                            item.get("status_ferpam", "") or ""
                        ).strip()

                        status_externo = {
                            "ok": False,
                            "status": "",
                            "resolvido": False,
                        }

                        # Esta terceira chamada só é necessária para o caso
                        # que queremos auditar: Ferpam ainda aguardando terceiro.
                        if _status_ferpam_aguardando_terceiro(status_ferpam_item):
                            status_externo = consultar_status_request_citel(
                                ticket_citel
                            )

                        ultima_dt = pd.to_datetime(
                            situacao.get(
                                "ultima_data"
                            ),
                            errors="coerce",
                            utc=True,
                        )

                        dias_sem_interacao = None

                        if pd.notna(
                            ultima_dt
                        ):
                            dias_sem_interacao = int(
                                max(
                                    0,
                                    (
                                        agora_live
                                        - ultima_dt
                                    ).total_seconds()
                                    // 86400,
                                )
                            )

                        estado_codigo = (
                            situacao.get(
                                "estado",
                                "indisponivel",
                            )
                            if situacao.get("ok")
                            else "indisponivel"
                        )

                        resultados_live.append({
                            "Ticket Ferpam": item.get(
                                "ticket_ferpam",
                                "",
                            ),
                            "Ticket Citel": (
                                ticket_citel
                                or "-"
                            ),
                            "Título": item.get(
                                "titulo",
                                "",
                            ),
                            "Técnico": item.get(
                                "tecnico",
                                "",
                            ),
                            "Status Ferpam": status_ferpam_item,
                            "Status Citel": (
                                _rotulo_status_citel(
                                    status_externo.get("status")
                                )
                                if status_externo.get("ok")
                                else "-"
                            ),
                            "resolvido_citel_pendente_ferpam": bool(
                                _status_ferpam_aguardando_terceiro(status_ferpam_item)
                                and status_externo.get("ok")
                                and status_externo.get("resolvido")
                            ),
                            "Estado": (
                                situacao.get(
                                    "titulo"
                                )
                                if situacao.get("ok")
                                else "Não foi possível consultar"
                            ),
                            "estado_codigo": estado_codigo,
                            "Última interação": (
                                formatar_data_citel(
                                    situacao.get(
                                        "ultima_data"
                                    )
                                )
                                or "-"
                            ),
                            "dias_sem_interacao": (
                                dias_sem_interacao
                            ),
                        })

                    st.session_state[
                        "central_terceiros_live_v3"
                    ] = resultados_live

                    if (
                        len(citel_ativos)
                        > limite_live
                    ):
                        st.warning(
                            (
                                "Por segurança, a atualização "
                                "ao vivo foi limitada aos "
                                f"primeiros {limite_live} "
                                "chamados ativos."
                            )
                        )

                live = st.session_state.get(
                    "central_terceiros_live_v3",
                    [],
                )

                if live:
                    live_df = pd.DataFrame(
                        live
                    )

                    # Compatibilidade com sessão já aberta durante um redeploy.
                    if "resolvido_citel_pendente_ferpam" not in live_df.columns:
                        live_df["resolvido_citel_pendente_ferpam"] = False
                    if "Status Ferpam" not in live_df.columns:
                        live_df["Status Ferpam"] = "-"
                    if "Status Citel" not in live_df.columns:
                        live_df["Status Citel"] = "-"

                    aguardando_ti = live_df[
                        live_df[
                            "estado_codigo"
                        ] == "aguardando_ti"
                    ]

                    aguardando_citel = live_df[
                        live_df[
                            "estado_codigo"
                        ] == "aguardando_citel"
                    ]

                    roadmaps_live = live_df[
                        live_df[
                            "estado_codigo"
                        ] == "roadmap"
                    ]

                    sem_interacao_15 = live_df[
                        (
                            live_df[
                                "estado_codigo"
                            ].isin([
                                "aguardando_ti",
                                "aguardando_citel",
                            ])
                        )
                        &
                        (
                            pd.to_numeric(
                                live_df[
                                    "dias_sem_interacao"
                                ],
                                errors="coerce",
                            )
                            >= 15
                        )
                    ]

                    resolvidos_citel_pendentes_ferpam = live_df[
                        live_df[
                            "resolvido_citel_pendente_ferpam"
                        ] == True
                    ].copy()

                    indisponiveis = live_df[
                        ~live_df[
                            "estado_codigo"
                        ].isin([
                            "aguardando_ti",
                            "aguardando_citel",
                            "roadmap",
                        ])
                    ]

                    (
                        lc1,
                        lc2,
                        lc3,
                        lc4,
                        lc5,
                        lc6,
                    ) = st.columns(6)

                    with lc1:
                        st.metric(
                            "Citel respondeu / aguardando TI",
                            len(aguardando_ti),
                        )

                    with lc2:
                        st.metric(
                            "Aguardando Citel",
                            len(aguardando_citel),
                        )

                    with lc3:
                        st.metric(
                            "🟣 Em Roadmap",
                            len(roadmaps_live),
                        )

                    with lc4:
                        st.metric(
                            "⏳ 15+ dias sem atualização",
                            len(sem_interacao_15),
                        )

                    with lc5:
                        st.metric(
                            "⚠️ Resolvido Citel / Ferpam pendente",
                            len(resolvidos_citel_pendentes_ferpam),
                        )

                    with lc6:
                        st.metric(
                            "Consulta indisponível",
                            len(indisponiveis),
                        )

                    tabela_live = live_df.copy()

                    tabela_live[
                        "Dias sem interação"
                    ] = tabela_live[
                        "dias_sem_interacao"
                    ]

                    tabela_live = (
                        tabela_live.drop(
                            columns=[
                                "estado_codigo",
                                "dias_sem_interacao",
                                "resolvido_citel_pendente_ferpam",
                            ]
                        )
                    )

                    st.dataframe(
                        tabela_live,
                        use_container_width=True,
                        hide_index=True,
                    )

                    if not resolvidos_citel_pendentes_ferpam.empty:
                        st.markdown(
                            "##### ⚠️ Citel já resolveu, mas a Ferpam ainda está aguardando terceiro"
                        )
                        st.warning(
                            f"Encontrado(s) {len(resolvidos_citel_pendentes_ferpam)} chamado(s) que precisam de revisão interna."
                        )
                        st.caption(
                            "Entram aqui somente chamados cujo status na Ferpam contém 'Aguardando Terceiro' e cujo Request da Citel está como Resolvido ou Fechado."
                        )

                        for idx_div, item_div in resolvidos_citel_pendentes_ferpam.iterrows():
                            with st.container(border=True):
                                c_d1, c_d2 = st.columns([8, 2])

                                with c_d1:
                                    st.markdown(
                                        f"**⚠️ Ferpam #{item_div['Ticket Ferpam']} | Citel #{item_div['Ticket Citel']}**"
                                    )
                                    st.write(item_div.get("Título") or "Sem título")
                                    st.caption(
                                        f"FerPam: {item_div.get('Status Ferpam') or '-'} • Citel: {item_div.get('Status Citel') or '-'} • Técnico: {item_div.get('Técnico') or 'Não atribuído'}"
                                    )

                                with c_d2:
                                    if item_div["Ticket Ferpam"]:
                                        st.button(
                                            "👁️ Abrir",
                                            key=(
                                                "btn_live_divergencia_"
                                                f"{idx_div}_"
                                                f"{item_div['Ticket Ferpam']}"
                                            ),
                                            on_click=abrir_ticket,
                                            args=(item_div["Ticket Ferpam"],),
                                            use_container_width=True,
                                        )

                    if not roadmaps_live.empty:
                        st.markdown(
                            "##### 🟣 Chamados em Roadmap"
                        )

                        st.caption(
                            (
                                "Esses chamados não entram em "
                                "'Aguardando Citel' nem em "
                                "'Aguardando TI'."
                            )
                        )

                        for (
                            idx_live,
                            item_live,
                        ) in (
                            roadmaps_live.iterrows()
                        ):
                            with st.container(
                                border=True
                            ):
                                c_l1, c_l2 = (
                                    st.columns(
                                        [8, 2]
                                    )
                                )

                                with c_l1:
                                    st.markdown(
                                        (
                                            "**🟣 Ferpam "
                                            f"#{item_live['Ticket Ferpam']} "
                                            "| Citel "
                                            f"#{item_live['Ticket Citel']}**"
                                        )
                                    )

                                    st.write(
                                        item_live.get(
                                            "Título"
                                        )
                                        or "Sem título"
                                    )

                                    st.caption(
                                        (
                                            "Roadmap detectado pela "
                                            "última mensagem da Citel "
                                            "• Última interação: "
                                            f"{item_live.get('Última interação')}"
                                        )
                                    )

                                with c_l2:
                                    if item_live[
                                        "Ticket Ferpam"
                                    ]:
                                        st.button(
                                            "👁️ Abrir",
                                            key=(
                                                "btn_live_roadmap_"
                                                f"{idx_live}_"
                                                f"{item_live['Ticket Ferpam']}"
                                            ),
                                            on_click=abrir_ticket,
                                            args=(
                                                item_live[
                                                    "Ticket Ferpam"
                                                ],
                                            ),
                                            use_container_width=True,
                                        )

                    if not aguardando_ti.empty:
                        st.markdown(
                            (
                                "##### 🔵 Citel respondeu — "
                                "chamados que precisam da TI"
                            )
                        )

                        for (
                            idx_live,
                            item_live,
                        ) in (
                            aguardando_ti.iterrows()
                        ):
                            with st.container(
                                border=True
                            ):
                                c_l1, c_l2 = (
                                    st.columns(
                                        [8, 2]
                                    )
                                )

                                with c_l1:
                                    st.markdown(
                                        (
                                            "**🎫 Ferpam "
                                            f"#{item_live['Ticket Ferpam']} "
                                            "| Citel "
                                            f"#{item_live['Ticket Citel']}**"
                                        )
                                    )

                                    st.write(
                                        item_live.get(
                                            "Título"
                                        )
                                        or "Sem título"
                                    )

                                    st.caption(
                                        (
                                            "Técnico: "
                                            f"{item_live.get('Técnico') or 'Não atribuído'} "
                                            "• Última interação: "
                                            f"{item_live.get('Última interação')}"
                                        )
                                    )

                                with c_l2:
                                    if item_live[
                                        "Ticket Ferpam"
                                    ]:
                                        st.button(
                                            "👁️ Abrir",
                                            key=(
                                                "btn_live_abrir_"
                                                f"{idx_live}_"
                                                f"{item_live['Ticket Ferpam']}"
                                            ),
                                            on_click=abrir_ticket,
                                            args=(
                                                item_live[
                                                    "Ticket Ferpam"
                                                ],
                                            ),
                                            use_container_width=True,
                                        )

                    if not sem_interacao_15.empty:
                        st.markdown(
                            (
                                "##### ⏳ Chamados da Citel "
                                "há 15+ dias sem nenhuma interação"
                            )
                        )

                        st.caption(
                            (
                                "Aqui entram tickets em que nem "
                                "a Citel nem a TI/Ferpam enviaram "
                                "nova mensagem pública há pelo "
                                "menos 15 dias. Roadmaps são ignorados."
                            )
                        )

                        for (
                            idx_live,
                            item_live,
                        ) in (
                            sem_interacao_15.iterrows()
                        ):
                            dias = int(
                                item_live.get(
                                    "dias_sem_interacao"
                                )
                                or 0
                            )

                            st.warning(
                                (
                                    f"🎫 Ferpam "
                                    f"#{item_live['Ticket Ferpam']} "
                                    f"| Citel "
                                    f"#{item_live['Ticket Citel']} "
                                    f"— {dias} dias sem interação "
                                    f"— {item_live.get('Título') or 'Sem título'}"
                                )
                            )

        # --------------------------------------------------------
        # AUDITORIA
        # --------------------------------------------------------
        with sub_aud:
            st.markdown("### 🛡️ Auditoria administrativa")
            st.caption("Registra ações administrativas relevantes sem gravar senhas, tokens ou conteúdo das mensagens da Citel.")

            if carregar_auditoria is None:
                st.warning("A auditoria persistente precisa da versão atualizada de services/sheets.py que acompanha este pacote.")
            else:
                col_aud1, col_aud2 = st.columns([2, 8])
                with col_aud1:
                    if st.button("🔄 Atualizar auditoria", use_container_width=True, key="btn_refresh_aud"):
                        try:
                            carregar_auditoria.clear()
                        except Exception:
                            pass
                try:
                    df_aud = carregar_auditoria()
                except Exception as e:
                    df_aud = pd.DataFrame()
                    st.error(f"Não foi possível carregar a auditoria: {e}")

                if df_aud.empty:
                    st.info("Ainda não existem registros de auditoria. A aba será criada automaticamente no primeiro evento administrativo.")
                else:
                    df_aud.columns = [str(c).strip() for c in df_aud.columns]
                    eventos_disp = sorted([str(v) for v in df_aud.get("evento", pd.Series(dtype=str)).dropna().unique()])
                    filtro_evento = st.selectbox("Filtrar por evento", ["Todos"] + eventos_disp, key="aud_evento")
                    df_aud_view = df_aud.copy()
                    if filtro_evento != "Todos" and "evento" in df_aud_view.columns:
                        df_aud_view = df_aud_view[df_aud_view["evento"].astype(str) == filtro_evento]
                    if "timestamp" in df_aud_view.columns:
                        dt_aud = pd.to_datetime(df_aud_view["timestamp"], errors="coerce")
                        df_aud_view = df_aud_view.assign(_dt=dt_aud).sort_values("_dt", ascending=False).drop(columns=["_dt"])
                    colunas_visiveis = [c for c in ["timestamp", "usuario_admin", "evento", "ticket", "detalhes"] if c in df_aud_view.columns]
                    st.dataframe(df_aud_view[colunas_visiveis].head(500), use_container_width=True, hide_index=True)
                    st.caption("Mostrando no máximo os 500 registros mais recentes do filtro atual.")


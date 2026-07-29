import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from services.sheets import carregar_chamados


# ============================================================
# CONFIGURAÇÃO DA PÁGINA
# ============================================================

st.set_page_config(
    page_title="Portal de Chamados TI",
    page_icon="🎫",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ============================================================
# CARREGAMENTO E TRATAMENTO DE DADOS BLINDADO
# ============================================================

@st.cache_data(ttl=60)
def carregar_dados():
    colunas_obrigatorias = [
        "id_chamado", "solicitante", "titulo", "ocorrencia", 
        "status", "prioridade", "departamento", "tecnico", 
        "cidade", "atividade_realizada", "nota_atendimento",
        "data_avaliacao", "comentario_avaliacao"
    ]
    
    try:
        data = carregar_chamados()
        
        if isinstance(data, pd.DataFrame):
            df_raw = data.copy()
        else:
            df_raw = pd.DataFrame(data)
        
        if df_raw.empty:
            df_empty = pd.DataFrame(columns=colunas_obrigatorias)
            df_empty["nota_num"] = pd.Series(dtype=float)
            df_empty["data_aval_dt"] = pd.Series(dtype="datetime64[ns]")
            return df_empty
        
        # 1. Normaliza os nomes das colunas (minúsculas e sem espaços nas pontas)
        df_raw.columns = [str(col).strip().lower() for col in df_raw.columns]
        
        # 2. Remove colunas sem nome
        df_raw = df_raw.loc[:, df_raw.columns != ""]
        
        # 3. Remove duplicadas de nomes de colunas mantendo a primeira
        df_raw = df_raw.loc[:, ~df_raw.columns.duplicated()]
        
        # 4. Garante que todas as colunas obrigatórias existam
        for col in colunas_obrigatorias:
            if col not in df_raw.columns:
                df_raw[col] = ""
                
        # 5. Tratamento básico de texto
        for col in df_raw.columns:
            df_raw[col] = df_raw[col].fillna("").astype(str).str.strip()
            
        # 6. Colunas auxiliares convertidas para métricas de Avaliação
        df_raw["nota_num"] = pd.to_numeric(df_raw["nota_atendimento"], errors="coerce")
        df_raw["data_aval_dt"] = pd.to_datetime(df_raw["data_avaliacao"], errors="coerce")
            
        return df_raw

    except Exception as e:
        st.error(f"Erro ao carregar dados da planilha: {e}")
        df_err = pd.DataFrame(columns=colunas_obrigatorias)
        df_err["nota_num"] = pd.Series(dtype=float)
        df_err["data_aval_dt"] = pd.Series(dtype="datetime64[ns]")
        return df_err

df = carregar_dados()


# ============================================================
# ESTADOS DA SESSÃO (SESSION STATE)
# ============================================================

if "tela" not in st.session_state:
    st.session_state.tela = "busca"

if "ticket_aberto" not in st.session_state:
    st.session_state.ticket_aberto = None

if "tema" not in st.session_state:
    st.session_state.tema = "☀️ Claro"

if "autenticado_admin" not in st.session_state:
    st.session_state.autenticado_admin = False

if "filtro_dash_tipo" not in st.session_state:
    st.session_state.filtro_dash_tipo = None

if "filtro_dash_valor" not in st.session_state:
    st.session_state.filtro_dash_valor = None


def abrir_ticket(ticket_id):
    st.session_state.ticket_aberto = str(ticket_id).strip()
    st.session_state.tela = "ticket"


def voltar_busca():
    st.session_state.ticket_aberto = None
    st.session_state.tela = "busca"


def limpar_filtro_dash():
    st.session_state.filtro_dash_tipo = None
    st.session_state.filtro_dash_valor = None


lista_solicitantes_admin = sorted(
    list(set([s for s in df["solicitante"].unique() if s and s.casefold() != "nan"])),
    key=str.casefold
)

lista_status_opcoes = ["Todos os Status"] + sorted(
    list(set([s for s in df["status"].unique() if s and s.casefold() != "nan"])),
    key=str.casefold
)


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
        if st.button("Entrar", type="primary", use_container_width=True):
            if usuario_login.strip() == "admin" and senha_login == "admin":
                st.session_state.autenticado_admin = True
                st.success("Login efetuado!")
                st.rerun()
            else:
                st.error("Usuário ou senha incorretos.")
else:
    st.sidebar.success("⚡ Conectado como ADMIN")
    if st.sidebar.button("🚪 Sair do Modo Admin", use_container_width=True):
        st.session_state.autenticado_admin = False
        st.session_state.tela = "busca"
        limpar_filtro_dash()
        st.rerun()

st.sidebar.divider()

opcao_tema = st.sidebar.selectbox(
    "🎨 Aparência / Tema",
    ["☀️ Claro", "🌙 Escuro"],
    index=0 if st.session_state.tema == "☀️ Claro" else 1,
    key="select_tema"
)
st.session_state.tema = opcao_tema
modo_escuro = (st.session_state.tema == "🌙 Escuro")

st.sidebar.divider()

opcoes_menu = ["🔍 Consultar Chamados"]
if st.session_state.autenticado_admin:
    opcoes_menu.append("📊 Dashboard de Indicadores")

opcao_menu = st.sidebar.radio(
    "📍 Navegação",
    opcoes_menu,
    index=0 if st.session_state.tela in ["busca", "ticket"] else 1
)

if opcao_menu == "📊 Dashboard de Indicadores" and st.session_state.tela != "dashboard":
    st.session_state.tela = "dashboard"
elif opcao_menu == "🔍 Consultar Chamados" and st.session_state.tela == "dashboard":
    st.session_state.tela = "busca"


# ============================================================
# ESTILIZAÇÃO CSS CUSTOMIZADA (AZUL FERPAM #003399)
# ============================================================

AZUL_FERPAM = "#003399"
AZUL_FERPAM_HOVER = "#002266"

if modo_escuro:
    bg_app = "#0b0f19"
    bg_sidebar = "#111827"
    bg_card = "#1e293b"
    border_card = "#334155"
    text_main = "#f8fafc"
    text_muted = "#94a3b8"
    plotly_template = "plotly_dark"
    input_bg = "#1e293b"
    btn_bg = "#1e293b"
    btn_text = "#f8fafc"
    btn_border = "#334155"
else:
    bg_app = "#f8fafc"
    bg_sidebar = "#ffffff"
    bg_card = "#ffffff"
    border_card = "#cbd5e1"
    text_main = "#0f172a"
    text_muted = "#64748b"
    plotly_template = "plotly_white"
    input_bg = "#ffffff"
    btn_bg = "#ffffff"
    btn_text = "#0f172a"
    btn_border = "#cbd5e1"

st.markdown(f"""
<style>
    header[data-testid="stHeader"] {{ background-color: transparent !important; }}
    #MainMenu {{ visibility: hidden; }}
    footer {{ visibility: hidden; }}

    .stApp {{ background-color: {bg_app} !important; }}
    section[data-testid="stSidebar"] {{ 
        background-color: {bg_sidebar} !important; 
        border-right: 1px solid {border_card}; 
    }}

    div[data-testid="stMetric"] {{
        background-color: {bg_card} !important;
        border: 1px solid {border_card} !important;
        border-radius: 12px !important;
        padding: 16px !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}
    div[data-testid="stMetricLabel"] label {{ color: {text_muted} !important; font-weight: 600 !important; }}
    div[data-testid="stMetricValue"] div {{ color: {text_main} !important; font-weight: 800 !important; }}

    div[data-testid="stVerticalBlock"] > div[style*="border"] {{
        background-color: {bg_card} !important;
        border: 1px solid {border_card} !important;
        border-radius: 12px !important;
        padding: 18px !important;
    }}

    div[data-baseweb="input"] > div,
    div[data-baseweb="select"] > div,
    input[type="text"],
    input[type="password"] {{
        background-color: {input_bg} !important;
        color: {text_main} !important;
        border-color: {border_card} !important;
        border-radius: 8px !important;
    }}
    input {{ color: {text_main} !important; }}
    input::placeholder {{ color: {text_muted} !important; }}

    div[data-testid="stExpander"] {{
        background-color: {bg_card} !important;
        border: 1px solid {border_card} !important;
        border-radius: 8px !important;
    }}
    div[data-testid="stExpander"] summary * {{
        color: {text_main} !important;
        font-weight: 600 !important;
    }}

    .stButton > button[data-testid="stBaseButton-primary"],
    button[kind="primary"] {{
        background-color: {AZUL_FERPAM} !important;
        border: 1px solid {AZUL_FERPAM} !important;
        border-radius: 8px !important;
        font-weight: 700 !important;
    }}
    .stButton > button[data-testid="stBaseButton-primary"] *,
    button[kind="primary"] * {{ color: #ffffff !important; }}
    .stButton > button[data-testid="stBaseButton-primary"]:hover,
    button[kind="primary"]:hover {{
        background-color: {AZUL_FERPAM_HOVER} !important;
        border-color: {AZUL_FERPAM_HOVER} !important;
    }}

    .stButton > button[data-testid="stBaseButton-secondary"] {{
        background-color: {btn_bg} !important;
        color: {btn_text} !important;
        border: 1px solid {btn_border} !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
    }}
    .stButton > button[data-testid="stBaseButton-secondary"]:hover {{
        border-color: {AZUL_FERPAM} !important;
        color: {AZUL_FERPAM} !important;
    }}
</style>
""", unsafe_allow_html=True)


# ============================================================
# UTILS & RENDERIZAÇÃO
# ============================================================

def calcular_progresso(chamado):
    status = str(chamado.get("status", "")).strip().casefold()
    tecnico = str(chamado.get("tecnico", "")).strip().casefold()
    atividade = str(chamado.get("atividade_realizada", "")).strip().casefold()

    if status in ["concluído", "concluido", "finalizado", "fechado"]:
        return 100, "🟢 Chamado Finalizado"
    elif status in ["em andamento", "em atendimento"]:
        if atividade and atividade != "nan":
            return 80, "🔵 Em Atendimento (Atividade Registrada)"
        return 60, "🔵 Em Atendimento pelo Técnico"
    elif tecnico and tecnico != "nan" and tecnico != "não atribuído":
        return 35, "🟡 Técnico Atribuído (Aguardando Início)"
    else:
        return 15, "🟠 Chamado Aberto na Fila"


def get_status_badge(status):
    status_clean = str(status).strip()
    status_lower = status_clean.casefold()

    if status_lower in ["concluído", "concluido", "finalizado", "fechado"]:
        color = "#10b981"
        bg = "rgba(16, 185, 129, 0.12)"
        icon = "🟢"
    elif status_lower in ["em andamento", "em atendimento"]:
        color = AZUL_FERPAM
        bg = "rgba(0, 51, 153, 0.12)"
        icon = "🔵"
    elif status_lower in ["pendente", "aberto"]:
        color = "#d97706"
        bg = "rgba(217, 119, 6, 0.12)"
        icon = "🟡"
    else:
        color = "#64748b"
        bg = "rgba(100, 116, 139, 0.12)"
        icon = "⚪"

    return f'''<span style="background-color: {bg}; color: {color}; font-weight: 700; font-size: 0.82rem; padding: 4px 12px; border-radius: 20px; border: 1px solid {color}44; display: inline-flex; align-items: center; gap: 6px;">{icon} {status_clean}</span>'''


def render_barra_progresso(pct, texto_estagio):
    bar_color = "#10b981" if pct == 100 else (AZUL_FERPAM if pct >= 50 else "#d97706")
    return f"""
    <div style="margin-top: 10px; margin-bottom: 6px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <span style="font-size: 0.83rem; font-weight: 600; color: {text_muted};">{texto_estagio}</span>
            <span style="font-size: 0.85rem; font-weight: 800; color: {bar_color}; background-color: {bar_color}18; padding: 2px 10px; border-radius: 12px;">{pct}%</span>
        </div>
        <div style="width: 100%; background-color: {border_card}; height: 10px; border-radius: 6px; overflow: hidden;">
            <div style="width: {pct}%; background-color: {bar_color}; height: 100%; border-radius: 6px;"></div>
        </div>
    </div>
    """


def render_estrelas(nota):
    try:
        val = int(float(nota))
        val = max(1, min(5, val))
        return "⭐" * val + "☆" * (5 - val) + f" ({val}/5)"
    except (ValueError, TypeError):
        return None


def extrair_valor_clicado(event):
    if not event or "selection" not in event:
        return None
    points = event["selection"].get("points", [])
    if not points:
        return None
    p = points[0]
    if "customdata" in p and p["customdata"]:
        val = p["customdata"]
        return str(val[0]).strip() if isinstance(val, list) else str(val).strip()
    if "label" in p and p["label"] is not None:
        return str(p["label"]).strip()
    if "y" in p and isinstance(p["y"], str) and p["y"]:
        return str(p["y"]).strip()
    if "x" in p and isinstance(p["x"], str) and p["x"]:
        return str(p["x"]).strip()
    return None


def processar_clique_grafico(event, tipo_filtro):
    val = extrair_valor_clicado(event)
    if val and (st.session_state.filtro_dash_tipo != tipo_filtro or st.session_state.filtro_dash_valor != val):
        st.session_state.filtro_dash_tipo = tipo_filtro
        st.session_state.filtro_dash_valor = val
        st.rerun()


# ============================================================
# TELA 1: DETALHES DO TICKET
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

    st.divider()

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**Status Atual**")
        st.markdown(get_status_badge(chamado["status"]), unsafe_allow_html=True)
        st.write("")
        st.markdown("**👤 Solicitante**")
        st.write(chamado.get("solicitante", "-"))
    with col2:
        st.markdown("**⚠️ Prioridade**")
        st.write(chamado.get("prioridade", "-"))
        st.markdown("**🏢 Departamento**")
        st.write(chamado.get("departamento", "-"))
    with col3:
        st.markdown("**👨‍💻 Técnico Responsável**")
        st.write(chamado.get("tecnico", "Ainda não atribuído"))
        st.markdown("**📍 Cidade**")
        st.write(chamado.get("cidade", "-"))

    st.divider()

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("📋 Detalhes da Solicitação")
        st.markdown(f"**Título:** {chamado.get('titulo', '-')}")
        ocorrencia = str(chamado.get("ocorrencia", "")).strip()
        st.info(ocorrencia if ocorrencia and ocorrencia.casefold() != "nan" else "Nenhuma descrição fornecida.")

    with col_b:
        st.subheader("🔧 Resolução / Atividade Realizada")
        atividade = str(chamado.get("atividade_realizada", "")).strip()
        st.success(atividade if atividade and atividade.casefold() != "nan" else "Ainda não há atividades registradas para este chamado.")

    # AVALIAÇÃO DO ATENDIMENTO
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
                if estrelas:
                    st.markdown(f"### {estrelas}")
            if data_aval and data_aval.casefold() != "nan":
                st.caption(f"🗓️ Avaliado em: {data_aval}")
                
        with col_eval2:
            if coment_aval and coment_aval.casefold() != "nan":
                st.markdown(f"💬 **Comentário do Solicitante:**")
                st.write(f"*\"{coment_aval}\"*")

    st.stop()


# ============================================================
# TELA 2: BUSCA DE CHAMADOS
# ============================================================

if st.session_state.tela == "busca":

    st.title("🎫 Portal de Consulta de Chamados")

    if not st.session_state.autenticado_admin:
        st.write("Digite o **Número do Chamado** ou o **Seu Nome** e escolha o status para consultar.")
        
        c1, c2, c3 = st.columns([1.5, 2, 1.5])
        with c1:
            input_ticket = st.text_input("Número do Chamado", placeholder="Ex.: 933")
        with c2:
            input_nome = st.text_input("Seu Nome (Solicitante)", placeholder="Ex.: Carla")
        with c3:
            input_status = st.selectbox("Status / Pendência", options=lista_status_opcoes, key="usr_status")

        btn_pesquisar = st.button("🔍 Pesquisar Chamado", type="primary", use_container_width=True)

        if btn_pesquisar or input_ticket.strip() or input_nome.strip() or input_status != "Todos os Status":
            res = df.copy()

            if input_ticket.strip():
                res = res[res["id_chamado"].str.contains(input_ticket.strip(), case=False, na=False)]
            
            if input_nome.strip():
                res = res[res["solicitante"].str.contains(input_nome.strip(), case=False, na=False)]

            if input_status != "Todos os Status":
                res = res[res["status"].str.casefold() == input_status.casefold()]

            st.divider()

            if not input_ticket.strip() and not input_nome.strip() and input_status == "Todos os Status":
                st.info("💡 Informe o número do ticket, seu nome ou escolha um status para iniciar.")
            elif res.empty:
                st.warning("Nenhum chamado foi encontrado com esses critérios.")
            else:
                st.subheader(f"Localizado(s) {len(res)} chamado(s):")

                for _, cham in res.iterrows():
                    t_id = str(cham["id_chamado"]).strip()
                    pct, status_txt = calcular_progresso(cham)
                    badge_html = get_status_badge(cham.get("status", ""))
                    bar_html = render_barra_progresso(pct, status_txt)

                    with st.container(border=True):
                        col1, col2 = st.columns([7, 3])
                        with col1:
                            st.markdown(f"""
                            <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 6px;">
                                <span style="font-size: 1.2rem; font-weight: 800;">🎫 #{t_id}</span>
                                {badge_html}
                            </div>
                            <div style="font-size: 1rem; font-weight: 700; margin-bottom: 4px;">{cham.get('titulo', 'Sem título')}</div>
                            <div style="font-size: 0.85rem; color: {text_muted};">👤 {cham.get('solicitante', '-')} | 🏢 {cham.get('departamento', '-')}</div>
                            """, unsafe_allow_html=True)
                            st.markdown(bar_html, unsafe_allow_html=True)

                        with col2:
                            st.write("")
                            st.write("")
                            st.button("👁️ Ver detalhes", key=f"btn_usr_{t_id}", on_click=abrir_ticket, args=(t_id,), use_container_width=True)

    else:
        # PAINEL ADMINISTRADOR
        st.write("🔧 **Painel Admin**: Filtragem global de chamados.")

        c1, c2, c3 = st.columns([1.5, 2, 1.5])
        with c1:
            input_ticket_admin = st.text_input("Número do Ticket", placeholder="Ex.: 933")
        with c2:
            input_solic_admin = st.selectbox("Filtrar por Solicitante", options=["Todos"] + lista_solicitantes_admin)
        with c3:
            input_status_admin = st.selectbox("Status / Pendência", options=lista_status_opcoes, key="adm_status")

        btn_pesquisar_admin = st.button("🔍 Filtrar Base", type="primary", use_container_width=True)

        res = df.copy()

        if input_ticket_admin.strip():
            res = res[res["id_chamado"].str.contains(input_ticket_admin.strip(), case=False, na=False)]

        if input_solic_admin != "Todos":
            res = res[res["solicitante"].str.casefold() == input_solic_admin.casefold()]

        if input_status_admin != "Todos os Status":
            res = res[res["status"].str.casefold() == input_status_admin.casefold()]

        st.divider()

        if res.empty:
            st.warning("Nenhum chamado encontrado com estes filtros.")
        else:
            st.subheader(f"Total na consulta: {len(res)} chamado(s)")
            for _, cham in res.iterrows():
                t_id = str(cham["id_chamado"]).strip()
                pct, status_txt = calcular_progresso(cham)
                badge_html = get_status_badge(cham.get("status", ""))
                bar_html = render_barra_progresso(pct, status_txt)

                with st.container(border=True):
                    col1, col2 = st.columns([7, 3])
                    with col1:
                        st.markdown(f"""
                        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 6px;">
                            <span style="font-size: 1.2rem; font-weight: 800;">🎫 #{t_id}</span>
                            {badge_html}
                        </div>
                        <div style="font-size: 1rem; font-weight: 700;">{cham.get('titulo', 'Sem título')}</div>
                        <div style="font-size: 0.85rem; color: {text_muted};">👤 {cham.get('solicitante', '-')} | 🏢 {cham.get('departamento', '-')}</div>
                        """, unsafe_allow_html=True)
                        st.markdown(bar_html, unsafe_allow_html=True)

                    with col2:
                        st.write("")
                        st.write("")
                        st.button("👁️ Ver detalhes", key=f"btn_adm_{t_id}", on_click=abrir_ticket, args=(t_id,), use_container_width=True)


# ============================================================
# TELA 3: DASHBOARD INTERATIVA & SATISFAÇÃO (CSAT)
# ============================================================

if st.session_state.tela == "dashboard":

    if not st.session_state.autenticado_admin:
        st.error("⛔ Acesso Negado! Faça login como admin no menu lateral para visualizar o Dashboard.")
        st.stop()

    st.title("📊 Dashboard & Indicadores de TI")

    # Função auxiliar para manter o estilo dos gráficos Plotly coerente
    def aplicar_layout_plotly(fig):
        fig.update_layout(
            template=plotly_template,
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color=text_main, size=12),
            legend=dict(font=dict(color=text_main)),
            xaxis=dict(
                title=dict(font=dict(color=text_main)),
                tickfont=dict(color=text_main),
                gridcolor=border_card
            ),
            yaxis=dict(
                title=dict(font=dict(color=text_main)),
                tickfont=dict(color=text_main),
                gridcolor=border_card
            ),
            margin=dict(t=30, b=20, l=20, r=20)
        )
        return fig

    # CRIAÇÃO DAS ABAS DO DASHBOARD
    tab_op, tab_csat, tab_reviews = st.tabs([
        "📊 Operação & Volumetria", 
        "⭐ Satisfação & Notas (CSAT)", 
        "💬 Feed de Reviews & Feedback"
    ])


    # ============================================================
    # ABA 1: OPERAÇÃO & VOLUMETRIA
    # ============================================================
    with tab_op:
        st.caption("⚡ **Interativo**: Clique nos botões dos cartões ou nas fatias/barras dos gráficos para filtrar!")

        total_chamados = len(df)
        status_series = df["status"].astype(str).str.strip().str.casefold()
        concluidos = len(df[status_series.isin(["concluído", "concluido", "finalizado", "fechado"])])
        em_andamento = len(df[status_series.isin(["em andamento", "em atendimento"])])
        pendentes = len(df[status_series.isin(["pendente", "aberto", "aguardando terceiros", "aguardando solicitante"])])
        taxa_conclusao = (concluidos / total_chamados * 100) if total_chamados > 0 else 0

        m1, m2, m3, m4, m5 = st.columns(5)

        with m1:
            st.metric("Total Chamados", total_chamados)
            if st.button("👁️ Ver Todos", key="btn_kpi_total", use_container_width=True):
                limpar_filtro_dash()
                st.rerun()

        with m2:
            st.metric("🟢 Concluídos", concluidos)
            if st.button("🔍 Concluídos", key="btn_kpi_concluidos", use_container_width=True, type="primary" if st.session_state.filtro_dash_valor == "Concluídos" else "secondary"):
                st.session_state.filtro_dash_tipo = "status_grupo"
                st.session_state.filtro_dash_valor = "Concluídos"
                st.rerun()

        with m3:
            st.metric("🔵 Em Andamento", em_andamento)
            if st.button("🔍 Andamento", key="btn_kpi_andamento", use_container_width=True, type="primary" if st.session_state.filtro_dash_valor == "Em Andamento" else "secondary"):
                st.session_state.filtro_dash_tipo = "status_grupo"
                st.session_state.filtro_dash_valor = "Em Andamento"
                st.rerun()

        with m4:
            st.metric("🟡 Abertos", pendentes)
            if st.button("🔍 Abertos", key="btn_kpi_abertos", use_container_width=True, type="primary" if st.session_state.filtro_dash_valor == "Abertos" else "secondary"):
                st.session_state.filtro_dash_tipo = "status_grupo"
                st.session_state.filtro_dash_valor = "Abertos"
                st.rerun()

        with m5:
            st.metric("📈 Taxa Resolução", f"{taxa_conclusao:.1f}%")

        st.divider()

        g1, g2 = st.columns(2)

        with g1:
            st.subheader("🍩 Distribuição por Status")
            df_status = df["status"].value_counts().reset_index()
            df_status.columns = ["Status", "Quantidade"]
            fig_status = px.pie(df_status, names="Status", values="Quantidade", hole=0.45, custom_data=["Status"])
            
            evt_status = st.plotly_chart(
                aplicar_layout_plotly(fig_status), 
                use_container_width=True, 
                on_select="rerun", 
                selection_mode="points",
                key="chart_status"
            )
            processar_clique_grafico(evt_status, "status")

        with g2:
            st.subheader("⚠️ Chamados por Prioridade")
            df_prio = df["prioridade"].replace("", "Não Informado").value_counts().reset_index()
            df_prio.columns = ["Prioridade", "Quantidade"]
            fig_prio = px.bar(df_prio, x="Prioridade", y="Quantidade", text="Quantidade", color="Prioridade", custom_data=["Prioridade"])
            fig_prio.update_layout(showlegend=False)
            
            evt_prio = st.plotly_chart(
                aplicar_layout_plotly(fig_prio), 
                use_container_width=True, 
                on_select="rerun", 
                selection_mode="points",
                key="chart_prio"
            )
            processar_clique_grafico(evt_prio, "prioridade")

        st.divider()

        g3, g4 = st.columns(2)

        with g3:
            st.subheader("🏢 Demandas por Departamento")
            df_dep = df["departamento"].replace("", "Outros").value_counts().head(10).reset_index()
            df_dep.columns = ["Departamento", "Quantidade"]
            fig_dep = px.bar(df_dep, y="Departamento", x="Quantidade", orientation="h", text="Quantidade", custom_data=["Departamento"])
            fig_dep.update_layout(yaxis=dict(autorange="reversed"))
            
            evt_dep = st.plotly_chart(
                aplicar_layout_plotly(fig_dep), 
                use_container_width=True, 
                on_select="rerun", 
                selection_mode="points",
                key="chart_dep"
            )
            processar_clique_grafico(evt_dep, "departamento")

        with g4:
            st.subheader("👨‍💻 Atendimentos por Técnico")
            df_tec = df["tecnico"].replace("", "Não Atribuído").value_counts().head(10).reset_index()
            df_tec.columns = ["Técnico", "Quantidade"]
            fig_tec = px.bar(df_tec, x="Técnico", y="Quantidade", text="Quantidade", custom_data=["Técnico"])
            
            evt_tec = st.plotly_chart(
                aplicar_layout_plotly(fig_tec), 
                use_container_width=True, 
                on_select="rerun", 
                selection_mode="points",
                key="chart_tec"
            )
            processar_clique_grafico(evt_tec, "tecnico")

        st.divider()

        # TABELA DE LISTAGEM FILTRADA DA OPERAÇÃO
        df_filtrado_dash = df.copy()
        tipo_filtro = st.session_state.filtro_dash_tipo
        valor_filtro = st.session_state.filtro_dash_valor

        if tipo_filtro and valor_filtro:
            if tipo_filtro == "status_grupo":
                s_series = df_filtrado_dash["status"].astype(str).str.strip().str.casefold()
                if valor_filtro == "Concluídos":
                    df_filtrado_dash = df_filtrado_dash[s_series.isin(["concluído", "concluido", "finalizado", "fechado"])]
                elif valor_filtro == "Em Andamento":
                    df_filtrado_dash = df_filtrado_dash[s_series.isin(["em andamento", "em atendimento"])]
                elif valor_filtro == "Abertos":
                    df_filtrado_dash = df_filtrado_dash[s_series.isin(["pendente", "aberto", "aguardando terceiros", "aguardando solicitante"])]

            elif tipo_filtro in ["status", "prioridade", "departamento", "tecnico", "cidade"]:
                df_filtrado_dash = df_filtrado_dash[
                    df_filtrado_dash[tipo_filtro].astype(str).str.strip().str.casefold() == str(valor_filtro).strip().casefold()
                ]

            col_tit, col_btn = st.columns([8, 2])
            with col_tit:
                st.subheader(f"🎯 Chamados Filtrados por **{tipo_filtro.capitalize()} = '{valor_filtro}'**")
                st.caption(f"Mostrando {len(df_filtrado_dash)} de {len(df)} chamados totais.")
            with col_btn:
                st.button("❌ Limpar Filtro", on_click=limpar_filtro_dash, type="primary", use_container_width=True, key="btn_clear_op")

        else:
            st.subheader(f"📋 Lista Completa de Chamados ({len(df_filtrado_dash)} chamados)")

        if df_filtrado_dash.empty:
            st.warning("Nenhum chamado encontrado para este filtro.")
        else:
            for _, cham in df_filtrado_dash.iterrows():
                t_id = str(cham["id_chamado"]).strip()
                pct, status_txt = calcular_progresso(cham)
                badge_html = get_status_badge(cham.get("status", ""))
                bar_html = render_barra_progresso(pct, status_txt)

                with st.container(border=True):
                    col1, col2 = st.columns([7, 3])
                    with col1:
                        st.markdown(f"""
                        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 6px;">
                            <span style="font-size: 1.2rem; font-weight: 800;">🎫 #{t_id}</span>
                            {badge_html}
                        </div>
                        <div style="font-size: 1rem; font-weight: 700;">{cham.get('titulo', 'Sem título')}</div>
                        <div style="font-size: 0.85rem; color: {text_muted};">👤 {cham.get('solicitante', '-')} | 🏢 {cham.get('departamento', '-')} | ⚠️ Prioridade: {cham.get('prioridade', '-')}</div>
                        """, unsafe_allow_html=True)
                        st.markdown(bar_html, unsafe_allow_html=True)

                    with col2:
                        st.write("")
                        st.write("")
                        st.button("👁️ Ver detalhes", key=f"btn_dash_list_{t_id}", on_click=abrir_ticket, args=(t_id,), use_container_width=True)


    # ============================================================
    # ABA 2: SATISFAÇÃO & NOTAS (CSAT) - EXCLUSIVA
    # ============================================================
    with tab_csat:
        st.subheader("⭐ Indicadores de Qualidade e Satisfação (CSAT)")

        # Dataset filtrado apenas com notas válidas
        df_avaliados = df.dropna(subset=["nota_num"]).copy()
        df_avaliados["nota_num"] = df_avaliados["nota_num"].astype(float)

        if df_avaliados.empty:
            st.info("ℹ️ Ainda não há chamados com avaliações gravadas na planilha para exibir gráficos de satisfação.")
        else:
            # DATAS PARA FILTRAGEM POR PERÍODO
            data_maxima = df_avaliados["data_aval_dt"].max()
            if pd.isna(data_maxima):
                data_maxima = pd.Timestamp.now()

            eval_30d = df_avaliados[df_avaliados["data_aval_dt"] >= (data_maxima - pd.Timedelta(days=30))]
            eval_7d = df_avaliados[df_avaliados["data_aval_dt"] >= (data_maxima - pd.Timedelta(days=7))]

            media_geral = df_avaliados["nota_num"].mean()
            media_30d = eval_30d["nota_num"].mean() if not eval_30d.empty else media_geral
            media_7d = eval_7d["nota_num"].mean() if not eval_7d.empty else media_geral
            total_avaliacoes = len(df_avaliados)

            # CARDS DE MÉTRICAS DA NOTA
            c_n1, c_n2, c_n3, c_n4 = st.columns(4)

            with c_n1:
                st.metric(
                    "⭐ Média Geral (Todo o tempo)", 
                    f"{media_geral:.2f} / 5.0",
                    help="Média de todas as avaliações já recebidas no sistema"
                )

            with c_n2:
                delta_30d = (media_30d - media_geral) if not eval_30d.empty else 0
                st.metric(
                    "🗓️ Média (Últimos 30 dias)", 
                    f"{media_30d:.2f} / 5.0",
                    delta=f"{delta_30d:+.2f} vs Geral" if abs(delta_30d) >= 0.01 else None,
                    help="Média das notas recebidas nos últimos 30 dias"
                )

            with c_n3:
                delta_7d = (media_7d - media_geral) if not eval_7d.empty else 0
                st.metric(
                    "📅 Média (Últimos 7 dias)", 
                    f"{media_7d:.2f} / 5.0",
                    delta=f"{delta_7d:+.2f} vs Geral" if abs(delta_7d) >= 0.01 else None,
                    help="Média das notas recebidas nos últimos 7 dias"
                )

            with c_n4:
                st.metric(
                    "🗳️ Total de Avaliações", 
                    f"{total_avaliacoes}",
                    help="Quantidade total de respostas recebidas"
                )

            st.divider()

            # GRÁFICOS DA ABA SATISFAÇÃO
            csat_col1, csat_col2 = st.columns(2)

            with csat_col1:
                st.subheader("📊 Distribuição das Notas (Estrelas)")
                # Garante que mostre de 1 a 5 estrelas mesmo se alguma nota tiver 0 contagens
                dist_notas = df_avaliados["nota_num"].value_counts().reindex([5, 4, 3, 2, 1], fill_value=0).reset_index()
                dist_notas.columns = ["Nota", "Quantidade"]
                dist_notas["Estrelas"] = dist_notas["Nota"].apply(lambda n: f"{int(n)} ⭐")

                # Cores padronizadas de satisfação (Verde para 5/4, Amarelo para 3, Vermelho/Laranja para 2/1)
                cores_estrelas = {
                    "5 ⭐": "#10b981",
                    "4 ⭐": "#3b82f6",
                    "3 ⭐": "#f59e0b",
                    "2 ⭐": "#f97316",
                    "1 ⭐": "#ef4444"
                }

                fig_dist = px.bar(
                    dist_notas, 
                    x="Estrelas", 
                    y="Quantidade", 
                    text="Quantidade",
                    color="Estrelas",
                    color_discrete_map=cores_estrelas
                )
                fig_dist.update_layout(showlegend=False)
                st.plotly_chart(aplicar_layout_plotly(fig_dist), use_container_width=True)

            with csat_col2:
                st.subheader("📈 Evolução da Média de Nota por Mês")
                df_tempo = df_avaliados.dropna(subset=["data_aval_dt"]).copy()

                if df_tempo.empty:
                    st.info("Ainda não há datas de avaliação suficientes para montar a linha de tendência.")
                else:
                    df_tempo["mes_ano"] = df_tempo["data_aval_dt"].dt.strftime("%Y-%m")
                    df_evolucao = df_tempo.groupby("mes_ano").agg(
                        nota_media=("nota_num", "mean"),
                        total=("nota_num", "count")
                    ).reset_index()

                    fig_evol = px.line(
                        df_evolucao, 
                        x="mes_ano", 
                        y="nota_media", 
                        markers=True,
                        text=df_evolucao["nota_media"].round(2),
                        title="Nota Média Mensal"
                    )
                    fig_evol.update_traces(line_color=AZUL_FERPAM, line_width=3, marker_size=8)
                    fig_evol.update_yaxes(range=[1, 5.2])
                    st.plotly_chart(aplicar_layout_plotly(fig_evol), use_container_width=True)

            st.divider()

            csat_col3, csat_col4 = st.columns(2)

            with csat_col3:
                st.subheader("👨‍💻 Média de Satisfação por Técnico")
                df_tec_csat = df_avaliados.groupby("tecnico").agg(
                    nota_media=("nota_num", "mean"),
                    total=("nota_num", "count")
                ).reset_index()

                df_tec_csat["nota_media"] = df_tec_csat["nota_media"].round(2)
                df_tec_csat = df_tec_csat.sort_values("nota_media", ascending=False)

                fig_tec_csat = px.bar(
                    df_tec_csat, 
                    x="tecnico", 
                    y="nota_media", 
                    text="nota_media",
                    hover_data=["total"],
                    color="nota_media",
                    color_continuous_scale="RdYlGn"
                )
                fig_tec_csat.update_yaxes(range=[1, 5.2])
                fig_tec_csat.update_layout(coloraxis_showscale=False)
                st.plotly_chart(aplicar_layout_plotly(fig_tec_csat), use_container_width=True)

            with csat_col4:
                st.subheader("🏢 Satisfação por Departamento")
                df_dep_csat = df_avaliados.groupby("departamento").agg(
                    nota_media=("nota_num", "mean"),
                    total=("nota_num", "count")
                ).reset_index()

                df_dep_csat["nota_media"] = df_dep_csat["nota_media"].round(2)
                df_dep_csat = df_dep_csat.sort_values("nota_media", ascending=True)

                fig_dep_csat = px.bar(
                    df_dep_csat, 
                    y="departamento", 
                    x="nota_media", 
                    orientation="h",
                    text="nota_media",
                    hover_data=["total"],
                    color="nota_media",
                    color_continuous_scale="RdYlGn"
                )
                fig_dep_csat.update_xaxes(range=[1, 5.2])
                fig_dep_csat.update_layout(coloraxis_showscale=False)
                st.plotly_chart(aplicar_layout_plotly(fig_dep_csat), use_container_width=True)


    # ============================================================
    # ABA 3: FEED DE REVIEWS & FEEDBACK
    # ============================================================
    with tab_reviews:
        st.subheader("💬 Feed de Avaliações e Comentários do Usuário")
        st.caption("Acompanhe o que os solicitantes estão dizendo sobre o atendimento prestado.")

        # Filtra chamados que possuem nota OU comentário preenchido
        df_feed = df[
            (pd.notna(df["nota_num"])) | 
            (df["comentario_avaliacao"].str.lower().isin(["", "nan", "none", "null"]) == False)
        ].copy()

        if df_feed.empty:
            st.info("ℹ️ Nenhuma avaliação ou comentário foi registrado ainda.")
        else:
            # FILTROS DA ABA FEED
            f_col1, f_col2, f_col3 = st.columns([2, 2, 3])

            with f_col1:
                filtro_estrela = st.selectbox(
                    "Filtrar por Estrelas",
                    ["Todas as Notas", "5 ⭐ (Excelente)", "4 ⭐ (Bom)", "3 ⭐ (Regular)", "2 ⭐ (Ruim)", "1 ⭐ (Péssimo)"]
                )

            with f_col2:
                apenas_comentarios = st.checkbox("Apenas com Comentário de Texto", value=False)

            with f_col3:
                busca_texto = st.text_input("🔍 Buscar no comentário...", placeholder="Ex.: rápido, atencioso, demorou...")

            # Aplicação dos filtros no Feed
            if filtro_estrela != "Todas as Notas":
                num_alvo = int(filtro_estrela[0])
                df_feed = df_feed[df_feed["nota_num"] == num_alvo]

            if apenas_comentarios:
                df_feed = df_feed[~df_feed["comentario_avaliacao"].str.lower().isin(["", "nan", "none", "null"])]

            if busca_texto.strip():
                df_feed = df_feed[df_feed["comentario_avaliacao"].str.contains(busca_texto.strip(), case=False, na=False)]

            st.divider()

            if df_feed.empty:
                st.warning("Nenhum comentário/review encontrado para os filtros selecionados.")
            else:
                st.caption(f"Exibindo **{len(df_feed)}** review(s):")

                # Renderiza cada review em um card moderno
                for _, r in df_feed.iterrows():
                    t_id = str(r["id_chamado"]).strip()
                    solic = r.get("solicitante", "Solicitante não informado")
                    tec = r.get("tecnico", "Técnico não atribuído")
                    dt_aval = str(r.get("data_avaliacao", "")).strip()
                    coment = str(r.get("comentario_avaliacao", "")).strip()
                    nota_val = r.get("nota_num")

                    estrelas_str = render_estrelas(nota_val) if pd.notna(nota_val) else "Sem nota definida"

                    # Definir cor de borda do box de comentário com base na nota
                    if pd.notna(nota_val) and nota_val >= 4:
                        box_type = "success"
                    elif pd.notna(nota_val) and nota_val == 3:
                        box_type = "warning"
                    elif pd.notna(nota_val) and nota_val <= 2:
                        box_type = "error"
                    else:
                        box_type = "info"

                    with st.container(border=True):
                        c_top1, c_top2 = st.columns([7, 3])

                        with c_top1:
                            st.markdown(f"### {estrelas_str}")
                            st.markdown(f"**👤 {solic}** • *Técnico:* **{tec}**")
                            if dt_aval and dt_aval.casefold() != "nan":
                                st.caption(f"🗓️ Data da Avaliação: {dt_aval}")

                        with c_top2:
                            st.button(f"👁️ Abrir #{t_id}", key=f"btn_feed_{t_id}", on_click=abrir_ticket, args=(t_id,), use_container_width=True)

                        if coment and coment.casefold() not in ["nan", "", "none", "null"]:
                            if box_type == "success":
                                st.success(f"💬 *\"{coment}\"*")
                            elif box_type == "warning":
                                st.warning(f"💬 *\"{coment}\"*")
                            elif box_type == "error":
                                st.error(f"💬 *\"{coment}\"*")
                            else:
                                st.info(f"💬 *\"{coment}\"*")
                        else:
                            st.caption("*(Avaliação enviada sem comentário por texto)*")

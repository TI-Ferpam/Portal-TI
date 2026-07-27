import streamlit as st
import pandas as pd
import plotly.express as px
from services.sheets import carregar_chamados


# ============================================================
# CONFIGURAÇÃO DE PÁGINA
# ============================================================

st.set_page_config(
    page_title="Portal de Chamados TI",
    page_icon="🎫",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ============================================================
# CARREGAMENTO DE DADOS
# ============================================================

@st.cache_data(ttl=60)
def carregar_dados():
    return carregar_chamados()

df = carregar_dados()
df.columns = [str(col).strip() for col in df.columns]


# ============================================================
# GERENCIAMENTO DE ESTADO (SESSION STATE)
# ============================================================

if "tela" not in st.session_state:
    st.session_state.tela = "busca"

if "ticket_aberto" not in st.session_state:
    st.session_state.ticket_aberto = None

# MODO CLARO COMO PADRÃO INICIAL
if "tema" not in st.session_state:
    st.session_state.tema = "☀️ Claro"


def abrir_ticket(ticket_id):
    st.session_state.ticket_aberto = str(ticket_id).strip()
    st.session_state.tela = "ticket"


def voltar_busca():
    st.session_state.ticket_aberto = None
    st.session_state.tela = "busca"


# ============================================================
# MENU LATERAL & TEMA (DARK / LIGHT)
# ============================================================

st.sidebar.image("https://cdn-icons-png.flaticon.com/512/1063/1063376.png", width=55)
st.sidebar.title("Portal TI")

# Seleção do Tema (Modo Claro padrão)
opcao_tema = st.sidebar.selectbox(
    "🎨 Aparência / Tema",
    ["☀️ Claro", "🌙 Escuro"],
    index=0 if st.session_state.tema == "☀️ Claro" else 1,
    key="select_tema"
)
st.session_state.tema = opcao_tema
modo_escuro = (st.session_state.tema == "🌙 Escuro")

st.sidebar.divider()

# Navegação entre Telas
opcao_menu = st.sidebar.radio(
    "📍 Navegação",
    ["🔍 Consultar Chamados", "📊 Dashboard de Indicadores"],
    index=0 if st.session_state.tela in ["busca", "ticket"] else 1
)

if opcao_menu == "📊 Dashboard de Indicadores" and st.session_state.tela != "dashboard":
    st.session_state.tela = "dashboard"
elif opcao_menu == "🔍 Consultar Chamados" and st.session_state.tela == "dashboard":
    st.session_state.tela = "busca"


# ============================================================
# ESTILIZAÇÃO CSS CUSTOMIZADA
# ============================================================

if modo_escuro:
    bg_app = "#0b0f19"
    bg_sidebar = "#111827"
    bg_card = "#1e293b"
    border_card = "#334155"
    text_main = "#f8fafc"
    text_muted = "#94a3b8"
    plotly_template = "plotly_dark"
    input_bg = "#1e293b"
else:
    bg_app = "#f8fafc"
    bg_sidebar = "#ffffff"
    bg_card = "#ffffff"
    border_card = "#e2e8f0"
    text_main = "#0f172a"
    text_muted = "#64748b"
    plotly_template = "plotly_white"
    input_bg = "#ffffff"

st.markdown(f"""
<style>
    /* Fundo principal */
    .stApp {{
        background-color: {bg_app} !important;
    }}
    
    /* Sidebar */
    section[data-testid="stSidebar"] {{
        background-color: {bg_sidebar} !important;
        border-right: 1px solid {border_card};
    }}
    
    /* Cartões de Métricas KPI */
    div[data-testid="stMetric"] {{
        background-color: {bg_card} !important;
        border: 1px solid {border_card} !important;
        border-radius: 12px !important;
        padding: 16px 20px !important;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
    }}
    
    div[data-testid="stMetricLabel"] label {{
        color: {text_muted} !important;
        font-size: 0.88rem !important;
        font-weight: 600 !important;
    }}
    
    div[data-testid="stMetricValue"] div {{
        color: {text_main} !important;
        font-weight: 800 !important;
    }}
    
    /* Container dos Cards de Chamados */
    div[data-testid="stVerticalBlock"] > div[style*="border"] {{
        background-color: {bg_card} !important;
        border: 1px solid {border_card} !important;
        border-radius: 14px !important;
        padding: 18px !important;
        box-shadow: 0 4px 14px rgba(0, 0, 0, 0.06) !important;
    }}
    
    /* Textos Gerais */
    h1, h2, h3, h4, h5, h6, label, p, span {{
        color: {text_main} !important;
    }}

    .stCaption {{
        color: {text_muted} !important;
    }}

    /* Entradas e Selectbox */
    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div {{
        background-color: {input_bg} !important;
        border-color: {border_card} !important;
        color: {text_main} !important;
        border-radius: 8px !important;
    }}

    /* Botões */
    .stButton button {{
        border-radius: 8px !important;
        font-weight: 600 !important;
    }}

    /* Ocultar elementos desnecessários */
    #MainMenu {{visibility: hidden;}}
    footer {{visibility: hidden;}}
</style>
""", unsafe_allow_html=True)


# ============================================================
# FUNÇÕES DE RENDERIZAÇÃO DE STATUS E BARRA DE PROGRESSO
# ============================================================

def calcular_progresso(chamado):
    status = str(chamado.get("status", "")).strip().casefold()
    tecnico = str(chamado.get("tecnico", "")).strip().casefold()
    atividade = str(chamado.get("atividade_realizada", "")).strip().casefold()

    if status in ["concluído", "concluido", "finalizado", "fechado"]:
        return 100, "🟢 Chamado Finalizado"
    elif status in ["em andamento", "em atendimento"]:
        if atividade and atividade != "nan" and atividade != "":
            return 80, "🔵 Em Atendimento (Atividade Registrada)"
        return 60, "🔵 Em Atendimento pelo Técnico"
    elif tecnico and tecnico != "nan" and tecnico != "" and tecnico != "não atribuído":
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
        color = "#2563eb"
        bg = "rgba(37, 99, 235, 0.12)"
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
    if pct == 100:
        bar_color = "#10b981" # Verde
    elif pct >= 50:
        bar_color = "#2563eb" # Azul
    else:
        bar_color = "#d97706" # Laranja

    badge_bg = f"{bar_color}18"

    return f"""
    <div style="margin-top: 10px; margin-bottom: 6px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <span style="font-size: 0.83rem; font-weight: 600; color: {text_muted};">{texto_estagio}</span>
            <span style="font-size: 0.85rem; font-weight: 800; color: {bar_color}; background-color: {badge_bg}; padding: 2px 10px; border-radius: 12px;">{pct}%</span>
        </div>
        <div style="width: 100%; background-color: {border_card}; height: 10px; border-radius: 6px; overflow: hidden;">
            <div style="width: {pct}%; background-color: {bar_color}; height: 100%; border-radius: 6px; transition: width 0.4s ease;"></div>
        </div>
    </div>
    """


# ============================================================
# TELA 1: DETALHES DO TICKET
# ============================================================

if st.session_state.tela == "ticket" and st.session_state.ticket_aberto is not None:

    ticket_id = str(st.session_state.ticket_aberto).strip()

    resultado = df[
        df["id_chamado"].astype(str).str.strip().str.casefold() == ticket_id.casefold()
    ]

    if resultado.empty:
        st.error(f"Não foi possível encontrar o ticket #{ticket_id}.")
        st.button("← Voltar para a busca", on_click=voltar_busca)
        st.stop()

    chamado = resultado.iloc[0]
    percentual, etapa_nome = calcular_progresso(chamado)

    st.button("← Voltar para meus tickets", on_click=voltar_busca)

    st.title(f"🎫 Ticket #{ticket_id}")
    st.caption(f"Solicitante: {chamado.get('solicitante', 'N/A')}")

    # Barra de Progresso Customizada
    st.subheader("📌 Progresso da Resolução")
    st.markdown(render_barra_progresso(percentual, etapa_nome), unsafe_allow_html=True)

    st.divider()

    # Cards de Informações
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

    st.stop()


# ============================================================
# TELA 2: BUSCA DE CHAMADOS
# ============================================================

if st.session_state.tela == "busca":

    st.title("🎫 Portal de Chamados de TI")
    st.write("Acompanhe e consulte o andamento dos seus chamados técnicos.")

    nomes = df["solicitante"].dropna().astype(str).str.strip()
    nomes = sorted(nomes[nomes != ""].unique(), key=str.casefold)

    c1, c2 = st.columns(2)
    with c1:
        ticket_input = st.text_input("Número do Ticket", placeholder="Ex.: 933")
    with c2:
        nome_input = st.selectbox(
            "Nome do Solicitante",
            options=[""] + nomes,
            format_func=lambda x: "Digite ou selecione seu nome..." if x == "" else x
        )

    pesquisar = st.button("🔍 Pesquisar Chamados", type="primary", use_container_width=True)

    if pesquisar:
        res = df.copy()

        if ticket_input.strip():
            res = res[res["id_chamado"].astype(str).str.strip().str.contains(ticket_input.strip(), case=False, na=False)]

        if nome_input:
            res = res[res["solicitante"].astype(str).str.strip().str.casefold() == nome_input.strip().casefold()]

        st.divider()

        if not ticket_input.strip() and not nome_input:
            st.info("💡 Informe o número do ticket ou selecione o solicitante para iniciar a busca.")
        elif res.empty:
            st.warning("Nenhum chamado foi localizado com os dados informados.")
        else:
            st.subheader(f"Encontrado(s) {len(res)} chamado(s)")

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
                            <span style="font-size: 1.25rem; font-weight: 800; color: {text_main};">🎫 #{t_id}</span>
                            {badge_html}
                        </div>
                        <div style="font-size: 1.05rem; font-weight: 700; color: {text_main}; margin-bottom: 4px;">
                            {cham.get('titulo', 'Sem título')}
                        </div>
                        <div style="font-size: 0.85rem; color: {text_muted}; margin-bottom: 8px;">
                            👤 <b>{cham.get('solicitante', '-')}</b> &nbsp;|&nbsp; 🏢 <b>{cham.get('departamento', '-')}</b>
                        </div>
                        """, unsafe_allow_html=True)

                        st.markdown(bar_html, unsafe_allow_html=True)

                    with col2:
                        st.write("")
                        st.write("")
                        st.button(
                            "👁️ Ver detalhes",
                            key=f"btn_ver_{t_id}",
                            on_click=abrir_ticket,
                            args=(t_id,),
                            use_container_width=True
                        )


# ============================================================
# TELA 3: DASHBOARD DE INDICADORES
# ============================================================

if st.session_state.tela == "dashboard":

    st.title("📊 Dashboard de Indicadores de TI")
    st.write("Análise visual detalhada sobre volumetria, prazos, técnicos e departamentos.")

    total_chamados = len(df)
    status_series = df["status"].astype(str).str.strip().str.casefold()
    concluidos = len(df[status_series.isin(["concluído", "concluido", "finalizado", "fechado"])])
    em_andamento = len(df[status_series.isin(["em andamento", "em atendimento"])])
    pendentes = len(df[status_series.isin(["pendente", "aberto"])])
    taxa_conclusao = (concluidos / total_chamados * 100) if total_chamados > 0 else 0

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total de Chamados", total_chamados)
    m2.metric("🟢 Concluídos", concluidos)
    m3.metric("🔵 Em Andamento", em_andamento)
    m4.metric("🟡 Abertos", pendentes)
    m5.metric("📈 Taxa de Resolução", f"{taxa_conclusao:.1f}%")

    st.divider()

    def aplicar_layout_plotly(fig):
        fig.update_layout(
            template=plotly_template,
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color=text_main),
            margin=dict(t=30, b=20, l=20, r=20)
        )
        return fig

    g1, g2 = st.columns(2)

    with g1:
        st.subheader("🍩 Distribuição por Status")
        df_status = df["status"].value_counts().reset_index()
        df_status.columns = ["Status", "Quantidade"]
        
        fig_status = px.pie(
            df_status, 
            names="Status", 
            values="Quantidade", 
            hole=0.45,
            color_discrete_sequence=px.colors.qualitative.Set2
        )
        st.plotly_chart(aplicar_layout_plotly(fig_status), use_container_width=True)

    with g2:
        st.subheader("⚠️ Chamados por Prioridade")
        df_prio = df["prioridade"].fillna("Não Informado").value_counts().reset_index()
        df_prio.columns = ["Prioridade", "Quantidade"]

        fig_prio = px.bar(
            df_prio, 
            x="Prioridade", 
            y="Quantidade", 
            text="Quantidade",
            color="Prioridade",
            color_discrete_sequence=px.colors.qualitative.Pastel
        )
        fig_prio.update_layout(showlegend=False)
        st.plotly_chart(aplicar_layout_plotly(fig_prio), use_container_width=True)

    st.divider()

    g3, g4 = st.columns(2)

    with g3:
        st.subheader("🏢 Demandas por Departamento")
        df_dep = df["departamento"].fillna("Outros").value_counts().head(8).reset_index()
        df_dep.columns = ["Departamento", "Quantidade"]

        fig_dep = px.bar(
            df_dep, 
            y="Departamento", 
            x="Quantidade", 
            orientation="h",
            text="Quantidade",
            color_discrete_sequence=["#0284c7" if not modo_escuro else "#38bdf8"]
        )
        fig_dep.update_layout(yaxis=dict(autorange="reversed"))
        st.plotly_chart(aplicar_layout_plotly(fig_dep), use_container_width=True)

    with g4:
        st.subheader("👨‍💻 Atendimentos por Técnico")
        df_tec = df["tecnico"].fillna("Não Atribuído").value_counts().reset_index()
        df_tec.columns = ["Técnico", "Quantidade"]

        fig_tec = px.bar(
            df_tec, 
            x="Técnico", 
            y="Quantidade", 
            text="Quantidade",
            color_discrete_sequence=["#10b981" if not modo_escuro else "#34d399"]
        )
        st.plotly_chart(aplicar_layout_plotly(fig_tec), use_container_width=True)

    st.divider()

    st.subheader("📍 Volume por Cidade / Unidade")
    df_cid = df["cidade"].fillna("Não Informado").value_counts().reset_index()
    df_cid.columns = ["Cidade", "Quantidade"]

    fig_cid = px.bar(
        df_cid, 
        x="Cidade", 
        y="Quantidade", 
        text="Quantidade",
        color="Cidade"
    )
    fig_cid.update_layout(showlegend=False)
    st.plotly_chart(aplicar_layout_plotly(fig_cid), use_container_width=True)
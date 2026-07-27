import streamlit as st
import pandas as pd
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
# CARREGAMENTO E TRATAMENTO DE DADOS
# ============================================================

@st.cache_data(ttl=60)
def carregar_dados():
    try:
        data = carregar_chamados()
        if isinstance(data, pd.DataFrame):
            df_raw = data
        else:
            df_raw = pd.DataFrame(data)
        
        # Padronização dos nomes das colunas
        df_raw.columns = [str(col).strip().lower() for col in df_raw.columns]
        
        colunas_obrigatorias = [
            "id_chamado", "solicitante", "titulo", "ocorrencia", 
            "status", "prioridade", "departamento", "tecnico", 
            "cidade", "atividade_realizada"
        ]
        
        for col in colunas_obrigatorias:
            if col not in df_raw.columns:
                df_raw[col] = ""
                
        # Limpeza básica nos campos de texto
        df_raw["solicitante"] = df_raw["solicitante"].astype(str).str.strip()
        df_raw["id_chamado"] = df_raw["id_chamado"].astype(str).str.strip()
        df_raw["status"] = df_raw["status"].astype(str).str.strip()
        df_raw["prioridade"] = df_raw["prioridade"].astype(str).str.strip()
        df_raw["departamento"] = df_raw["departamento"].astype(str).str.strip()
        df_raw["tecnico"] = df_raw["tecnico"].astype(str).str.strip()
        df_raw["cidade"] = df_raw["cidade"].astype(str).str.strip()
        
        return df_raw
    except Exception as e:
        st.error(f"Erro ao carregar dados da planilha: {e}")
        return pd.DataFrame()

df = carregar_dados()


# ============================================================
# ESTADOS DA SESSÃO (SESSION STATE)
# ============================================================

if "tela" not in st.session_state:
    st.session_state.tela = "busca"

if "ticket_aberto" not in st.session_state:
    st.session_state.ticket_aberto = None

if "tema" not in st.session_state:
    st.session_state.tema = "🌙 Escuro"

if "autenticado_admin" not in st.session_state:
    st.session_state.autenticado_admin = False

# Estados de filtro dinâmico para a Dashboard Interativa
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


# Listas auxiliares para selects
lista_solicitantes_admin = sorted(
    list(set([s for s in df["solicitante"].unique() if s and s.casefold() != "nan"])),
    key=str.casefold
)

lista_status_opcoes = ["Todos os Status"] + sorted(
    list(set([s for s in df["status"].unique() if s and s.casefold() != "nan"])),
    key=str.casefold
)


# ============================================================
# MENU LATERAL & SISTEMA DE LOGIN ADMIN / ADMIN
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

# Alternador de Tema
opcao_tema = st.sidebar.selectbox(
    "🎨 Aparência / Tema",
    ["☀️ Claro", "🌙 Escuro"],
    index=0 if st.session_state.tema == "☀️ Claro" else 1,
    key="select_tema"
)
st.session_state.tema = opcao_tema
modo_escuro = (st.session_state.tema == "🌙 Escuro")

st.sidebar.divider()

# Navegação
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
    .stApp {{ background-color: {bg_app} !important; }}
    section[data-testid="stSidebar"] {{ background-color: {bg_sidebar} !important; border-right: 1px solid {border_card}; }}
    
    div[data-testid="stMetric"] {{
        background-color: {bg_card} !important;
        border: 1px solid {border_card} !important;
        border-radius: 12px !important;
        padding: 16px 20px !important;
    }}
    div[data-testid="stMetricLabel"] label {{ color: {text_muted} !important; font-weight: 600 !important; }}
    div[data-testid="stMetricValue"] div {{ color: {text_main} !important; font-weight: 800 !important; }}
    
    div[data-testid="stVerticalBlock"] > div[style*="border"] {{
        background-color: {bg_card} !important;
        border: 1px solid {border_card} !important;
        border-radius: 14px !important;
        padding: 18px !important;
    }}
    
    h1, h2, h3, h4, h5, h6, label, p, span {{ color: {text_main} !important; }}
    .stCaption {{ color: {text_muted} !important; }}

    div[data-baseweb="input"] > div, div[data-baseweb="select"] > div {{
        background-color: {input_bg} !important;
        border-color: {border_card} !important;
        color: {text_main} !important;
        border-radius: 8px !important;
    }}

    .stButton button {{ border-radius: 8px !important; font-weight: 600 !important; }}
    #MainMenu {{visibility: hidden;}}
    footer {{visibility: hidden;}}
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
    bar_color = "#10b981" if pct == 100 else ("#2563eb" if pct >= 50 else "#d97706")
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


def extrair_valor_clicado(event):
    """Extrai o nome do elemento clicado em um gráfico Plotly do Streamlit"""
    if not event or "selection" not in event:
        return None
    points = event["selection"].get("points", [])
    if not points:
        return None
    
    p = points[0]
    
    # 1. Customdata (mais preciso)
    if "customdata" in p and p["customdata"]:
        val = p["customdata"]
        if isinstance(val, list) and len(val) > 0:
            return str(val[0]).strip()
        return str(val).strip()
    
    # 2. Label (Gráficos de Rosca / Pizza)
    if "label" in p and p["label"] is not None:
        return str(p["label"]).strip()
        
    # 3. Y para barras horizontais, X para barras verticais
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
# TELA 3: DASHBOARD INTERATIVA (DRILL-DOWN COMPLETO)
# ============================================================

if st.session_state.tela == "dashboard":

    if not st.session_state.autenticado_admin:
        st.error("⛔ Acesso Negado! Faça login como admin no menu lateral para visualizar o Dashboard.")
        st.stop()

    st.title("📊 Dashboard de Indicadores de TI")
    st.caption("⚡ **Interativo**: Clique nos botões dos cartões ou em qualquer barra/fatia dos gráficos para filtrar os chamados!")

    # Cálculo dos indicadores principais
    total_chamados = len(df)
    status_series = df["status"].astype(str).str.strip().str.casefold()
    concluidos = len(df[status_series.isin(["concluído", "concluido", "finalizado", "fechado"])])
    em_andamento = len(df[status_series.isin(["em andamento", "em atendimento"])])
    pendentes = len(df[status_series.isin(["pendente", "aberto", "aguardando terceiros", "aguardando solicitante"])])
    taxa_conclusao = (concluidos / total_chamados * 100) if total_chamados > 0 else 0

    # CARTÕES CLICÁVEIS (KPIS)
    m1, m2, m3, m4, m5 = st.columns(5)

    with m1:
        st.metric("Total Chamados", total_chamados)
        if st.button("👁️ Ver Todos", key="btn_kpi_total", use_container_width=True):
            limpar_filtro_dash()
            st.rerun()

    with m2:
        st.metric("🟢 Concluídos", concluidos)
        if st.button("🔍 Filtrar Concluídos", key="btn_kpi_concluidos", use_container_width=True, type="primary" if st.session_state.filtro_dash_valor == "Concluídos" else "secondary"):
            st.session_state.filtro_dash_tipo = "status_grupo"
            st.session_state.filtro_dash_valor = "Concluídos"
            st.rerun()

    with m3:
        st.metric("🔵 Em Andamento", em_andamento)
        if st.button("🔍 Filtrar Andamento", key="btn_kpi_andamento", use_container_width=True, type="primary" if st.session_state.filtro_dash_valor == "Em Andamento" else "secondary"):
            st.session_state.filtro_dash_tipo = "status_grupo"
            st.session_state.filtro_dash_valor = "Em Andamento"
            st.rerun()

    with m4:
        st.metric("🟡 Abertos", pendentes)
        if st.button("🔍 Filtrar Abertos", key="btn_kpi_abertos", use_container_width=True, type="primary" if st.session_state.filtro_dash_valor == "Abertos" else "secondary"):
            st.session_state.filtro_dash_tipo = "status_grupo"
            st.session_state.filtro_dash_valor = "Abertos"
            st.rerun()

    with m5:
        st.metric("📈 Taxa Resolução", f"{taxa_conclusao:.1f}%")

    st.divider()

    # Função para aplicar tema Plotly
    def aplicar_layout_plotly(fig):
        fig.update_layout(
            template=plotly_template,
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color=text_main),
            margin=dict(t=30, b=20, l=20, r=20)
        )
        return fig

    # GRÁFICOS INTERATIVOS COM SELEÇÃO ATIVA
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
        df_prio = df["prioridade"].fillna("Não Informado").value_counts().reset_index()
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
        df_dep = df["departamento"].fillna("Outros").value_counts().head(10).reset_index()
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
        df_tec = df["tecnico"].fillna("Não Atribuído").value_counts().head(10).reset_index()
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


    # ============================================================
    # EXIBIÇÃO DINÂMICA DA LISTA DE CHAMADOS FILTRADOS
    # ============================================================

    st.divider()

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
            st.button("❌ Limpar Filtro", on_click=limpar_filtro_dash, type="primary", use_container_width=True)

    else:
        st.subheader(f"📋 Lista Completa de Chamados ({len(df_filtrado_dash)} chamados)")
        st.caption("Clique nos botões superiores ou nas barras/fatias dos gráficos para aplicar filtros dinâmicos.")

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

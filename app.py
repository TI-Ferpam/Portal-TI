import pandas as pd
import streamlit as st
import plotly.express as px
from services.sheets import carregar_chamados

# ============================================================
# CONFIGURAÇÃO DA PÁGINA
# ============================================================

st.set_page_config(
    page_title="Portal de Chamados TI",
    page_icon="🎫",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Filtro estrito por técnicos solicitados
TECNICOS_PERMITIDOS = ["Matheus Juliati", "Jair de Alcantara"]
LIMITE_ROADMAP_MINUTOS = 5 * 24 * 60  # 5 dias em minutos = 7200 min

MESES_DIC = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
}

# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def formatar_tempo(minutos):
    """Converte minutos numéricos em texto legível (ex: '45 min', '2h 35m', '1d 4h 12m')."""
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
# CARREGAMENTO E TRATAMENTO DE DADOS
# ============================================================

@st.cache_data(ttl=60)
def carregar_dados():
    colunas_obrigatorias = [
        "id_chamado", "solicitante", "titulo", "ocorrencia", "status",
        "prioridade", "tecnico", "cidade",
        "atividade_realizada", "nota_atendimento", "data_avaliacao", "comentario_avaliacao",
        "data_hora_abertura", "data_inicial", "data_tecnico", "data_conclusao", "data_final"
    ]

    try:
        data = carregar_chamados()
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
            df_empty["ano_abertura"] = pd.Series(dtype=float)
            df_empty["mes_num_abertura"] = pd.Series(dtype=float)
            df_empty["mes_nome_abertura"] = pd.Series(dtype=str)
            df_empty["dt_aval_parsed"] = pd.Series(dtype="datetime64[ns]")
            return df_empty

        # Normalização de colunas
        df_raw.columns = [str(col).strip().lower() for col in df_raw.columns]
        df_raw = df_raw.loc[:, df_raw.columns != ""]
        df_raw = df_raw.loc[:, ~df_raw.columns.duplicated()]

        mapeamento_colunas = {
            "id": "id_chamado",
            "ticket": "id_chamado",
            "n_chamado": "id_chamado",
            "numero": "id_chamado",
            "num_chamado": "id_chamado",
            "descricao": "ocorrencia",
            "detalhes": "ocorrencia",
            "solucao": "atividade_realizada",
            "resolucao": "atividade_realizada",
            "nota": "nota_atendimento",
            "avaliacao": "nota_atendimento",
        }
        df_raw = df_raw.rename(columns=mapeamento_colunas)

        for col in colunas_obrigatorias:
            if col not in df_raw.columns:
                df_raw[col] = ""

        for col in ["id_chamado", "solicitante", "titulo", "ocorrencia", "status", 
                    "prioridade", "tecnico", "cidade", "atividade_realizada"]:
            df_raw[col] = df_raw[col].fillna("").astype(str).str.strip()
            df_raw[col] = df_raw[col].replace({"nan": "", "None": "", "null": "", "<NA>": ""})

        # Apenas os dois técnicos permitidos
        df_raw = df_raw[df_raw["tecnico"].isin(TECNICOS_PERMITIDOS)].copy()

        nota_limpa = df_raw["nota_atendimento"].astype(str).str.replace(",", ".", regex=False).str.strip()
        df_raw["nota_num"] = pd.to_numeric(nota_limpa, errors="coerce")

        # Tratamento de Datas
        df_raw["dt_abertura"] = pd.to_datetime(df_raw["data_hora_abertura"], dayfirst=True, errors="coerce").fillna(
            pd.to_datetime(df_raw["data_inicial"], dayfirst=True, errors="coerce")
        )
        df_raw["dt_tecnico"] = pd.to_datetime(df_raw["data_tecnico"], dayfirst=True, errors="coerce")
        df_raw["dt_conclusao_efetiva"] = pd.to_datetime(df_raw["data_conclusao"], dayfirst=True, errors="coerce").fillna(
            pd.to_datetime(df_raw["data_final"], dayfirst=True, errors="coerce")
        )
        
        df_raw["dt_aval_parsed"] = pd.to_datetime(df_raw["data_avaliacao"], dayfirst=True, errors="coerce").fillna(df_raw["dt_conclusao_efetiva"])

        df_raw["ano_abertura"] = df_raw["dt_abertura"].dt.year
        df_raw["mes_num_abertura"] = df_raw["dt_abertura"].dt.month
        df_raw["mes_nome_abertura"] = df_raw["mes_num_abertura"].map(MESES_DIC)

        # Tempos em minutos
        df_raw["min_total"] = (df_raw["dt_conclusao_efetiva"] - df_raw["dt_abertura"]).dt.total_seconds() / 60.0
        df_raw["min_ate_tecnico"] = (df_raw["dt_tecnico"] - df_raw["dt_abertura"]).dt.total_seconds() / 60.0
        df_raw["min_resolucao"] = (df_raw["dt_conclusao_efetiva"] - df_raw["dt_tecnico"]).dt.total_seconds() / 60.0

        df_raw["sla_valido"] = (
            df_raw["dt_abertura"].notna() &
            df_raw["dt_conclusao_efetiva"].notna() &
            (df_raw["min_total"] >= 0)
        )

        df_raw["eh_roadmap"] = (df_raw["min_total"] >= LIMITE_ROADMAP_MINUTOS)

        return df_raw

    except Exception as e:
        st.error(f"Erro ao carregar dados da planilha: {e}")
        return pd.DataFrame(columns=colunas_obrigatorias)

df = carregar_dados()

# ============================================================
# CLASSIFICAÇÃO DE STATUS
# ============================================================

def classificar_status_grupo(status_str):
    if not status_str or str(status_str).strip() == "" or str(status_str).strip().lower() == "nan":
        return "Abertos"
    s = str(status_str).strip().casefold()
    concluidos_kw = ["concluído", "concluido", "finalizado", "fechado", "resolvido", "encerrado", "cancelado"]
    andamento_kw = ["em andamento", "em atendimento", "atendendo", "execução", "execucao", "iniciado", "aguardando"]

    if any(kw in s for kw in concluidos_kw):
        return "Concluídos"
    elif any(kw in s for kw in andamento_kw):
        return "Em Andamento"
    else:
        return "Abertos"

# ============================================================
# ESTADOS DA SESSÃO
# ============================================================

for key, val in [("tela", "busca"), ("ticket_aberto", None), ("autenticado_admin", False), ("filtro_tec", "Todos")]:
    if key not in st.session_state:
        st.session_state[key] = val

def abrir_ticket(ticket_id):
    st.session_state.ticket_aberto = str(ticket_id).strip()
    st.session_state.tela = "ticket"

def voltar_busca():
    st.session_state.ticket_aberto = None
    st.session_state.tela = "busca"

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
    div[data-testid="stMetric"] {{ border: 1px solid #cbd5e1 !important; border-radius: 12px !important; padding: 16px !important; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
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
        st.rerun()

st.sidebar.divider()
opcoes_menu = ["🔍 Consultar Chamados"]
if st.session_state.autenticado_admin:
    opcoes_menu.append("📊 Dashboard de Indicadores")

opcao_menu = st.sidebar.radio("📍 Navegação", opcoes_menu, index=0 if st.session_state.tela in ["busca", "ticket"] else 1)

if opcao_menu == "📊 Dashboard de Indicadores" and st.session_state.tela != "dashboard":
    st.session_state.tela = "dashboard"
elif opcao_menu == "🔍 Consultar Chamados" and st.session_state.tela == "dashboard":
    st.session_state.tela = "busca"

# ============================================================
# FUNÇÕES DE RENDERIZAÇÃO DE STATUS/BARRA
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
    grupo = classificar_status_grupo(status_clean)
    color, bg, icon = ("#10b981", "rgba(16, 185, 129, 0.12)", "🟢") if grupo == "Concluídos" else ((AZUL_FERPAM, "rgba(0, 51, 153, 0.12)", "🔵") if grupo == "Em Andamento" else ("#d97706", "rgba(217, 119, 6, 0.12)", "🟡"))
    return f"""<span style="background-color: {bg}; color: {color}; font-weight: 700; font-size: 0.82rem; padding: 4px 12px; border-radius: 20px; border: 1px solid {color}44; display: inline-flex; align-items: center; gap: 6px;">{icon} {status_clean if status_clean else 'Aberto'}</span>"""

def render_barra_progresso(pct, texto_estagio):
    bar_color = "#10b981" if pct == 100 else (AZUL_FERPAM if pct >= 50 else "#d97706")
    return f"""
    <div style="margin-top: 10px; margin-bottom: 6px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <span style="font-size: 0.83rem; font-weight: 600; color: #64748b;">{texto_estagio}</span>
            <span style="font-size: 0.85rem; font-weight: 800; color: {bar_color}; background-color: {bar_color}18; padding: 2px 10px; border-radius: 12px;">{pct}%</span>
        </div>
        <div style="width: 100%; background-color: #cbd5e1; height: 10px; border-radius: 6px; overflow: hidden;">
            <div style="width: {pct}%; background-color: {bar_color}; height: 100%; border-radius: 6px;"></div>
        </div>
    </div>
    """

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
    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Status Atual**")
        st.markdown(get_status_badge(chamado["status"]), unsafe_allow_html=True)
        st.write("")
        st.markdown("**👤 Solicitante**")
        st.write(chamado.get("solicitante", "-"))
    with col2:
        st.markdown("**⚠️ Prioridade**")
        st.write(chamado.get("prioridade", "-"))
        st.markdown("**👨‍💻 Técnico Responsável**")
        st.write(chamado.get("tecnico", "-"))

    st.divider()

    st.subheader("⏱️ Tempos de Atendimento")
    if chamado.get("sla_valido"):
        t1, t2, t3 = st.columns(3)
        with t1:
            st.metric("⏳ Tempo até Assumir", formatar_tempo(chamado.get("min_ate_tecnico")))
        with t2:
            st.metric("🔧 Tempo de Resolução", formatar_tempo(chamado.get("min_resolucao")))
        with t3:
            st.metric("🏁 Tempo Total", formatar_tempo(chamado.get("min_total")))
    else:
        st.info("ℹ️ Chamado em aberto ou sem todas as datas registradas para cálculo de SLA.")

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
# TELA DE BUSCA DE CHAMADOS
# ============================================================

if st.session_state.tela == "busca":
    st.title("🎫 Portal de Consulta de Chamados")
    
    c1, c2, c3 = st.columns([1.5, 2, 1.5])
    with c1: input_ticket = st.text_input("Número do Chamado", placeholder="Ex.: 933")
    with c2: input_tec = st.selectbox("Filtrar por Técnico", options=["Todos"] + TECNICOS_PERMITIDOS)
    with c3: input_status = st.selectbox("Status", options=lista_status_opcoes)
    
    res = df.copy()
    if input_ticket.strip(): res = res[res["id_chamado"].str.contains(input_ticket.strip(), case=False, na=False)]
    if input_tec != "Todos": res = res[res["tecnico"].str.casefold() == input_tec.casefold()]
    if input_status != "Todos os Status": res = res[res["status"].str.casefold() == input_status.casefold()]

    st.divider()
    if res.empty:
        st.warning("Nenhum chamado foi encontrado com esses critérios.")
    else:
        st.subheader(f"Localizado(s) {len(res)} chamado(s):")
        for idx, cham in res.reset_index(drop=True).iterrows():
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
                    <div style="font-size: 0.85rem; color: #64748b;">👤 {cham.get('solicitante', '-')} | 👨‍💻 {cham.get('tecnico', '-')}</div>
                    """, unsafe_allow_html=True)
                    st.markdown(bar_html, unsafe_allow_html=True)
                with col2:
                    st.write("")
                    st.write("")
                    st.button("👁️ Ver detalhes", key=f"btn_usr_{t_id}_{idx}", on_click=abrir_ticket, args=(t_id,), use_container_width=True)

# ============================================================
# TELA DASHBOARD DE INDICADORES
# ============================================================

if st.session_state.tela == "dashboard":
    if not st.session_state.autenticado_admin:
        st.error("⛔ Acesso Negado! Faça login como admin no menu lateral.")
        st.stop()

    st.title("📊 Painel de Indicadores de TI")

    # FILTROS
    anos_disponiveis = sorted([int(a) for a in df["ano_abertura"].dropna().unique()], reverse=True)
    opcoes_anos = ["Todos os Anos"] + anos_disponiveis
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🗓️ Filtro de Período")
    ano_sel = st.sidebar.selectbox("📅 Escolha o Ano", options=opcoes_anos, index=0)

    df_ano = df.copy() if ano_sel == "Todos os Anos" else df[df["ano_abertura"] == ano_sel]
    meses_nums = sorted([int(m) for m in df_ano["mes_num_abertura"].dropna().unique()])
    opcoes_meses = ["Todos os Meses"] + [MESES_DIC[m] for m in meses_nums if m in MESES_DIC]
    mes_sel = st.sidebar.selectbox("🗓️ Escolha o Mês", options=opcoes_meses, index=0)

    df_base = df_ano.copy()
    if mes_sel != "Todos os Meses":
        df_base = df_base[df_base["mes_nome_abertura"] == mes_sel]

    ocultar_roadmap = st.checkbox("🚫 Ocultar Projetos/Roadmap (> 5 dias) dos cálculos de SLA", value=True)
    
    df_sla = df_base[df_base["sla_valido"]].copy()
    if ocultar_roadmap:
        df_sla = df_sla[~df_sla["eh_roadmap"]]

    st.caption(f"⚡ Período Selecionado: **{mes_sel} / {ano_sel}**")
    st.divider()

    # 1. VISÃO GERAL DE VOLUME (COM GRÁFICO MANTIDO)
    st.subheader("📈 Volume Geral de Chamados")
    
    df_vol = df_base.groupby(["tecnico", "status"]).size().reset_index(name="Quantidade")
    if not df_vol.empty:
        fig_vol = px.bar(
            df_vol, 
            x="tecnico", 
            y="Quantidade", 
            color="status", 
            barmode="group",
            title="Total de Chamados por Técnico e Status",
            labels={"tecnico": "Técnico", "Quantidade": "Qtd Chamados", "status": "Status"},
            color_discrete_sequence=px.colors.qualitative.Set2
        )
        fig_vol.update_layout(margin=dict(l=20, r=20, t=40, b=20), height=350)
        st.plotly_chart(fig_vol, use_container_width=True)

    st.divider()

    # 2. SEÇÃO DE SLA (SEM GRÁFICO - SOMENTE MÉTRICAS E CARDS)
    st.subheader("⏱️ Indicadores de SLA e Tempos Médios (Sem Gráfico)")
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Chamados SLA Válido", len(df_sla))
    m2.metric("Média - Início Atendimento", formatar_tempo(df_sla["min_ate_tecnico"].mean()))
    m3.metric("Média - Tempo Execução", formatar_tempo(df_sla["min_resolucao"].mean()))
    m4.metric("Média - Tempo Total", formatar_tempo(df_sla["min_total"].mean()))

    st.write("")
    tec_cols = st.columns(len(TECNICOS_PERMITIDOS))
    
    for idx, tec_nome in enumerate(TECNICOS_PERMITIDOS):
        df_tec = df_sla[df_sla["tecnico"].str.casefold() == tec_nome.casefold()]
        total_tec = len(df_tec)
        media_inicio = df_tec["min_ate_tecnico"].mean()
        media_exec = df_tec["min_resolucao"].mean()
        media_total = df_tec["min_total"].mean()

        with tec_cols[idx]:
            with st.container(border=True):
                st.markdown(f"### 👤 {tec_nome}")
                st.write(f"**Total Chamados SLA:** {total_tec}")
                st.write(f"**Início Médio:** {formatar_tempo(media_inicio)}")
                st.write(f"**Execução Média:** {formatar_tempo(media_exec)}")
                st.write(f"**Tempo Total Médio:** {formatar_tempo(media_total)}")

    st.divider()

    # 3. TABELA DETALHADA DOS CHAMADOS
    st.subheader("📋 Detalhamento dos Chamados")
    col_filtro, _ = st.columns([2, 2])
    with col_filtro:
        tec_filtro = st.selectbox("Filtrar Tabela por Técnico", ["Todos"] + TECNICOS_PERMITIDOS)
    
    df_tabela = df_base.copy()
    if tec_filtro != "Todos":
        df_tabela = df_tabela[df_tabela["tecnico"].str.casefold() == tec_filtro.casefold()]

    df_exibicao = df_tabela[["id_chamado", "tecnico", "solicitante", "titulo", "status", "min_total"]].copy()
    df_exibicao["Tempo Total"] = df_exibicao["min_total"].apply(formatar_tempo)
    df_exibicao = df_exibicao.drop(columns=["min_total"]).rename(columns={
        "id_chamado": "Chamado",
        "tecnico": "Técnico",
        "solicitante": "Solicitante",
        "titulo": "Título",
        "status": "Status"
    })

    st.dataframe(df_exibicao, use_container_width=True, hide_index=True)

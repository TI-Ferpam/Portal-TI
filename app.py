import pandas as pd
import plotly.express as px
import streamlit as st
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

TECNICOS_PERMITIDOS = ["Matheus Juliati", "Jair de Alcantara"]
LIMITE_ROADMAP_MINUTOS = 5 * 24 * 60  # 5 dias em minutos = 7200 min

# ============================================================
# FUNÇÃO AUXILIAR DE FORMATAÇÃO DE TEMPO
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
        "prioridade", "departamento", "tecnico", "cidade",
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
            return df_empty

        # 1. Normalização dos nomes das colunas
        df_raw.columns = [str(col).strip().lower() for col in df_raw.columns]
        df_raw = df_raw.loc[:, df_raw.columns != ""]
        df_raw = df_raw.loc[:, ~df_raw.columns.duplicated()]

        # 2. Mapeamento de nomes de colunas
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

        # 3. Garantir existência das colunas
        for col in colunas_obrigatorias:
            if col not in df_raw.columns:
                df_raw[col] = ""

        # Limpeza genérica de strings
        for col in ["id_chamado", "solicitante", "titulo", "ocorrencia", "status", 
                    "prioridade", "departamento", "tecnico", "cidade", "atividade_realizada"]:
            df_raw[col] = df_raw[col].fillna("").astype(str).str.strip()
            df_raw[col] = df_raw[col].replace({"nan": "", "None": "", "null": "", "<NA>": ""})

        # Tratar nota numérica
        nota_limpa = df_raw["nota_atendimento"].astype(str).str.replace(",", ".", regex=False).str.strip()
        df_raw["nota_num"] = pd.to_numeric(nota_limpa, errors="coerce")

        # ============================================================
        # DATAS E CÁLCULOS DE SLA E ROADMAP
        # ============================================================
        df_raw["dt_abertura"] = pd.to_datetime(df_raw["data_hora_abertura"], errors="coerce").fillna(
            pd.to_datetime(df_raw["data_inicial"], errors="coerce")
        )
        df_raw["dt_tecnico"] = pd.to_datetime(df_raw["data_tecnico"], errors="coerce")
        df_raw["dt_conclusao_efetiva"] = pd.to_datetime(df_raw["data_conclusao"], errors="coerce").fillna(
            pd.to_datetime(df_raw["data_final"], errors="coerce")
        )

        # Minutos totais, até técnico e de resolução
        df_raw["min_total"] = (df_raw["dt_conclusao_efetiva"] - df_raw["dt_abertura"]).dt.total_seconds() / 60.0
        df_raw["min_ate_tecnico"] = (df_raw["dt_tecnico"] - df_raw["dt_abertura"]).dt.total_seconds() / 60.0
        df_raw["min_resolucao"] = (df_raw["dt_conclusao_efetiva"] - df_raw["dt_tecnico"]).dt.total_seconds() / 60.0

        # Regra do SLA Válido (necessita ter as 3 datas preenchidas sem tempos negativos)
        df_raw["sla_valido"] = (
            df_raw["dt_abertura"].notna() &
            df_raw["dt_tecnico"].notna() &
            df_raw["dt_conclusao_efetiva"].notna() &
            (df_raw["min_total"] >= 0) &
            (df_raw["min_ate_tecnico"] >= 0) &
            (df_raw["min_resolucao"] >= 0)
        )

        # REGRA DE ROADMAP: Chamado levar 5 dias ou mais pra conclusão (>= 7200 minutos)
        df_raw["eh_roadmap"] = (
            (df_raw["min_total"] >= LIMITE_ROADMAP_MINUTOS) | 
            (df_raw["min_resolucao"] >= LIMITE_ROADMAP_MINUTOS)
        )

        return df_raw

    except Exception as e:
        st.error(f"Erro ao carregar dados da planilha: {e}")
        df_err = pd.DataFrame(columns=colunas_obrigatorias)
        df_err["nota_num"] = pd.Series(dtype=float)
        df_err["sla_valido"] = pd.Series(dtype=bool)
        df_err["eh_roadmap"] = pd.Series(dtype=bool)
        return df_err

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
# ESTADOS DA SESSÃO E AUXILIARES
# ============================================================

for key, val in [("tela", "busca"), ("ticket_aberto", None), ("autenticado_admin", False), ("filtro_dash_tipo", None), ("filtro_dash_valor", None)]:
    if key not in st.session_state:
        st.session_state[key] = val

def abrir_ticket(ticket_id):
    st.session_state.ticket_aberto = str(ticket_id).strip()
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
        limpar_filtro_dash()
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

    st.subheader("⏱️ Tempos de Atendimento do Chamado")
    if chamado.get("sla_valido"):
        t1, t2, t3 = st.columns(3)
        with t1:
            st.metric("⏳ Tempo até Assumir", formatar_tempo(chamado.get("min_ate_tecnico")))
        with t2:
            st.metric("🔧 Tempo de Resolução", formatar_tempo(chamado.get("min_resolucao")))
        with t3:
            st.metric("🏁 Tempo Total", formatar_tempo(chamado.get("min_total")))
    else:
        st.info("ℹ️ Chamado em aberto ou sem todas as 3 datas registradas para cálculo de SLA.")

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
                    with st.container(border=True):
                        col1, col2 = st.columns([7, 3])
                        with col1:
                            st.markdown(f"""
                            <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 6px;">
                                <span style="font-size: 1.2rem; font-weight: 800;">🎫 #{t_id}</span>
                                {badge_html}
                            </div>
                            <div style="font-size: 1rem; font-weight: 700; margin-bottom: 4px;">{cham.get('titulo', 'Sem título')}</div>
                            <div style="font-size: 0.85rem; color: #64748b;">👤 {cham.get('solicitante', '-')} | 🏢 {cham.get('departamento', '-')}</div>
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
                with st.container(border=True):
                    col1, col2 = st.columns([7, 3])
                    with col1:
                        st.markdown(f"""
                        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 6px;">
                            <span style="font-size: 1.2rem; font-weight: 800;">🎫 #{t_id}</span>
                            {badge_html}
                        </div>
                        <div style="font-size: 1rem; font-weight: 700;">{cham.get('titulo', 'Sem título')}</div>
                        <div style="font-size: 0.85rem; color: #64748b;">👤 {cham.get('solicitante', '-')} | 🏢 {cham.get('departamento', '-')}</div>
                        """, unsafe_allow_html=True)
                        st.markdown(bar_html, unsafe_allow_html=True)
                    with col2:
                        st.write("")
                        st.write("")
                        st.button("👁️ Ver detalhes", key=f"btn_adm_{t_id}_{idx}", on_click=abrir_ticket, args=(t_id,), use_container_width=True)

# ============================================================
# TELA DASHBOARD DE INDICADORES
# ============================================================

if st.session_state.tela == "dashboard":
    if not st.session_state.autenticado_admin:
        st.error("⛔ Acesso Negado! Faça login como admin no menu lateral para visualizar o Dashboard.")
        st.stop()

    st.title("📊 Dashboard & Indicadores de TI")
    def aplicar_layout_plotly(fig):
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(t=30, b=20, l=20, r=20))
        return fig

    tab_op, tab_sla, tab_roadmap, tab_csat, tab_reviews = st.tabs([
        "📊 Operação & Volumetria", 
        "⏱️ SLAs & Médias de Tempo",
        "🗺️ Chamados em Roadmap (>= 5 dias)", 
        "⭐ Satisfação & Notas (CSAT)", 
        "💬 Feed de Reviews & Feedback"
    ])

    with tab_op:
        st.caption("⚡ **Interativo**: Clique nos botões dos cartões ou nas fatias/barras dos gráficos para filtrar!")
        total_chamados = len(df)
        df_dash = df.copy()
        df_dash["grupo_status"] = df_dash["status"].apply(classificar_status_grupo)
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
            if st.button("🔍 Andamento", key="btn_kpi_andamento", use_container_width=True, type=("primary" if st.session_state.filtro_dash_valor == "Em Andamento" else "secondary")):
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

        st.divider()
        g1, g2 = st.columns(2)
        with g1:
            st.subheader("🍩 Distribuição por Status")
            s_counts = df["status"].replace("", "Aberto / Sem Status").value_counts().reset_index()
            s_counts.columns = ["Status", "Quantidade"]
            fig_status = px.pie(s_counts, names="Status", values="Quantidade", hole=0.45, custom_data=["Status"])
            evt_status = st.plotly_chart(aplicar_layout_plotly(fig_status), use_container_width=True, on_select="rerun", selection_mode="points", key="chart_status")
            processar_clique_grafico(evt_status, "status")

        with g2:
            st.subheader("⚠️ Chamados por Prioridade")
            df_prio = df["prioridade"].replace("", "Não Informado").value_counts().reset_index()
            df_prio.columns = ["Prioridade", "Quantidade"]
            fig_prio = px.bar(df_prio, x="Prioridade", y="Quantidade", text="Quantidade", color="Prioridade", custom_data=["Prioridade"])
            fig_prio.update_layout(showlegend=False)
            evt_prio = st.plotly_chart(aplicar_layout_plotly(fig_prio), use_container_width=True, on_select="rerun", selection_mode="points", key="chart_prio")
            processar_clique_grafico(evt_prio, "prioridade")

        st.divider()
        g3, g4 = st.columns(2)
        with g3:
            st.subheader("🏢 Demandas por Departamento")
            df_dep = df["departamento"].replace("", "Outros").value_counts().head(10).reset_index()
            df_dep.columns = ["Departamento", "Quantidade"]
            fig_dep = px.bar(df_dep, y="Departamento", x="Quantidade", orientation="h", text="Quantidade", custom_data=["Departamento"])
            fig_dep.update_layout(yaxis=dict(autorange="reversed"))
            evt_dep = st.plotly_chart(aplicar_layout_plotly(fig_dep), use_container_width=True, on_select="rerun", selection_mode="points", key="chart_dep")
            processar_clique_grafico(evt_dep, "departamento")

        with g4:
            st.subheader("👨‍💻 Atendimentos por Técnico")
            df_tec = df["tecnico"].replace("", "Não Atribuído").value_counts().head(10).reset_index()
            df_tec.columns = ["Técnico", "Quantidade"]
            fig_tec = px.bar(df_tec, x="Técnico", y="Quantidade", text="Quantidade", custom_data=["Técnico"])
            evt_tec = st.plotly_chart(aplicar_layout_plotly(fig_tec), use_container_width=True, on_select="rerun", selection_mode="points", key="chart_tec")
            processar_clique_grafico(evt_tec, "tecnico")

        st.divider()
        df_filtrado_dash = df_dash.copy()
        tipo_filtro = st.session_state.filtro_dash_tipo
        valor_filtro = st.session_state.filtro_dash_valor

        if tipo_filtro and valor_filtro:
            if tipo_filtro == "status_grupo":
                df_filtrado_dash = df_filtrado_dash[df_filtrado_dash["grupo_status"] == valor_filtro]
            elif tipo_filtro in ["status", "prioridade", "departamento", "tecnico", "cidade"]:
                df_filtrado_dash = df_filtrado_dash[df_filtrado_dash[tipo_filtro].astype(str).str.strip().str.casefold() == str(valor_filtro).strip().casefold()]

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
            cols_exibicao = ["id_chamado", "titulo", "solicitante", "departamento", "tecnico", "status", "prioridade"]
            st.dataframe(df_filtrado_dash[cols_exibicao], use_container_width=True, hide_index=True)

    # ============================================================
    # TAB: SLAs & MÉDIAS DE TEMPO (EXCLUI OS ROADMAPS >= 5 DIAS)
    # ============================================================
    with tab_sla:
        st.subheader("⏱️ Indicadores Médios de SLA da Equipe (Operacional)")
        st.caption("Exclui projetos/roadmaps (>= 5 dias) para manter a precisão dos chamados operacionais do dia a dia.")

        # Excluir Roadmaps da média do SLA tradicional
        df_sla_filtrado = df[
            (df["sla_valido"] == True) & 
            (df["tecnico"].astype(str).str.strip().isin(TECNICOS_PERMITIDOS)) &
            (df["eh_roadmap"] == False)
        ].copy()

        if df_sla_filtrado.empty:
            st.warning("⚠️ Nenhum chamado operacional (com as 3 datas e < 5 dias) foi encontrado para a equipe.")
        else:
            med_assumir = df_sla_filtrado["min_ate_tecnico"].mean()
            med_resolucao = df_sla_filtrado["min_resolucao"].mean()
            med_total = df_sla_filtrado["min_total"].mean()

            col_sla1, col_sla2, col_sla3 = st.columns(3)
            with col_sla1:
                st.metric("⏳ Média para Assumir", formatar_tempo(med_assumir))
            with col_sla2:
                st.metric("🔧 Média de Execução do Técnico", formatar_tempo(med_resolucao))
            with col_sla3:
                st.metric("🏁 Média de Tempo Total de Resolução", formatar_tempo(med_total))

            st.divider()

            st.subheader("👨‍💻 Desempenho de SLA por Técnico (Operacional)")

            rows_tec = []
            for tec in TECNICOS_PERMITIDOS:
                sub = df_sla_filtrado[df_sla_filtrado["tecnico"].astype(str).str.strip().str.casefold() == tec.casefold()]
                
                if not sub.empty:
                    m_ass = sub["min_ate_tecnico"].mean()
                    m_res = sub["min_resolucao"].mean()
                    m_tot = sub["min_total"].mean()
                    qtd = len(sub)
                else:
                    m_ass, m_res, m_tot = None, None, None
                    qtd = 0

                rows_tec.append({
                    "Técnico": tec,
                    "Média até Assumir": formatar_tempo(m_ass),
                    "Média Execução Técnico": formatar_tempo(m_res),
                    "Média Tempo Total": formatar_tempo(m_tot),
                    "Chamados Operacionais": qtd
                })

            df_tec_table = pd.DataFrame(rows_tec)
            st.dataframe(df_tec_table, use_container_width=True, hide_index=True)

    # ============================================================
    # TAB: CHAMADOS EM ROADMAP (>= 5 DIAS)
    # ============================================================
    with tab_roadmap:
        st.subheader("🗺️ Chamados Longos & Projetos em Roadmap")
        st.caption("Lista de solicitações com tempo de resolução ou execução superior a 5 dias.")

        df_roadmaps = df[df["eh_roadmap"] == True].copy()

        if df_roadmaps.empty:
            st.info("🎉 Nenhum chamado longo ou projeto com mais de 5 dias encontrado.")
        else:
            r1, r2 = st.columns(2)
            with r1:
                st.metric("📦 Total de Chamados em Roadmap", len(df_roadmaps))
            with r2:
                tempo_medio_road = df_roadmaps["min_total"].mean() if not df_roadmaps["min_total"].isna().all() else 0
                st.metric("⏳ Tempo Médio desses Projetos", formatar_tempo(tempo_medio_road))

            st.divider()

            # Tabela de Roadmaps com formatação amigável
            df_roadmaps_display = df_roadmaps.copy()
            df_roadmaps_display["Tempo Total Estimado/Gasto"] = df_roadmaps_display["min_total"].apply(formatar_tempo)
            df_roadmaps_display["Tempo Execução Técnico"] = df_roadmaps_display["min_resolucao"].apply(formatar_tempo)

            cols_roadmap = ["id_chamado", "titulo", "solicitante", "tecnico", "departamento", "status", "Tempo Execução Técnico", "Tempo Total Estimado/Gasto"]
            st.dataframe(df_roadmaps_display[cols_roadmap], use_container_width=True, hide_index=True)

    # ============================================================
    # TAB: SATISFAÇÃO & CSAT
    # ============================================================
    with tab_csat:
        st.subheader("⭐ Indicadores de Satisfação (CSAT)")
        df_avaliados = df[df["nota_num"].notna() & (df["nota_num"] > 0)].copy()

        if df_avaliados.empty:
            st.info("Nenhuma avaliação de atendimento registrada até o momento.")
        else:
            csat_medio = df_avaliados["nota_num"].mean()
            total_avals = len(df_avaliados)
            pct_satisfeitos = (len(df_avaliados[df_avaliados["nota_num"] >= 4]) / total_avals) * 100

            c1, c2, c3 = st.columns(3)
            with c1: st.metric("⭐ Nota Média CSAT", f"{csat_medio:.2f} / 5.0")
            with c2: st.metric("📊 Total de Avaliações", total_avals)
            with c3: st.metric("👍 Taxa de Satisfação (Notas 4 e 5)", f"{pct_satisfeitos:.1f}%")

            st.divider()
            st.subheader("📊 Distribuição de Notas")
            df_dist = df_avaliados["nota_num"].value_counts().reset_index()
            df_dist.columns = ["Nota", "Quantidade"]
            fig_dist = px.bar(df_dist, x="Nota", y="Quantidade", text="Quantidade", color="Nota")
            st.plotly_chart(aplicar_layout_plotly(fig_dist), use_container_width=True)

    # ============================================================
    # TAB: FEED DE REVIEWS & FEEDBACK
    # ============================================================
    with tab_reviews:
        st.subheader("💬 Feedbacks e Comentários dos Solicitantes")
        df_coments = df[df["comentario_avaliacao"].notna() & (df["comentario_avaliacao"].astype(str).str.strip() != "") & (df["comentario_avaliacao"].astype(str).str.strip().str.casefold() != "nan")].copy()

        if df_coments.empty:
            st.info("Nenhum comentário registrado nas avaliações.")
        else:
            for _, r in df_coments.iterrows():
                with st.container(border=True):
                    st.markdown(f"**Chamado #{r['id_chamado']}** - Solicitante: *{r.get('solicitante', 'Anônimo')}*")
                    if pd.notna(r.get("nota_num")):
                        st.markdown(render_estrelas(r["nota_num"]))
                    st.write(f'"{r["comentario_avaliacao"]}"')
                    if pd.notna(r.get("data_avaliacao")):
                        st.caption(f"🗓️ Data: {r['data_avaliacao']}")

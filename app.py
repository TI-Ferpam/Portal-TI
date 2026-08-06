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
            df_empty["tem_3_datas"] = pd.Series(dtype=bool)
            df_empty["ano_abertura"] = pd.Series(dtype=float)
            df_empty["mes_num_abertura"] = pd.Series(dtype=float)
            df_empty["mes_nome_abertura"] = pd.Series(dtype=str)
            df_empty["dt_aval_parsed"] = pd.Series(dtype="datetime64[ns]")
            return df_empty

        df_raw.columns = [str(col).strip().lower() for col in df_raw.columns]
        df_raw = df_raw.loc[:, df_raw.columns != ""]
        df_raw = df_raw.loc[:, ~df_raw.columns.duplicated()]

        mapeamento_colunas = {
            "id": "id_chamado", "ticket": "id_chamado", "n_chamado": "id_chamado",
            "numero": "id_chamado", "num_chamado": "id_chamado", "descricao": "ocorrencia",
            "detalhes": "ocorrencia", "solucao": "atividade_realizada", "resolucao": "atividade_realizada",
            "nota": "nota_atendimento", "avaliacao": "nota_atendimento",
        }
        df_raw = df_raw.rename(columns=mapeamento_colunas)

        for col in colunas_obrigatorias:
            if col not in df_raw.columns:
                df_raw[col] = ""

        for col in ["id_chamado", "solicitante", "titulo", "ocorrencia", "status", 
                    "prioridade", "departamento", "tecnico", "cidade", "atividade_realizada"]:
            df_raw[col] = df_raw[col].fillna("").astype(str).str.strip()
            df_raw[col] = df_raw[col].replace({"nan": "", "None": "", "null": "", "<NA>": ""})

        padrao_nunes = r"mat[h]?eus\s+nunes"
        df_raw = df_raw[~df_raw["tecnico"].str.contains(padrao_nunes, case=False, regex=True, na=False)]

        nota_limpa = df_raw["nota_atendimento"].astype(str).str.replace(",", ".", regex=False).str.strip()
        df_raw["nota_num"] = pd.to_numeric(nota_limpa, errors="coerce")

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
                            <div style="font-size: 0.85rem; color: #94a3b8;">👤 {cham.get('solicitante', '-')} | 🏢 {cham.get('departamento', '-')}</div>
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
                        <div style="font-size: 0.85rem; color: #94a3b8;">👤 {cham.get('solicitante', '-')} | 🏢 {cham.get('departamento', '-')}</div>
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
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#f8fafc"),
            margin=dict(t=30, b=20, l=20, r=20)
        )
        return fig

    tab_op, tab_sla, tab_csat, tab_reviews = st.tabs([
        "📊 Operação & Volumetria", 
        "⏱️ SLAs & Médias de Tempo",
        "⭐ Satisfação & Notas (CSAT)", 
        "💬 Feed de Reviews & Feedback"
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

        # CÁLCULO DOS CARDS DA OPERAÇÃO
        df_dash = df_op_base.copy()
        df_dash["grupo_status"] = df_dash["status"].apply(classificar_status_grupo)

        total_chamados = len(df_dash)
        concluidos = len(df_dash[df_dash["grupo_status"] == "Concluídos"])
        em_andamento = len(df_dash[df_dash["grupo_status"] == "Em Andamento"])
        pendentes = len(df_dash[df_dash["grupo_status"] == "Abertos"])
        taxa_conclusao = (concluidos / total_chamados * 100) if total_chamados > 0 else 0

        # FILTRAGEM INTERATIVA (AO CLICAR NOS BOTÕES/GRÁFICOS)
        df_filtrado_exibir = df_dash.copy()
        tipo_f = st.session_state.filtro_dash_tipo
        val_f = st.session_state.filtro_dash_valor

        if tipo_f and val_f:
            if tipo_f == "status_grupo":
                df_filtrado_exibir = df_filtrado_exibir[df_filtrado_exibir["grupo_status"] == val_f]
            elif tipo_f == "status":
                df_filtrado_exibir = df_filtrado_exibir[df_filtrado_exibir["status"].str.casefold() == str(val_f).casefold()]
            elif tipo_f == "prioridade":
                df_filtrado_exibir = df_filtrado_exibir[df_filtrado_exibir["prioridade"].str.casefold() == str(val_f).casefold()]
            elif tipo_f == "departamento":
                df_filtrado_exibir = df_filtrado_exibir[df_filtrado_exibir["departamento"].str.casefold() == str(val_f).casefold()]
            elif tipo_f == "tecnico":
                df_filtrado_exibir = df_filtrado_exibir[df_filtrado_exibir["tecnico"].str.casefold() == str(val_f).casefold()]

        # CARDS / METRICAS
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

        # DETALHAMENTO DE SUB-STATUS "EM ANDAMENTO"
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

        # AVISO DE FILTRO ATIVO
        if tipo_f and val_f:
            st.info(f"🔎 **Filtro ativo no Dashboard:** {tipo_f.upper()} = **{val_f}** ({len(df_filtrado_exibir)} chamados)")
            if st.button("❌ Limpar Filtro Selecionado", type="secondary"):
                limpar_filtro_dash()
                st.rerun()

        # GRÁFICOS OPERACIONAIS (LINHA 1)
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

        # GRÁFICOS OPERACIONAIS (LINHA 2)
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

        # TABELA RESUMO DE CHAMADOS
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
    # TAB 2: SLAs & TEMPOS MÉDIOS (APENAS CARDS - SEM GRÁFICOS)
    # ============================================================
    with tab_sla:
        st.subheader("⏱️ SLA & Métricas de Tempo (Chamados Operacionais)")
        st.caption("Esta aba exibe as métricas limpas, ignorando chamados de longa duração catalogados como **Roadmap**.")
        
        # 1. Filtra chamados válidos de SLA
        df_sla_base = df[df["sla_valido"] == True].copy()
        
        # 2. SEPARAÇÃO RIGOROSA: Chamados Operacionais vs Chamados de Roadmap (> 6 dias)
        df_sla_operacional = df_sla_base[df_sla_base["eh_roadmap"] == False]
        df_roadmap = df_sla_base[df_sla_base["eh_roadmap"] == True]
        
        if df_sla_operacional.empty:
            st.warning("Não há chamados operacionais com as 3 datas completas para gerar estatísticas de SLA.")
        else:
            # APENAS CARDS / MÉTRICAS (SEM GRÁFICOS)
            s1, s2, s3 = st.columns(3)
            with s1:
                st.metric("⏱️ Méd. Tempo até Atendimento", formatar_tempo(df_sla_operacional["min_ate_tecnico"].mean()))
            with s2:
                st.metric("🔧 Méd. Tempo de Execução", formatar_tempo(df_sla_operacional["min_resolucao"].mean()))
            with s3:
                st.metric("🏁 Méd. Tempo Total de Conclusão", formatar_tempo(df_sla_operacional["min_total"].mean()))

        st.divider()

        # BLOCO INFORMATIVO DE ROADMAP (SEM GRÁFICOS)
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
                        st.markdown(f"**🎫 #{t_id} | {item.get('titulo', 'Sem Título')}**")
                        if n_str:
                            st.markdown(f"**Avaliação:** {n_str}")
                        if texto_aval and texto_aval.casefold() != "nan":
                            st.markdown(f"> *\"{texto_aval}\"*")
                        st.caption(f"👤 Solicitante: **{item.get('solicitante', '-')}** | 👨‍💻 Técnico: **{item.get('tecnico', 'Não informado')}**")
                    with col2:
                        st.write("")
                        st.caption(f"📅 {data_aval_str}")
                        st.button("👁️ Ver Ticket", key=f"btn_feed_{t_id}_{idx}", on_click=abrir_ticket, args=(t_id,), use_container_width=True)

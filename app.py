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

MESES_DIC = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
}

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
            df_empty["tem_3_datas"] = pd.Series(dtype=bool)
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
                    "prioridade", "departamento", "tecnico", "cidade", "atividade_realizada"]:
            df_raw[col] = df_raw[col].fillna("").astype(str).str.strip()
            df_raw[col] = df_raw[col].replace({"nan": "", "None": "", "null": "", "<NA>": ""})

        nota_limpa = df_raw["nota_atendimento"].astype(str).str.replace(",", ".", regex=False).str.strip()
        df_raw["nota_num"] = pd.to_numeric(nota_limpa, errors="coerce")

        # Tratamento flexível de Datas (dayfirst=True para formato brasileiro DD/MM/YYYY)
        df_raw["dt_abertura"] = pd.to_datetime(df_raw["data_hora_abertura"], dayfirst=True, errors="coerce").fillna(
            pd.to_datetime(df_raw["data_inicial"], dayfirst=True, errors="coerce")
        )
        df_raw["dt_tecnico"] = pd.to_datetime(df_raw["data_tecnico"], dayfirst=True, errors="coerce")
        df_raw["dt_conclusao_efetiva"] = pd.to_datetime(df_raw["data_conclusao"], dayfirst=True, errors="coerce").fillna(
            pd.to_datetime(df_raw["data_final"], dayfirst=True, errors="coerce")
        )
        
        # Data de avaliação formatada para ordenação
        df_raw["dt_aval_parsed"] = pd.to_datetime(df_raw["data_avaliacao"], dayfirst=True, errors="coerce").fillna(df_raw["dt_conclusao_efetiva"])

        # Campos auxiliares para filtro de Mês/Ano
        df_raw["ano_abertura"] = df_raw["dt_abertura"].dt.year
        df_raw["mes_num_abertura"] = df_raw["dt_abertura"].dt.month
        df_raw["mes_nome_abertura"] = df_raw["mes_num_abertura"].map(MESES_DIC)

        # Checagem flexível de datas
        df_raw["min_total"] = (df_raw["dt_conclusao_efetiva"] - df_raw["dt_abertura"]).dt.total_seconds() / 60.0
        df_raw["min_ate_tecnico"] = (df_raw["dt_tecnico"] - df_raw["dt_abertura"]).dt.total_seconds() / 60.0
        df_raw["min_resolucao"] = (df_raw["dt_conclusao_efetiva"] - df_raw["dt_tecnico"]).dt.total_seconds() / 60.0

        # Regra de SLA Válido: Ter ao menos abertura e conclusão coerentes (tempo total >= 0)
        df_raw["sla_valido"] = (
            df_raw["dt_abertura"].notna() &
            df_raw["dt_conclusao_efetiva"].notna() &
            (df_raw["min_total"] >= 0)
        )

        # MARCAÇÃO DE ROADMAP (>= 5 dias)
        df_raw["eh_roadmap"] = (df_raw["min_total"] >= LIMITE_ROADMAP_MINUTOS)

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

    tab_op, tab_sla, tab_csat, tab_reviews = st.tabs([
        "📊 Operação & Volumetria", 
        "⏱️ SLAs & Médias de Tempo",
        "⭐ Satisfação & Notas (CSAT)", 
        "💬 Feed de Reviews & Feedback"
    ])

    # ============================================================
    # FILTRO GLOBAL DE PERÍODO (COMPARTILHADO ENTRE ABAS)
    # ============================================================
    anos_disponiveis = sorted([int(a) for a in df["ano_abertura"].dropna().unique()], reverse=True)
    opcoes_anos = ["Todos os Anos"] + anos_disponiveis
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🗓️ Filtro de Período Global")
    ano_sel = st.sidebar.selectbox("📅 Escolha o Ano", options=opcoes_anos, index=0)

    if ano_sel == "Todos os Anos":
        df_ano = df.copy()
    else:
        df_ano = df[df["ano_abertura"] == ano_sel]

    meses_nums = sorted([int(m) for m in df_ano["mes_num_abertura"].dropna().unique()])
    opcoes_meses = ["Todos os Meses"] + [MESES_DIC[m] for m in meses_nums if m in MESES_DIC]

    mes_sel = st.sidebar.selectbox("🗓️ Escolha o Mês", options=opcoes_meses, index=0)

    df_op_base = df_ano.copy()
    if mes_sel != "Todos os Meses":
        df_op_base = df_op_base[df_op_base["mes_nome_abertura"] == mes_sel]

    # ============================================================
    # TAB: OPERAÇÃO & VOLUMETRIA
    # ============================================================
    with tab_op:
        st.caption(f"⚡ Exibindo dados do período: **{mes_sel} / {ano_sel}**")

        # METRICAS E CARDS
        total_chamados = len(df_op_base)
        df_dash = df_op_base.copy()
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

        # GRÁFICOS INTERATIVOS
        g1, g2 = st.columns(2)
        with g1:
            st.subheader("🍩 Distribuição por Status")
            s_counts = df_op_base["status"].replace("", "Aberto / Sem Status").value_counts().reset_index()
            s_counts.columns = ["Status", "Quantidade"]
            fig_status = px.pie(s_counts, names="Status", values="Quantidade", hole=0.45, custom_data=["Status"])
            evt_status = st.plotly_chart(aplicar_layout_plotly(fig_status), use_container_width=True, on_select="rerun", selection_mode="points", key="chart_status")
            processar_clique_grafico(evt_status, "status")

        with g2:
            st.subheader("⚠️ Chamados por Prioridade")
            df_prio = df_op_base["prioridade"].replace("", "Não Informado").value_counts().reset_index()
            df_prio.columns = ["Prioridade", "Quantidade"]
            fig_prio = px.bar(df_prio, x="Prioridade", y="Quantidade", text="Quantidade", color="Prioridade", custom_data=["Prioridade"])
            fig_prio.update_layout(showlegend=False)
            evt_prio = st.plotly_chart(aplicar_layout_plotly(fig_prio), use_container_width=True, on_select="rerun", selection_mode="points", key="chart_prio")
            processar_clique_grafico(evt_prio, "prioridade")

        st.divider()
        g3, g4 = st.columns(2)
        with g3:
            st.subheader("🏢 Demandas por Departamento")
            df_dep = df_op_base["departamento"].replace("", "Outros").value_counts().head(10).reset_index()
            df_dep.columns = ["Departamento", "Quantidade"]
            fig_dep = px.bar(df_dep, y="Departamento", x="Quantidade", orientation="h", text="Quantidade", custom_data=["Departamento"])
            fig_dep.update_layout(yaxis=dict(autorange="reversed"))
            evt_dep = st.plotly_chart(aplicar_layout_plotly(fig_dep), use_container_width=True, on_select="rerun", selection_mode="points", key="chart_dep")
            processar_clique_grafico(evt_dep, "departamento")

        with g4:
            st.subheader("👨‍💻 Atendimentos por Técnico")
            df_tec = df_op_base["tecnico"].replace("", "Não Atribuído").value_counts().head(10).reset_index()
            df_tec.columns = ["Técnico", "Quantidade"]
            fig_tec = px.bar(df_tec, x="Técnico", y="Quantidade", text="Quantidade", custom_data=["Técnico"])
            evt_tec = st.plotly_chart(aplicar_layout_plotly(fig_tec), use_container_width=True, on_select="rerun", selection_mode="points", key="chart_tec")
            processar_clique_grafico(evt_tec, "tecnico")

        st.divider()

        # TABELA DE CHAMADOS
        df_filtrado_dash = df_dash.copy()
        tipo_filtro = st.session_state.filtro_dash_tipo
        valor_filtro = st.session_state.filtro_dash_valor

        rotulo_periodo = f"{mes_sel} / {ano_sel}" if ano_sel != "Todos os Anos" else f"{mes_sel} (Todos os Anos)"

        if tipo_filtro and valor_filtro:
            if tipo_filtro == "status_grupo":
                df_filtrado_dash = df_filtrado_dash[df_filtrado_dash["grupo_status"] == valor_filtro]
            elif tipo_filtro in ["status", "prioridade", "departamento", "tecnico"]:
                df_filtrado_dash = df_filtrado_dash[df_filtrado_dash[tipo_filtro] == valor_filtro]

            st.info(f"🔍 **Filtro ativo:** {tipo_filtro.upper()} = **{valor_filtro}** ({len(df_filtrado_dash)} chamados em {rotulo_periodo})")
            st.button("❌ Limpar Filtro de Gráfico/Card", on_click=limpar_filtro_dash, type="secondary")
        else:
            st.caption(f"Exibindo todos os {len(df_filtrado_dash)} chamados do período selecionado ({rotulo_periodo}).")

        colunas_exibir = [
            "id_chamado", "status", "solicitante", "titulo", 
            "departamento", "tecnico", "prioridade", "data_hora_abertura"
        ]
        colunas_existentes = [c for c in colunas_exibir if c in df_filtrado_dash.columns]
        
        st.dataframe(
            df_filtrado_dash[colunas_existentes].sort_values(by="id_chamado", ascending=False),
            use_container_width=True,
            hide_index=True
        )

    # ============================================================
    # TAB: SLAs & MÉDIAS DE TEMPO (CORRIGIDA E ROBUSTA)
    # ============================================================
    with tab_sla:
        st.caption("⏱️ Indicadores de tempo calculados com base nos chamados finalizados do período.")
        
        # Filtra chamados válidos (tem data de abertura e conclusão válidas)
        df_sla = df_op_base[df_op_base["sla_valido"] == True].copy()
        
        # Opção para o usuário ignorar ou não chamados longos (Roadmap > 5 dias)
        ocultar_roadmap = st.checkbox("🚫 Ocultar Projetos/Roadmap (> 5 dias) dos cálculos de média", value=False)
        
        if ocultar_roadmap:
            df_sla_trabalhado = df_sla[df_sla["eh_roadmap"] == False]
        else:
            df_sla_trabalhado = df_sla.copy()

        if df_sla_trabalhado.empty:
            st.warning("⚠️ Nenhum chamado concluído foi encontrado para os critérios de tempo no período selecionado.")
        else:
            t1, t2, t3, t4 = st.columns(4)
            with t1:
                st.metric("Chamados com SLA Válido", len(df_sla_trabalhado))
            with t2:
                # Média até o técnico assumir (ignora registros sem dt_tecnico)
                df_ate_tec = df_sla_trabalhado[df_sla_trabalhado["min_ate_tecnico"].notna() & (df_sla_trabalhado["min_ate_tecnico"] >= 0)]
                media_atencao = df_ate_tec["min_ate_tecnico"].mean() if not df_ate_tec.empty else None
                st.metric("⏳ Média - Início do Atendimento", formatar_tempo(media_atencao))
            with t3:
                # Média do tempo de resolução técnica
                df_res = df_sla_trabalhado[df_sla_trabalhado["min_resolucao"].notna() & (df_sla_trabalhado["min_resolucao"] >= 0)]
                media_resolucao = df_res["min_resolucao"].mean() if not df_res.empty else None
                st.metric("🔧 Média - Tempo de Execução", formatar_tempo(media_resolucao))
            with t4:
                # Média do tempo total
                media_total = df_sla_trabalhado["min_total"].mean()
                st.metric("🏁 Média - Tempo Total", formatar_tempo(media_total))

            st.divider()

            col_sla1, col_sla2 = st.columns(2)
            with col_sla1:
                st.subheader("👨‍💻 Tempo Médio Total por Técnico")
                df_tec_sla = df_sla_trabalhado[df_sla_trabalhado["tecnico"] != ""].groupby("tecnico")["min_total"].mean().reset_index()
                if not df_tec_sla.empty:
                    df_tec_sla["tempo_formatado"] = df_tec_sla["min_total"].apply(formatar_tempo)
                    fig_tec_sla = px.bar(
                        df_tec_sla, x="tecnico", y="min_total",
                        text="tempo_formatado", color="min_total",
                        labels={"min_total": "Minutos", "tecnico": "Técnico"}
                    )
                    fig_tec_sla.update_layout(showlegend=False)
                    st.plotly_chart(aplicar_layout_plotly(fig_tec_sla), use_container_width=True)
                else:
                    st.info("Sem dados de técnicos para os chamados deste período.")

            with col_sla2:
                st.subheader("🏢 Tempo Médio por Departamento")
                df_dep_sla = df_sla_trabalhado[df_sla_trabalhado["departamento"] != ""].groupby("departamento")["min_total"].mean().reset_index()
                if not df_dep_sla.empty:
                    df_dep_sla["tempo_formatado"] = df_dep_sla["min_total"].apply(formatar_tempo)
                    fig_dep_sla = px.bar(
                        df_dep_sla, x="min_total", y="departamento",
                        orientation="h", text="tempo_formatado",
                        labels={"min_total": "Minutos", "departamento": "Departamento"}
                    )
                    fig_dep_sla.update_layout(yaxis=dict(autorange="reversed"))
                    st.plotly_chart(aplicar_layout_plotly(fig_dep_sla), use_container_width=True)
                else:
                    st.info("Sem dados de departamentos para os chamados deste período.")

    # ============================================================
    # TAB: SATISFAÇÃO & NOTAS (CSAT)
    # ============================================================
    with tab_csat:
        st.caption("⭐ Indicadores de satisfação (CSAT) com base nas avaliações enviadas pelos usuários.")
        
        df_csat = df_op_base[df_op_base["nota_num"].notna() & (df_op_base["nota_num"] > 0)].copy()
        
        if df_csat.empty:
            st.info("Ainda não há avaliações registradas para o período selecionado.")
        else:
            media_geral = df_csat["nota_num"].mean()
            total_avaliados = len(df_csat)
            pct_satisfeitos = (len(df_csat[df_csat["nota_num"] >= 4]) / total_avaliados * 100) if total_avaliados > 0 else 0

            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("⭐ Nota Média Geral", f"{media_geral:.2f} / 5.0")
            with c2:
                st.metric("📋 Total de Avaliações", total_avaliados)
            with c3:
                st.metric("😊 Taxa de Satisfação (Notas 4 e 5)", f"{pct_satisfeitos:.1f}%")

            st.divider()

            col_c1, col_c2 = st.columns(2)
            with col_c1:
                st.subheader("📊 Distribuição das Notas")
                dist_notas = df_csat["nota_num"].value_counts().sort_index(ascending=False).reset_index()
                dist_notas.columns = ["Nota", "Quantidade"]
                dist_notas["Nota_Str"] = dist_notas["Nota"].apply(lambda x: "⭐" * int(x))
                
                fig_dist = px.bar(
                    dist_notas, x="Quantidade", y="Nota_Str",
                    orientation="h", text="Quantidade",
                    color="Nota", color_continuous_scale="Blues"
                )
                fig_dist.update_layout(showlegend=False, yaxis_title="Avaliação")
                st.plotly_chart(aplicar_layout_plotly(fig_dist), use_container_width=True)

            with col_c2:
                st.subheader("👨‍💻 Nota Média por Técnico")
                df_tec_csat = df_csat[df_csat["tecnico"] != ""].groupby("tecnico")["nota_num"].agg(["mean", "count"]).reset_index()
                if not df_tec_csat.empty:
                    df_tec_csat.columns = ["Técnico", "Nota Média", "Avaliações"]
                    df_tec_csat["Nota Média"] = df_tec_csat["Nota Média"].round(2)
                    
                    fig_tec_csat = px.bar(
                        df_tec_csat, x="Técnico", y="Nota Média",
                        text="Nota Média", color="Nota Média",
                        range_y=[0, 5], color_continuous_scale="Blues"
                    )
                    st.plotly_chart(aplicar_layout_plotly(fig_tec_csat), use_container_width=True)
                else:
                    st.info("Sem dados de técnicos avaliados.")

    # ============================================================
    # TAB: FEED DE REVIEWS & FEEDBACK
    # ============================================================
    with tab_reviews:
        st.caption("💬 Listagem dos comentários recentes deixados pelos solicitantes.")
        
        df_feed = df_op_base[
            df_op_base["comentario_avaliacao"].notna() & 
            (df_op_base["comentario_avaliacao"].str.strip() != "") &
            (df_op_base["comentario_avaliacao"].str.casefold() != "nan")
        ].copy()

        if df_feed.empty:
            st.info("Nenhum comentário por escrito foi registrado no período selecionado.")
        else:
            df_feed = df_feed.sort_values(by="dt_aval_parsed", ascending=False)
            
            for _, row in df_feed.iterrows():
                with st.container(border=True):
                    f_col1, f_col2 = st.columns([8, 2])
                    with f_col1:
                        estrelas_txt = render_estrelas(row.get("nota_num", 5)) or "⭐⭐⭐⭐⭐"
                        st.markdown(f"**🎫 Chamado #{row['id_chamado']} - {row.get('titulo', 'Sem título')}**")
                        st.markdown(f"*{estrelas_txt}* — **{row.get('solicitante', 'Anônimo')}** ({row.get('departamento', '-')})")
                        st.write(f'💬 *"{row["comentario_avaliacao"]}"*')
                    with f_col2:
                        st.caption("👨‍💻 **Técnico:**")
                        st.write(row.get("tecnico", "-"))
                        dt_str = row["dt_aval_parsed"].strftime("%d/%m/%Y") if pd.notna(row["dt_aval_parsed"]) else "-"
                        st.caption(f"📅 {dt_str}")

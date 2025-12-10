"""
Aplicação Streamlit para consumir a API da Câmara dos Deputados
"""

import streamlit as st
import pandas as pd
import importlib
import sys

# Forçar recarga do módulo api_client
if 'api_client' in sys.modules:
    importlib.reload(sys.modules['api_client'])

from api_client import CamaraAPIClient
from datetime import datetime, timedelta

# Configuração da página
st.set_page_config(
    page_title="API Câmara dos Deputados",
    page_icon="🏛️",
    layout="wide"
)

# Inicializar cliente da API
@st.cache_resource
def get_api_client():
    return CamaraAPIClient()

# Limpar cache se necessário (força recarga do módulo)
if st.sidebar.button("🔄 Recarregar API"):
    st.cache_resource.clear()
    st.rerun()

api = get_api_client()

# Título principal
st.title("🏛️ API Dados Abertos - Câmara dos Deputados")
st.markdown("---")

# Sidebar com seleção de funcionalidade
st.sidebar.title("Menu")
opcao = st.sidebar.selectbox(
    "Escolha uma opção:",
    [
        "Deputados",
        "Proposições",
        "Partidos",
        "Blocos",
        "Eventos",
        "Votações",
        "Órgãos"
    ]
)

# ========== DEPUTADOS ==========
if opcao == "Deputados":
    st.header("👤 Deputados")
    
    # Inicializar o estado da sessão para armazenar o deputado selecionado e lista de deputados
    if 'deputado_selecionado' not in st.session_state:
        st.session_state.deputado_selecionado = None
    if 'lista_deputados' not in st.session_state:
        st.session_state.lista_deputados = None
    
    tab1, tab2, tab3, tab4 = st.tabs(["Listar Deputados", "Detalhes do Deputado", "Despesas", "Discursos"])
    
    with tab1:
        st.subheader("Buscar Deputados")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            nome_filtro = st.text_input("Nome do Deputado")
        with col2:
            uf_filtro = st.text_input("UF (ex: SC, SP, RJ)")
        with col3:
            partido_filtro = st.text_input("Partido (ex: PT, PSDB, PL)")
        
        if st.button("Buscar Deputados"):
            with st.spinner("Buscando deputados..."):
                resultado = api.listar_deputados(
                    nome=nome_filtro if nome_filtro else None,
                    sigla_uf=uf_filtro.upper() if uf_filtro else None,
                    sigla_partido=partido_filtro.upper() if partido_filtro else None,
                    itens=50
                )
                
                if "dados" in resultado and resultado["dados"]:
                    st.session_state.lista_deputados = pd.DataFrame(resultado["dados"])
                    st.success(f"Encontrados {len(st.session_state.lista_deputados)} deputados")
                elif "error" in resultado:
                    st.error(f"Erro: {resultado['error']}")
                    st.session_state.lista_deputados = None
                else:
                    st.warning("Nenhum deputado encontrado")
                    st.session_state.lista_deputados = None
        
        # Exibir a tabela com seleção se houver dados
        if st.session_state.lista_deputados is not None:
            st.info("💡 Clique em uma linha da tabela para ver os detalhes do deputado nas outras abas")
            
            # Usar st.dataframe com seleção de linha
            event = st.dataframe(
                st.session_state.lista_deputados,
                width='stretch',
                on_select="rerun",
                selection_mode="single-row"
            )
            
            # Verificar se uma linha foi selecionada
            if event.selection and len(event.selection.rows) > 0:
                row_index = event.selection.rows[0]
                st.session_state.deputado_selecionado = st.session_state.lista_deputados.iloc[row_index]['id']
                st.success(f"✅ Deputado selecionado! ID: {st.session_state.deputado_selecionado}")
    
    with tab2:
        st.subheader("Detalhes do Deputado")
        
        # Carregar automaticamente se houver deputado selecionado
        if st.session_state.deputado_selecionado:
            id_deputado = st.session_state.deputado_selecionado
            st.info(f"📋 Deputado ID: {id_deputado} (selecionado da lista)")
            
            with st.spinner("Buscando detalhes..."):
                resultado = api.detalhes_deputado(id_deputado)
                
                if "dados" in resultado:
                    dados = resultado["dados"]
                    
                    # Verificar se dados é uma lista e pegar o primeiro elemento
                    if isinstance(dados, list):
                        if len(dados) > 0:
                            dados = dados[0]
                        else:
                            st.warning("Nenhum dado encontrado")
                            dados = None
                    
                    if dados:
                        col1, col2 = st.columns([1, 2])
                        with col1:
                            if "urlFoto" in dados:
                                st.image(dados["urlFoto"], width=200)
                        
                        with col2:
                            st.markdown(f"### {dados.get('nomeCivil', 'N/A')}")
                            st.write(f"**Nome Parlamentar:** {dados.get('ultimoStatus', {}).get('nome', 'N/A')}")
                            st.write(f"**Partido:** {dados.get('ultimoStatus', {}).get('siglaPartido', 'N/A')}")
                            st.write(f"**UF:** {dados.get('ultimoStatus', {}).get('siglaUf', 'N/A')}")
                            st.write(f"**Data de Nascimento:** {dados.get('dataNascimento', 'N/A')}")
                            st.write(f"**Escolaridade:** {dados.get('escolaridade', 'N/A')}")
                        
                        st.subheader("📄 Dados Completos")
                        st.json(dados)
                elif "error" in resultado:
                    st.error(f"Erro: {resultado['error']}")
                else:
                    st.warning("Deputado não encontrado")
            
            # Botão para limpar seleção
            if st.button("🔄 Limpar Seleção", key="limpar_detalhes"):
                st.session_state.deputado_selecionado = None
                st.session_state.lista_deputados = None
                st.rerun()
        else:
            st.info("👈 Selecione um deputado na aba 'Listar Deputados' para ver os detalhes aqui.")
    
    with tab3:
        st.subheader("Despesas do Deputado")
        
        if st.session_state.deputado_selecionado:
            id_dep_despesa = st.session_state.deputado_selecionado
            st.info(f"📋 Deputado ID: {id_dep_despesa} (selecionado da lista)")
            
            col1, col2 = st.columns(2)
            
            with col1:
                ano_despesa = st.number_input("Ano", min_value=2000, max_value=datetime.now().year, 
                                             value=datetime.now().year, key="ano_desp")
            with col2:
                mes_despesa = st.selectbox("Mês (opcional)", ["Todos"] + list(range(1, 13)))
            
            if st.button("Buscar Despesas"):
                with st.spinner("Buscando despesas..."):
                    mes = mes_despesa if mes_despesa != "Todos" else None
                    resultado = api.despesas_deputado(id_dep_despesa, ano=ano_despesa, mes=mes, itens=100)
                    
                    if "dados" in resultado and resultado["dados"]:
                        df = pd.DataFrame(resultado["dados"])
                        
                        # Estatísticas
                        if "valorDocumento" in df.columns:
                            total = df["valorDocumento"].sum()
                            st.metric("Valor Total", f"R$ {total:,.2f}")
                        
                        st.dataframe(df, width='stretch')
                        
                        # Gráfico por tipo de despesa
                        if "tipoDespesa" in df.columns and "valorDocumento" in df.columns:
                            despesas_por_tipo = df.groupby("tipoDespesa")["valorDocumento"].sum().sort_values(ascending=False)
                            st.bar_chart(despesas_por_tipo)
                    elif "error" in resultado:
                        st.error(f"Erro: {resultado['error']}")
                    else:
                        st.warning("Nenhuma despesa encontrada")
            
            # Botão para limpar seleção
            if st.button("🔄 Limpar Seleção", key="limpar_desp"):
                st.session_state.deputado_selecionado = None
                st.session_state.lista_deputados = None
                st.rerun()
        else:
            st.info("👈 Selecione um deputado na aba 'Listar Deputados' para ver as despesas aqui.")
    
    with tab4:
        st.subheader("Discursos do Deputado")
        
        if st.session_state.deputado_selecionado:
            id_dep_discurso = st.session_state.deputado_selecionado
            st.info(f"📋 Deputado ID: {id_dep_discurso} (selecionado da lista)")
            
            col1, col2 = st.columns(2)
            
            with col1:
                data_inicio_disc = st.date_input("Data Início", value=datetime.now() - timedelta(days=90), key="disc_inicio")
            with col2:
                data_fim_disc = st.date_input("Data Fim", value=datetime.now(), key="disc_fim")
            
            if st.button("Buscar Discursos"):
                with st.spinner("Buscando discursos..."):
                    resultado = api.discursos_deputado(
                        id_dep_discurso,
                        data_inicio=data_inicio_disc.strftime("%Y-%m-%d"),
                        data_fim=data_fim_disc.strftime("%Y-%m-%d"),
                        itens=100
                    )
                    
                    if "dados" in resultado and resultado["dados"]:
                        discursos = resultado["dados"]
                        st.success(f"Encontrados {len(discursos)} discursos")
                        
                        # Exibir cada discurso
                        for i, discurso in enumerate(discursos, 1):
                            with st.expander(f"🎤 Discurso {i} - {discurso.get('dataHoraInicio', 'Data não disponível')}"):
                                st.write(f"**Fase do Evento:** {discurso.get('faseEvento', {}).get('titulo', 'N/A')}")
                                st.write(f"**Tipo de Discurso:** {discurso.get('tipoDiscurso', 'N/A')}")
                                
                                # Transcrição
                                transcricao = discurso.get('transcricao', 'Transcrição não disponível')
                                if transcricao and len(transcricao) > 0:
                                    st.markdown("**Transcrição:**")
                                    st.text_area("", transcricao, height=200, key=f"disc_{i}", disabled=True)
                                
                                # URL do inteiro teor se disponível
                                if 'urlTexto' in discurso:
                                    st.markdown(f"[📄 Ver Inteiro Teor]({discurso['urlTexto']})")
                                
                                # Dados completos
                                with st.expander("Ver dados completos"):
                                    st.json(discurso)
                    elif "error" in resultado:
                        st.error(f"Erro: {resultado['error']}")
                    else:
                        st.warning("Nenhum discurso encontrado no período selecionado")
            
            # Botão para limpar seleção
            if st.button("🔄 Limpar Seleção", key="limpar_disc"):
                st.session_state.deputado_selecionado = None
                st.session_state.lista_deputados = None
                st.rerun()
        else:
            st.info("👈 Selecione um deputado na aba 'Listar Deputados' para ver os discursos aqui.")

# ========== PROPOSIÇÕES ==========
elif opcao == "Proposições":
    st.header("📜 Proposições")
    
    # Inicializar o estado da sessão para proposições
    if 'proposicao_selecionada' not in st.session_state:
        st.session_state.proposicao_selecionada = None
    if 'lista_proposicoes' not in st.session_state:
        st.session_state.lista_proposicoes = None
    
    tab1, tab2 = st.tabs(["Listar Proposições", "Detalhes da Proposição"])
    
    with tab1:
        st.subheader("Buscar Proposições")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            sigla_tipo = st.selectbox("Tipo", ["", "PL", "PEC", "PLP", "PDC", "MPV", "PRC"])
        with col2:
            numero_prop = st.number_input("Número", min_value=0, step=1)
        with col3:
            ano_prop = st.number_input("Ano", min_value=1900, max_value=datetime.now().year, 
                                      value=datetime.now().year)
        
        col4, col5 = st.columns(2)
        with col4:
            data_inicio = st.date_input("Data Início", value=datetime.now() - timedelta(days=30))
        with col5:
            data_fim = st.date_input("Data Fim", value=datetime.now())
        
        if st.button("Buscar Proposições"):
            with st.spinner("Buscando proposições..."):
                resultado = api.listar_proposicoes(
                    sigla_tipo=sigla_tipo if sigla_tipo else None,
                    numero=numero_prop if numero_prop > 0 else None,
                    ano=ano_prop,
                    data_inicio=data_inicio.strftime("%Y-%m-%d"),
                    data_fim=data_fim.strftime("%Y-%m-%d"),
                    itens=50
                )
                
                if "dados" in resultado and resultado["dados"]:
                    st.session_state.lista_proposicoes = pd.DataFrame(resultado["dados"])
                    st.success(f"Encontradas {len(st.session_state.lista_proposicoes)} proposições")
                elif "error" in resultado:
                    st.error(f"Erro: {resultado['error']}")
                    st.session_state.lista_proposicoes = None
                else:
                    st.warning("Nenhuma proposição encontrada")
                    st.session_state.lista_proposicoes = None
        
        # Exibir a tabela com seleção se houver dados
        if st.session_state.lista_proposicoes is not None:
            st.info("💡 Clique em uma linha da tabela para ver os detalhes da proposição na próxima aba")
            
            # Usar st.dataframe com seleção de linha
            event = st.dataframe(
                st.session_state.lista_proposicoes,
                width='stretch',
                on_select="rerun",
                selection_mode="single-row"
            )
            
            # Verificar se uma linha foi selecionada
            if event.selection and len(event.selection.rows) > 0:
                row_index = event.selection.rows[0]
                st.session_state.proposicao_selecionada = st.session_state.lista_proposicoes.iloc[row_index]['id']
                st.success(f"✅ Proposição selecionada! ID: {st.session_state.proposicao_selecionada}")
    
    with tab2:
        st.subheader("Detalhes da Proposição")
        
        if st.session_state.proposicao_selecionada:
            id_proposicao = st.session_state.proposicao_selecionada
            st.info(f"📋 Proposição ID: {id_proposicao} (selecionada da lista)")
            
            # Criar abas para diferentes tipos de informação
            sub_tab1, sub_tab2, sub_tab3, sub_tab4 = st.tabs(["Informações Gerais", "Autores", "Tramitações", "Temas"])
            
            with sub_tab1:
                with st.spinner("Buscando detalhes..."):
                    resultado = api.detalhes_proposicao(id_proposicao)
                    
                    if "dados" in resultado:
                        dados = resultado["dados"]
                        
                        # Verificar se dados é uma lista
                        if isinstance(dados, list):
                            if len(dados) > 0:
                                dados = dados[0]
                            else:
                                st.warning("Nenhum dado encontrado")
                                dados = None
                        
                        if dados:
                            # Exibir informações principais
                            col1, col2 = st.columns(2)
                            
                            with col1:
                                st.markdown(f"### {dados.get('siglaTipo', '')} {dados.get('numero', '')}/{dados.get('ano', '')}")
                                st.write(f"**Ementa:** {dados.get('ementa', 'N/A')}")
                                st.write(f"**Situação:** {dados.get('statusProposicao', {}).get('descricaoSituacao', 'N/A')}")
                                st.write(f"**Data Apresentação:** {dados.get('dataApresentacao', 'N/A')}")
                            
                            with col2:
                                st.write(f"**Tema:** {dados.get('descricaoTipo', 'N/A')}")
                                st.write(f"**Regime Tramitação:** {dados.get('statusProposicao', {}).get('regime', 'N/A')}")
                                if 'urlInteiroTeor' in dados:
                                    st.markdown(f"[📄 Ver Inteiro Teor]({dados['urlInteiroTeor']})")
                            
                            st.subheader("📄 Dados Completos")
                            st.json(dados)
                    elif "error" in resultado:
                        st.error(f"Erro: {resultado['error']}")
                    else:
                        st.warning("Proposição não encontrada")
            
            with sub_tab2:
                with st.spinner("Buscando autores..."):
                    resultado = api.autores_proposicao(id_proposicao)
                    
                    if "dados" in resultado and resultado["dados"]:
                        df = pd.DataFrame(resultado["dados"])
                        st.success(f"Encontrados {len(df)} autores")
                        st.dataframe(df, width='stretch')
                    elif "error" in resultado:
                        st.error(f"Erro: {resultado['error']}")
                    else:
                        st.warning("Nenhum autor encontrado")
            
            with sub_tab3:
                with st.spinner("Buscando tramitações..."):
                    resultado = api.tramitacoes_proposicao(id_proposicao)
                    
                    if "dados" in resultado and resultado["dados"]:
                        df = pd.DataFrame(resultado["dados"])
                        st.success(f"Encontradas {len(df)} tramitações")
                        st.dataframe(df, width='stretch')
                    elif "error" in resultado:
                        st.error(f"Erro: {resultado['error']}")
                    else:
                        st.warning("Nenhuma tramitação encontrada")
            
            with sub_tab4:
                with st.spinner("Buscando temas..."):
                    resultado = api.temas_proposicao(id_proposicao)
                    
                    if "dados" in resultado and resultado["dados"]:
                        temas = resultado["dados"]
                        st.success(f"Encontrados {len(temas)} temas")
                        
                        # Exibir temas de forma organizada
                        for tema in temas:
                            with st.container():
                                st.markdown(f"### 🏷️ {tema.get('tema', 'N/A')}")
                                
                                # Relevância
                                relevancia = tema.get('relevancia', 0)
                                st.progress(relevancia / 100, text=f"Relevância: {relevancia}%")
                                
                                # Detalhes adicionais se houver
                                if 'codTema' in tema:
                                    st.write(f"**Código:** {tema['codTema']}")
                                
                                st.divider()
                        
                        # Opção de ver dados completos
                        with st.expander("Ver dados completos em JSON"):
                            st.json(temas)
                    elif "error" in resultado:
                        st.error(f"Erro: {resultado['error']}")
                    else:
                        st.info("Nenhum tema associado a esta proposição")
            
            # Botão para limpar seleção
            if st.button("🔄 Limpar Seleção", key="limpar_proposicao"):
                st.session_state.proposicao_selecionada = None
                st.session_state.lista_proposicoes = None
                st.rerun()
        else:
            st.info("👈 Selecione uma proposição na aba 'Listar Proposições' para ver os detalhes aqui.")

# ========== PARTIDOS ==========
elif opcao == "Partidos":
    st.header("🎯 Partidos")
    
    # Inicializar estado da sessão
    if 'partido_selecionado' not in st.session_state:
        st.session_state.partido_selecionado = None
    if 'lista_partidos' not in st.session_state:
        st.session_state.lista_partidos = None
    
    tab1, tab2 = st.tabs(["Listar Partidos", "Detalhes do Partido"])
    
    with tab1:
        st.subheader("Partidos Políticos")
        
        if st.button("Listar Todos os Partidos"):
            with st.spinner("Buscando partidos..."):
                resultado = api.listar_partidos(itens=50)
                
                if "dados" in resultado and resultado["dados"]:
                    st.session_state.lista_partidos = pd.DataFrame(resultado["dados"])
                    st.success(f"Encontrados {len(st.session_state.lista_partidos)} partidos")
                elif "error" in resultado:
                    st.error(f"Erro: {resultado['error']}")
                    st.session_state.lista_partidos = None
                else:
                    st.warning("Nenhum partido encontrado")
                    st.session_state.lista_partidos = None
        
        if st.session_state.lista_partidos is not None:
            st.info("💡 Clique em uma linha para ver os detalhes do partido")
            event = st.dataframe(
                st.session_state.lista_partidos,
                width='stretch',
                on_select="rerun",
                selection_mode="single-row"
            )
            
            if event.selection and len(event.selection.rows) > 0:
                row_index = event.selection.rows[0]
                st.session_state.partido_selecionado = st.session_state.lista_partidos.iloc[row_index]['id']
                st.success(f"✅ Partido selecionado! ID: {st.session_state.partido_selecionado}")
    
    with tab2:
        st.subheader("Detalhes do Partido")
        
        if st.session_state.partido_selecionado:
            id_partido = st.session_state.partido_selecionado
            st.info(f"📋 Partido ID: {id_partido} (selecionado da lista)")
            
            sub_tab1, sub_tab2 = st.tabs(["Informações", "Membros"])
            
            with sub_tab1:
                with st.spinner("Buscando detalhes..."):
                    resultado = api.detalhes_partido(id_partido)
                    
                    if "dados" in resultado:
                        dados = resultado["dados"]
                        if isinstance(dados, list) and len(dados) > 0:
                            dados = dados[0]
                        
                        if dados:
                            st.markdown(f"### {dados.get('sigla', 'N/A')} - {dados.get('nome', 'N/A')}")
                            st.json(dados)
                    elif "error" in resultado:
                        st.error(f"Erro: {resultado['error']}")
                    else:
                        st.warning("Partido não encontrado")
            
            with sub_tab2:
                with st.spinner("Buscando membros..."):
                    resultado = api.membros_partido(id_partido, itens=100)
                    
                    if "dados" in resultado and resultado["dados"]:
                        df = pd.DataFrame(resultado["dados"])
                        st.success(f"Encontrados {len(df)} membros")
                        st.dataframe(df, width='stretch')
                    elif "error" in resultado:
                        st.error(f"Erro: {resultado['error']}")
                    else:
                        st.warning("Nenhum membro encontrado")
            
            if st.button("🔄 Limpar Seleção", key="limpar_partido"):
                st.session_state.partido_selecionado = None
                st.session_state.lista_partidos = None
                st.rerun()
        else:
            st.info("👈 Selecione um partido na aba 'Listar Partidos' para ver os detalhes.")

# ========== BLOCOS ==========
elif opcao == "Blocos":
    st.header("🤝 Blocos Parlamentares")
    
    if st.button("Listar Blocos"):
        with st.spinner("Buscando blocos..."):
            resultado = api.listar_blocos(itens=50)
            
            if "dados" in resultado and resultado["dados"]:
                df = pd.DataFrame(resultado["dados"])
                st.success(f"Encontrados {len(df)} blocos")
                st.dataframe(df, width='stretch')
            elif "error" in resultado:
                st.error(f"Erro: {resultado['error']}")
            else:
                st.warning("Nenhum bloco encontrado")

# ========== EVENTOS ==========
elif opcao == "Eventos":
    st.header("📅 Eventos")
    
    # Inicializar estado da sessão
    if 'evento_selecionado' not in st.session_state:
        st.session_state.evento_selecionado = None
    if 'lista_eventos' not in st.session_state:
        st.session_state.lista_eventos = None
    
    tab1, tab2 = st.tabs(["Listar Eventos", "Detalhes do Evento"])
    
    with tab1:
        st.subheader("Buscar Eventos")
        col1, col2 = st.columns(2)
        
        with col1:
            data_inicio_evt = st.date_input("Data Início", value=datetime.now() - timedelta(days=7), key="evt_inicio")
        with col2:
            data_fim_evt = st.date_input("Data Fim", value=datetime.now() + timedelta(days=7), key="evt_fim")
        
        if st.button("Buscar Eventos"):
            with st.spinner("Buscando eventos..."):
                resultado = api.listar_eventos(
                    data_inicio=data_inicio_evt.strftime("%Y-%m-%d"),
                    data_fim=data_fim_evt.strftime("%Y-%m-%d"),
                    itens=100
                )
                
                if "dados" in resultado and resultado["dados"]:
                    st.session_state.lista_eventos = pd.DataFrame(resultado["dados"])
                    st.success(f"Encontrados {len(st.session_state.lista_eventos)} eventos")
                elif "error" in resultado:
                    st.error(f"Erro: {resultado['error']}")
                    st.session_state.lista_eventos = None
                else:
                    st.warning("Nenhum evento encontrado")
                    st.session_state.lista_eventos = None
        
        if st.session_state.lista_eventos is not None:
            st.info("💡 Clique em uma linha para ver os detalhes do evento")
            event = st.dataframe(
                st.session_state.lista_eventos,
                width='stretch',
                on_select="rerun",
                selection_mode="single-row"
            )
            
            if event.selection and len(event.selection.rows) > 0:
                row_index = event.selection.rows[0]
                st.session_state.evento_selecionado = st.session_state.lista_eventos.iloc[row_index]['id']
                st.success(f"✅ Evento selecionado! ID: {st.session_state.evento_selecionado}")
    
    with tab2:
        st.subheader("Detalhes do Evento")
        
        if st.session_state.evento_selecionado:
            id_evento = st.session_state.evento_selecionado
            st.info(f"📋 Evento ID: {id_evento} (selecionado da lista)")
            
            with st.spinner("Buscando detalhes..."):
                resultado = api.detalhes_evento(id_evento)
                
                if "dados" in resultado:
                    dados = resultado["dados"]
                    if isinstance(dados, list) and len(dados) > 0:
                        dados = dados[0]
                    
                    if dados:
                        st.markdown(f"### {dados.get('descricao', 'N/A')}")
                        st.write(f"**Data:** {dados.get('dataHoraInicio', 'N/A')}")
                        st.write(f"**Local:** {dados.get('localCamara', {}).get('nome', 'N/A')}")
                        st.subheader("📄 Dados Completos")
                        st.json(dados)
                elif "error" in resultado:
                    st.error(f"Erro: {resultado['error']}")
                else:
                    st.warning("Evento não encontrado")
            
            if st.button("🔄 Limpar Seleção", key="limpar_evento"):
                st.session_state.evento_selecionado = None
                st.session_state.lista_eventos = None
                st.rerun()
        else:
            st.info("👈 Selecione um evento na aba 'Listar Eventos' para ver os detalhes.")

# ========== VOTAÇÕES ==========
elif opcao == "Votações":
    st.header("🗳️ Votações")
    
    # Inicializar estado da sessão
    if 'votacao_selecionada' not in st.session_state:
        st.session_state.votacao_selecionada = None
    if 'lista_votacoes' not in st.session_state:
        st.session_state.lista_votacoes = None
    
    tab1, tab2 = st.tabs(["Listar Votações", "Detalhes da Votação"])
    
    with tab1:
        st.subheader("Buscar Votações")
        
        id_prop_vot = st.number_input("ID Proposição (opcional)", min_value=0, step=1, 
                                      help="Digite o ID de uma proposição específica para ver suas votações")
        
        if st.button("Buscar Votações"):
            with st.spinner("Buscando votações..."):
                resultado = api.listar_votacoes(
                    id_proposicao=id_prop_vot if id_prop_vot > 0 else None,
                    itens=100
                )
                
                if "dados" in resultado and resultado["dados"]:
                    st.session_state.lista_votacoes = pd.DataFrame(resultado["dados"])
                    st.success(f"Encontradas {len(st.session_state.lista_votacoes)} votações")
                elif "error" in resultado:
                    st.error(f"Erro: {resultado['error']}")
                    st.session_state.lista_votacoes = None
                else:
                    st.warning("Nenhuma votação encontrada")
                    st.session_state.lista_votacoes = None
        
        if st.session_state.lista_votacoes is not None:
            st.info("💡 Clique em uma linha para ver os detalhes da votação")
            event = st.dataframe(
                st.session_state.lista_votacoes,
                width='stretch',
                on_select="rerun",
                selection_mode="single-row"
            )
            
            if event.selection and len(event.selection.rows) > 0:
                row_index = event.selection.rows[0]
                st.session_state.votacao_selecionada = st.session_state.lista_votacoes.iloc[row_index]['id']
                st.success(f"✅ Votação selecionada! ID: {st.session_state.votacao_selecionada}")
    
    with tab2:
        st.subheader("Detalhes da Votação")
        
        if st.session_state.votacao_selecionada:
            id_votacao = str(st.session_state.votacao_selecionada)
            st.info(f"📋 Votação ID: {id_votacao} (selecionada da lista)")
            
            sub_tab1, sub_tab2 = st.tabs(["Informações", "Votos"])
            
            with sub_tab1:
                with st.spinner("Buscando detalhes..."):
                    resultado = api.detalhes_votacao(id_votacao)
                    
                    if "dados" in resultado:
                        dados = resultado["dados"]
                        if isinstance(dados, list) and len(dados) > 0:
                            dados = dados[0]
                        
                        if dados:
                            st.markdown(f"### {dados.get('descricao', 'N/A')}")
                            st.write(f"**Data:** {dados.get('data', 'N/A')}")
                            st.write(f"**Aprovação:** {dados.get('aprovacao', 'N/A')}")
                            st.subheader("📄 Dados Completos")
                            st.json(dados)
                    elif "error" in resultado:
                        st.error(f"Erro: {resultado['error']}")
                    else:
                        st.warning("Votação não encontrada")
            
            with sub_tab2:
                with st.spinner("Buscando votos..."):
                    resultado = api.votos_votacao(id_votacao)
                    
                    if "dados" in resultado and resultado["dados"]:
                        df = pd.DataFrame(resultado["dados"])
                        st.success(f"Encontrados {len(df)} votos")
                        st.dataframe(df, width='stretch')
                        
                        # Estatísticas de votos
                        if "tipoVoto" in df.columns:
                            st.subheader("📊 Distribuição de Votos")
                            contagem = df["tipoVoto"].value_counts()
                            st.bar_chart(contagem)
                    elif "error" in resultado:
                        st.error(f"Erro: {resultado['error']}")
                    else:
                        st.warning("Nenhum voto encontrado")
            
            if st.button("🔄 Limpar Seleção", key="limpar_votacao"):
                st.session_state.votacao_selecionada = None
                st.session_state.lista_votacoes = None
                st.rerun()
        else:
            st.info("👈 Selecione uma votação na aba 'Listar Votações' para ver os detalhes.")

# ========== ÓRGÃOS ==========
elif opcao == "Órgãos":
    st.header("🏢 Órgãos")
    
    # Inicializar estado da sessão
    if 'orgao_selecionado' not in st.session_state:
        st.session_state.orgao_selecionado = None
    if 'lista_orgaos' not in st.session_state:
        st.session_state.lista_orgaos = None
    
    tab1, tab2 = st.tabs(["Listar Órgãos", "Detalhes do Órgão"])
    
    with tab1:
        st.subheader("Órgãos da Câmara")
        sigla_orgao = st.text_input("Sigla (opcional)")
        
        if st.button("Buscar Órgãos"):
            with st.spinner("Buscando órgãos..."):
                resultado = api.listar_orgaos(
                    sigla=sigla_orgao if sigla_orgao else None,
                    itens=100
                )
                
                if "dados" in resultado and resultado["dados"]:
                    st.session_state.lista_orgaos = pd.DataFrame(resultado["dados"])
                    st.success(f"Encontrados {len(st.session_state.lista_orgaos)} órgãos")
                elif "error" in resultado:
                    st.error(f"Erro: {resultado['error']}")
                    st.session_state.lista_orgaos = None
                else:
                    st.warning("Nenhum órgão encontrado")
                    st.session_state.lista_orgaos = None
        
        if st.session_state.lista_orgaos is not None:
            st.info("💡 Clique em uma linha para ver os detalhes do órgão")
            event = st.dataframe(
                st.session_state.lista_orgaos,
                width='stretch',
                on_select="rerun",
                selection_mode="single-row"
            )
            
            if event.selection and len(event.selection.rows) > 0:
                row_index = event.selection.rows[0]
                st.session_state.orgao_selecionado = st.session_state.lista_orgaos.iloc[row_index]['id']
                st.success(f"✅ Órgão selecionado! ID: {st.session_state.orgao_selecionado}")
    
    with tab2:
        st.subheader("Detalhes do Órgão")
        
        if st.session_state.orgao_selecionado:
            id_orgao = st.session_state.orgao_selecionado
            st.info(f"📋 Órgão ID: {id_orgao} (selecionado da lista)")
            
            sub_tab1, sub_tab2 = st.tabs(["Informações", "Membros"])
            
            with sub_tab1:
                with st.spinner("Buscando detalhes..."):
                    resultado = api.detalhes_orgao(id_orgao)
                    
                    if "dados" in resultado:
                        dados = resultado["dados"]
                        if isinstance(dados, list) and len(dados) > 0:
                            dados = dados[0]
                        
                        if dados:
                            st.markdown(f"### {dados.get('sigla', 'N/A')} - {dados.get('nome', 'N/A')}")
                            st.write(f"**Tipo:** {dados.get('tipoOrgao', 'N/A')}")
                            st.subheader("📄 Dados Completos")
                            st.json(dados)
                    elif "error" in resultado:
                        st.error(f"Erro: {resultado['error']}")
                    else:
                        st.warning("Órgão não encontrado")
            
            with sub_tab2:
                with st.spinner("Buscando membros..."):
                    resultado = api.membros_orgao(id_orgao, itens=100)
                    
                    if "dados" in resultado and resultado["dados"]:
                        df = pd.DataFrame(resultado["dados"])
                        st.success(f"Encontrados {len(df)} membros")
                        st.dataframe(df, width='stretch')
                    elif "error" in resultado:
                        st.error(f"Erro: {resultado['error']}")
                    else:
                        st.warning("Nenhum membro encontrado")
            
            if st.button("🔄 Limpar Seleção", key="limpar_orgao"):
                st.session_state.orgao_selecionado = None
                st.session_state.lista_orgaos = None
                st.rerun()
        else:
            st.info("👈 Selecione um órgão na aba 'Listar Órgãos' para ver os detalhes.")

# Footer
st.markdown("---")
st.markdown(
    """
    **Fonte dos Dados:** [Dados Abertos - Câmara dos Deputados](https://dadosabertos.camara.leg.br/)
    
    **Documentação da API:** [https://dadosabertos.camara.leg.br/swagger/api.html](https://dadosabertos.camara.leg.br/swagger/api.html)
    """
)

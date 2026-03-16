"""
Aplicação Streamlit para consumir a API da Câmara dos Deputados
"""

import streamlit as st
import pandas as pd
import importlib
import sys
import os
from dotenv import load_dotenv
import psycopg2
from psycopg2 import OperationalError
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse, urlunparse

# Forçar recarga do módulo api_client
if 'api_client' in sys.modules:
    importlib.reload(sys.modules['api_client'])

from api_client import CamaraAPIClient
from datetime import datetime, timedelta

# Carregar variáveis de ambiente
load_dotenv()

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

# Cache para tipos de proposição
@st.cache_data
def get_tipos_proposicao():
    """Carrega e cacheia os tipos de proposição"""
    tipos = api.tipos_proposicao()
    if tipos and 'dados' in tipos:
        # Criar dicionário sigla -> nome
        return {t['sigla']: t['nome'] for t in tipos['dados']}
    return {}

# Limpar cache se necessário (força recarga do módulo)
if st.sidebar.button("🔄 Recarregar API"):
    st.cache_resource.clear()
    st.cache_data.clear()
    st.rerun()

api = get_api_client()
tipos_prop = get_tipos_proposicao()

# Selector de domínio (Câmara ou ALESC)
st.sidebar.title("Sistema Legislativo")
dominio = st.sidebar.radio(
    "Selecione o domínio:",
    ["🏛️ Câmara dos Deputados", "🏛️ ALESC"],
    key="dominio_selecionado"
)

st.sidebar.markdown("---")

if dominio == "🏛️ Câmara dos Deputados":
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
            "Órgãos",
            "Notícias",
            "Teste PostgreSQL"
        ]
    )
else:
    opcao = "__ALESC__"

# ========== DEPUTADOS ==========
if opcao == "Deputados":
    st.header("👤 Deputados")
    
    # Inicializar o estado da sessão para armazenar o deputado selecionado e lista de deputados
    if 'deputado_selecionado' not in st.session_state:
        st.session_state.deputado_selecionado = None
    if 'lista_deputados' not in st.session_state:
        st.session_state.lista_deputados = None
    
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Listar Deputados", "Detalhes do Deputado", "Despesas", "Discursos", "Proposições"])
    
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

            df_deputados_display = st.session_state.lista_deputados.copy()
            sigla_col = next(
                (col for col in ['siglaPartido', 'sigla_partido', 'partido'] if col in df_deputados_display.columns),
                None
            )
            if 'nome' in df_deputados_display.columns and sigla_col:
                df_deputados_display['nome'] = df_deputados_display.apply(
                    lambda row: f"{row['nome']} ({row[sigla_col]})"
                    if pd.notna(row[sigla_col]) and str(row[sigla_col]).strip()
                    else row['nome'],
                    axis=1
                )
            
            # Usar st.dataframe com seleção de linha
            event = st.dataframe(
                df_deputados_display,
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
    
    with tab5:
        if st.session_state.deputado_selecionado:
            st.info(f"📋 Proposições do Deputado ID: {st.session_state.deputado_selecionado}")
            
            # Inicializar página e total de páginas se não existir
            if 'pagina_props_deputado' not in st.session_state:
                st.session_state.pagina_props_deputado = 1
            if 'total_paginas_props_deputado' not in st.session_state:
                st.session_state.total_paginas_props_deputado = 1
            
            if st.button("🔍 Buscar Proposições", key="buscar_props_dep"):
                st.session_state.pagina_props_deputado = 1  # Resetar para página 1 ao buscar
            
            with st.spinner("Buscando proposições..."):
                resultado = api.proposicoes_deputado(
                    st.session_state.deputado_selecionado,
                    pagina=st.session_state.pagina_props_deputado,
                    itens=25
                )
                
                if resultado and 'dados' in resultado:
                    proposicoes = resultado['dados']
                    
                    # Calcular total de páginas baseado nos links da API
                    if 'links' in resultado:
                        links = resultado['links']
                        # Tentar extrair o total de páginas dos links
                        for link in links:
                            if link.get('rel') == 'last':
                                # Extrair número da última página da URL
                                import re
                                match = re.search(r'pagina=(\d+)', link.get('href', ''))
                                if match:
                                    st.session_state.total_paginas_props_deputado = int(match.group(1))
                    
                    if proposicoes:
                        st.success(f"✅ {len(proposicoes)} proposições encontradas")
                        
                        # Preparar dados para exibição
                        props_display = []
                        for prop in proposicoes:
                            sigla = prop.get('siglaTipo', '')
                            props_display.append({
                                'ID': prop.get('id', ''),
                                'Tipo': sigla,
                                'Descrição': tipos_prop.get(sigla, 'N/A'),
                                'Número': prop.get('numero', ''),
                                'Ano': prop.get('ano', ''),
                                'Ementa': prop.get('ementa', '')[:100] + '...' if len(prop.get('ementa', '')) > 100 else prop.get('ementa', '')
                            })
                        
                        df_props = pd.DataFrame(props_display)
                        st.dataframe(df_props, width='stretch', height=925)
                        
                        # Controles de paginação logo abaixo da grid
                        col1, col2, col3 = st.columns([2, 1, 2])
                        with col1:
                            if st.button("⬅️ Página Anterior", key="prev_props_dep", disabled=(st.session_state.pagina_props_deputado == 1)):
                                st.session_state.pagina_props_deputado -= 1
                                st.rerun()
                        with col2:
                            st.write(f"Página {st.session_state.pagina_props_deputado} / {st.session_state.total_paginas_props_deputado}")
                        with col3:
                            tem_proxima = len(proposicoes) == 25 and st.session_state.pagina_props_deputado < st.session_state.total_paginas_props_deputado
                            if st.button("Próxima Página ➡️", key="next_props_dep", disabled=not tem_proxima):
                                st.session_state.pagina_props_deputado += 1
                                st.rerun()
                        
                        # Exibir detalhes em expanders
                        st.subheader("Detalhes das Proposições")
                        for i, prop in enumerate(proposicoes):
                            with st.expander(f"{prop.get('siglaTipo', '')} {prop.get('numero', '')}/{prop.get('ano', '')} - {prop.get('ementa', '')[:80]}..."):
                                st.write("**Ementa Completa:**")
                                st.write(prop.get('ementa', 'N/A'))
                                st.write("**Informações:**")
                                st.write(f"- ID: {prop.get('id', 'N/A')}")
                                st.write(f"- Tipo: {prop.get('siglaTipo', 'N/A')}")
                                st.write(f"- Número: {prop.get('numero', 'N/A')}")
                                st.write(f"- Ano: {prop.get('ano', 'N/A')}")
                                if 'uri' in prop:
                                    st.write(f"- [Link da API]({prop['uri']})")
                                
                                # Votações da proposição
                                st.write("---")
                                st.write("**Votações:**")
                                if st.button(f"🗳️ Buscar Votações", key=f"vot_prop_{prop.get('id')}_{st.session_state.pagina_props_deputado}"):
                                    with st.spinner("Buscando votações..."):
                                        vot_result = api.votacoes_proposicao(prop.get('id'))
                                        if vot_result and 'dados' in vot_result and vot_result['dados']:
                                            st.success(f"✅ {len(vot_result['dados'])} votações encontradas")
                                            for j, vot in enumerate(vot_result['dados']):
                                                st.write(f"  {j+1}. **{vot.get('data', 'N/A')}** - {vot.get('descricao', 'N/A')[:80]}")
                                                st.write(f"     - Aprovação: {vot.get('aprovacao', 'N/A')}")
                                        else:
                                            st.info("Nenhuma votação encontrada")
                    else:
                        st.warning("Nenhuma proposição encontrada nesta página")
                elif resultado and 'error' in resultado:
                    st.error(f"Erro: {resultado['error']}")
                else:
                    st.warning("Nenhuma proposição encontrada para este deputado")
            
            # Botão para limpar seleção
            if st.button("🔄 Limpar Seleção", key="limpar_props_dep"):
                st.session_state.deputado_selecionado = None
                st.session_state.lista_deputados = None
                if 'pagina_props_deputado' in st.session_state:
                    del st.session_state.pagina_props_deputado
                if 'total_paginas_props_deputado' in st.session_state:
                    del st.session_state.total_paginas_props_deputado
                st.rerun()
        else:
            st.info("👈 Selecione um deputado na aba 'Listar Deputados' para ver as proposições aqui.")

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
        
        st.info("💡 **Dica:** Por padrão, são listadas proposições dos últimos 30 dias. "
               "Use o filtro de tramitação apenas se quiser filtrar por período específico de mudanças.")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            sigla_tipo = st.selectbox("Tipo", ["", "PL", "PEC", "PLP", "PDC", "MPV", "PRC"])
        with col2:
            numero_prop = st.number_input("Número", min_value=0, step=1)
        with col3:
            ano_prop = st.number_input("Ano de Apresentação", min_value=1900, max_value=datetime.now().year, 
                                      value=datetime.now().year)
        
        usar_filtro_tramitacao = st.checkbox("Filtrar por período de tramitação", value=False,
                                             help="Marque para filtrar proposições que tiveram mudanças em um período específico")
        
        data_inicio = None
        data_fim = None
        
        if usar_filtro_tramitacao:
            col4, col5 = st.columns(2)
            with col4:
                data_inicio = st.date_input("Data Início Tramitação", value=datetime.now() - timedelta(days=30))
            with col5:
                data_fim = st.date_input("Data Fim Tramitação", value=datetime.now())
        
        if st.button("Buscar Proposições"):
            with st.spinner("Buscando proposições..."):
                resultado = api.listar_proposicoes(
                    sigla_tipo=sigla_tipo if sigla_tipo else None,
                    numero=numero_prop if numero_prop > 0 else None,
                    ano=ano_prop,
                    data_inicio=data_inicio.strftime("%Y-%m-%d") if data_inicio else None,
                    data_fim=data_fim.strftime("%Y-%m-%d") if data_fim else None,
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
            sub_tab1, sub_tab2, sub_tab3, sub_tab4, sub_tab5 = st.tabs(["Informações Gerais", "Autores", "Tramitações", "Temas", "Votações"])
            
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
            
            with sub_tab5:
                st.subheader("Votações da Proposição")
                
                if st.button("Buscar Votações", key="buscar_votacoes_prop"):
                    with st.spinner("Buscando votações..."):
                        resultado = api.votacoes_proposicao(id_proposicao)
                        
                        if resultado and 'dados' in resultado:
                            votacoes = resultado['dados']
                            if votacoes:
                                st.success(f"✅ {len(votacoes)} votações encontradas")
                                
                                for i, vot in enumerate(votacoes):
                                    with st.expander(f"Votação {i+1} - {vot.get('data', 'N/A')} - {vot.get('descricao', 'N/A')[:80]}"):
                                        st.write(f"**ID:** {vot.get('id', 'N/A')}")
                                        st.write(f"**Data:** {vot.get('data', 'N/A')}")
                                        st.write(f"**Descrição:** {vot.get('descricao', 'N/A')}")
                                        st.write(f"**Aprovação:** {vot.get('aprovacao', 'N/A')}")
                                        if 'uri' in vot:
                                            st.write(f"[Link da API]({vot['uri']})")
                            else:
                                st.info("Nenhuma votação encontrada para esta proposição")
                        elif resultado and "error" in resultado:
                            st.error(f"Erro: {resultado['error']}")
                        else:
                            st.info("Nenhuma votação encontrada para esta proposição")
            
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

# ========== NOTÍCIAS ==========
elif opcao == "Notícias":
    st.header("📰 Notícias - Feeds RSS da Câmara dos Deputados")
    
    @st.cache_data(ttl=3600)  # Cache por 1 hora
    def extrair_feeds_rss():
        """Extrai todos os feeds RSS da página de notícias da Câmara"""
        try:
            url_base = "https://www.camara.leg.br/noticias/rss"
            response = requests.get(url_base, timeout=10)
            response.raise_for_status()
            
            # Parse do HTML para encontrar links de RSS
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')
            
            feeds = []
            
            # Buscar pelos painéis que contêm os feeds
            # A estrutura é: <h4 class="media-heading">Título</h4> seguido de <a href="...">
            paineis = soup.find_all('div', class_='panel-body')
            
            for painel in paineis:
                # Buscar o título no h4 com classe media-heading
                titulo_elem = painel.find('h4', class_='media-heading')
                if not titulo_elem:
                    continue
                
                titulo = titulo_elem.get_text(strip=True)
                
                # Buscar o link RSS dentro do mesmo painel
                link_elem = painel.find('a', href=True)
                if not link_elem:
                    continue
                
                href = link_elem.get('href', '')
                if 'rss' in href.lower():
                    url = urljoin(url_base, href)
                    
                    # Evitar duplicatas
                    if url not in [f['url'] for f in feeds]:
                        feeds.append({
                            'titulo': titulo,
                            'url': url
                        })
            
            # Se não encontrou feeds no HTML, tentar feeds conhecidos
            if not feeds:
                feeds_conhecidos = [
                    {'titulo': 'Todas as Notícias', 'url': 'https://www.camara.leg.br/noticias/rss'},
                    {'titulo': 'Últimas Notícias', 'url': 'https://www.camara.leg.br/noticias/ultimas/rss'},
                    {'titulo': 'Notícias de Plenário', 'url': 'https://www.camara.leg.br/noticias/plenario/rss'},
                    {'titulo': 'Notícias de Política', 'url': 'https://www.camara.leg.br/noticias/politica/rss'},
                    {'titulo': 'Notícias de Economia', 'url': 'https://www.camara.leg.br/noticias/economia/rss'},
                ]
                
                # Validar cada feed
                for feed in feeds_conhecidos:
                    try:
                        test_response = requests.head(feed['url'], timeout=5)
                        if test_response.status_code == 200:
                            feeds.append(feed)
                    except:
                        pass
            
            return feeds
            
        except Exception as e:
            st.error(f"Erro ao extrair feeds RSS: {str(e)}")
            return []
    
    @st.cache_data(ttl=300)  # Cache por 5 minutos
    def buscar_noticias_rss(url_feed, exibir_erro=True):
        """Busca notícias de um feed RSS específico"""
        try:
            response = requests.get(url_feed, timeout=10)
            response.raise_for_status()
            
            # Parse do XML RSS
            root = ET.fromstring(response.content)
            
            noticias = []
            
            # RSS 2.0
            for item in root.findall('.//item'):
                titulo = item.find('title')
                link = item.find('link')
                descricao = item.find('description')
                data = item.find('pubDate')
                
                noticias.append({
                    'Título': titulo.text if titulo is not None else 'Sem título',
                    'Link': link.text if link is not None else '',
                    'Descrição': descricao.text if descricao is not None else '',
                    'Data': data.text if data is not None else ''
                })
            
            # Se não encontrou itens no formato RSS 2.0, tentar Atom
            if not noticias:
                for entry in root.findall('.//{http://www.w3.org/2005/Atom}entry'):
                    titulo = entry.find('{http://www.w3.org/2005/Atom}title')
                    link = entry.find('{http://www.w3.org/2005/Atom}link')
                    summary = entry.find('{http://www.w3.org/2005/Atom}summary')
                    updated = entry.find('{http://www.w3.org/2005/Atom}updated')
                    
                    noticias.append({
                        'Título': titulo.text if titulo is not None else 'Sem título',
                        'Link': link.get('href', '') if link is not None else '',
                        'Descrição': summary.text if summary is not None else '',
                        'Data': updated.text if updated is not None else ''
                    })
            
            return noticias
            
        except Exception as e:
            if exibir_erro:
                st.error(f"Erro ao buscar notícias do feed: {str(e)}")
            return []

    def limpar_html_e_links(html_texto):
        """Remove tags HTML e mantém apenas o texto dos hiperlinks."""
        if not html_texto:
            return ""

        from bs4 import BeautifulSoup
        import re

        soup = BeautifulSoup(html_texto, 'html.parser')

        for tag in soup(['script', 'style', 'noscript']):
            tag.decompose()

        for link in soup.find_all('a'):
            link.replace_with(link.get_text(' ', strip=True))

        texto_limpo = soup.get_text(' ', strip=True)
        return re.sub(r'\s+', ' ', texto_limpo).strip()

    def normalizar_link(url, base_url=''):
        """Normaliza URL para deduplicação e validação."""
        if not url:
            return ""

        url_completa = urljoin(base_url, url.strip())
        parsed = urlparse(url_completa)

        if parsed.scheme not in ('http', 'https') or not parsed.netloc:
            return ""

        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip('/') if parsed.path not in ('', '/') else parsed.path
        return urlunparse((parsed.scheme, netloc, path, '', '', ''))

    def eh_link_noticia_camara(url):
        """Valida se URL é de notícia do domínio da Câmara."""
        if not url:
            return False

        parsed = urlparse(url)
        host = parsed.netloc.lower().split(':')[0]
        dominios_permitidos = ('camara.leg.br', 'camara.gov.br')

        mesmo_dominio = any(
            host == dominio or host.endswith(f'.{dominio}')
            for dominio in dominios_permitidos
        )

        return mesmo_dominio and '/noticias/' in parsed.path.lower()

    def extrair_links_noticias_relacionadas(soup, base_url=''):
        """Extrai links de notícias da Câmara no HTML original da notícia."""
        if soup is None:
            return []

        links = []
        vistos = set()

        # Prioriza blocos típicos de relacionadas e, na falta deles, varre a página.
        anchors = []
        seletores_relacionadas = [
            '.relacionadas a[href]',
            '.noticias-relacionadas a[href]',
            '.veja-tambem a[href]',
            '[class*="relacionad"] a[href]',
            '[id*="relacionad"] a[href]',
            'article a[href]'
        ]

        for seletor in seletores_relacionadas:
            anchors.extend(soup.select(seletor))

        if not anchors:
            anchors = soup.find_all('a', href=True)

        for anchor in anchors:
            link = normalizar_link(anchor.get('href', ''), base_url)
            if (
                not link or
                link in vistos or
                link == normalizar_link(base_url) or
                not eh_link_noticia_camara(link)
            ):
                continue

            vistos.add(link)
            links.append(link)

        return links

    def extrair_conteudo_noticia(url_noticia, retornar_relacionadas=False):
        """Extrai o texto principal da notícia removendo HTML e hyperlinks."""
        try:
            response = requests.get(
                url_noticia,
                timeout=20,
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            response.raise_for_status()

            from bs4 import BeautifulSoup
            import re

            soup = BeautifulSoup(response.text, 'html.parser')

            links_relacionados = extrair_links_noticias_relacionadas(soup, url_noticia)

            for tag in soup(['script', 'style', 'noscript', 'svg']):
                tag.decompose()

            seletores_conteudo = [
                'article .g-artigo__texto',
                '.g-artigo__texto',
                'article .noticia__texto',
                '.noticia__texto',
                '.materia-content',
                '.texto-noticia',
                'article',
                'main',
                'body'
            ]

            bloco_conteudo = None
            for seletor in seletores_conteudo:
                candidato = soup.select_one(seletor)
                if candidato and len(candidato.get_text(' ', strip=True)) > 120:
                    bloco_conteudo = candidato
                    break

            if bloco_conteudo is None:
                bloco_conteudo = soup.body if soup.body else soup

            for link in bloco_conteudo.find_all('a'):
                link.replace_with(link.get_text(' ', strip=True))

            texto = bloco_conteudo.get_text(' ', strip=True)
            texto_limpo = re.sub(r'\s+', ' ', texto).strip()

            if retornar_relacionadas:
                return texto_limpo, links_relacionados

            return texto_limpo
        except Exception:
            if retornar_relacionadas:
                return "", []
            return ""

    def conectar_postgresql_banco():
        """Abre conexão com o banco banco usando variáveis de ambiente."""
        pg_host = os.getenv('POSTGREE_HOST', 'pgsql.hetzner.welm.com.br')
        pg_port = int(os.getenv('POSTGREE_PORT', '443'))
        pg_user = os.getenv('POSTGREE_USER', 'marcio')
        pg_password = os.getenv('POSTGREE_PASSWORD', '')

        connection = psycopg2.connect(
            host=pg_host,
            port=pg_port,
            user=pg_user,
            password=pg_password,
            database='banco',
            connect_timeout=15
        )
        connection.autocommit = True
        return connection

    def importar_noticias_feeds_para_postgres(feeds):
        """Importa notícias de todos os feeds para doutorado.noticias."""
        resultado = {
            'total_feeds': len(feeds),
            'total_lidas': 0,
            'importadas': 0,
            'relacionadas_importadas': 0,
            'relacionadas_encontradas': 0,
            'duplicadas': 0,
            'sem_link': 0,
            'falhas': 0,
            'erro': None
        }

        if not feeds:
            return resultado

        connection = None
        cursor = None

        try:
            connection = conectar_postgresql_banco()
            cursor = connection.cursor()

            cursor.execute("CREATE SCHEMA IF NOT EXISTS doutorado;")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS doutorado.noticias (
                    id BIGSERIAL PRIMARY KEY,
                    link TEXT NOT NULL,
                    data_importacao TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    conteudo TEXT,
                    CONSTRAINT noticias_link_url_completa_chk CHECK (link ~* '^https?://')
                );
                """
            )

            insert_sql = """
                INSERT INTO doutorado.noticias (link, data_importacao, conteudo)
                SELECT %s, NOW(), %s
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM doutorado.noticias
                    WHERE regexp_replace(link, '/+$', '') = regexp_replace(%s, '/+$', '')
                );
            """

            links_processados = set()

            for feed in feeds:
                url_feed = feed.get('url', '')
                if not url_feed:
                    continue

                noticias_feed = buscar_noticias_rss(url_feed, exibir_erro=False)

                for noticia in noticias_feed:
                    resultado['total_lidas'] += 1

                    link_noticia = normalizar_link(noticia.get('Link') or '', url_feed)
                    if not link_noticia:
                        resultado['sem_link'] += 1
                        continue

                    conteudo, links_relacionados = extrair_conteudo_noticia(
                        link_noticia,
                        retornar_relacionadas=True
                    )
                    corpo_rss = noticia.get('Descrição', '')

                    if not conteudo:
                        conteudo = limpar_html_e_links(corpo_rss)

                    try:
                        cursor.execute(insert_sql, (link_noticia, conteudo, link_noticia))
                        if cursor.rowcount == 1:
                            resultado['importadas'] += 1
                        else:
                            resultado['duplicadas'] += 1
                    except Exception:
                        resultado['falhas'] += 1

                    links_processados.add(link_noticia)

                    # Procura links de notícias relacionadas no HTML original da notícia principal.
                    resultado['relacionadas_encontradas'] += len(links_relacionados)

                    for link_relacionado in links_relacionados:
                        if link_relacionado in links_processados or link_relacionado == link_noticia:
                            continue

                        links_processados.add(link_relacionado)
                        conteudo_relacionado = extrair_conteudo_noticia(link_relacionado)

                        # Só importa link relacionado quando conseguir abrir e extrair conteúdo principal.
                        if not conteudo_relacionado:
                            continue

                        try:
                            cursor.execute(insert_sql, (link_relacionado, conteudo_relacionado, link_relacionado))
                            if cursor.rowcount == 1:
                                resultado['importadas'] += 1
                                resultado['relacionadas_importadas'] += 1
                            else:
                                resultado['duplicadas'] += 1
                        except Exception:
                            resultado['falhas'] += 1

            return resultado
        except Exception as e:
            resultado['erro'] = str(e)
            return resultado
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
    
    # Interface principal
    tab1, tab2 = st.tabs(["📡 Feeds RSS Disponíveis", "📰 Notícias do Feed"])
    
    with tab1:
        st.subheader("Feeds RSS Disponíveis")
        st.info("Lista de feeds RSS encontrados no site da Câmara dos Deputados")
        
        if st.button("🔄 Atualizar Feeds"):
            st.cache_data.clear()
            st.rerun()
        
        with st.spinner("Buscando feeds RSS..."):
            feeds = extrair_feeds_rss()
        
        if feeds:
            # Criar DataFrame com os feeds
            df_feeds = pd.DataFrame(feeds)
            
            st.success(f"✅ {len(feeds)} feed(s) encontrado(s)")
            
            # Exibir tabela com links clicáveis
            st.dataframe(
                df_feeds,
                column_config={
                    "titulo": st.column_config.TextColumn(
                        "Título do Feed",
                        width="medium"
                    ),
                    "url": st.column_config.LinkColumn(
                        "URL do Feed RSS",
                        display_text="Abrir Feed"
                    )
                },
                hide_index=True,
                width='stretch'
            )
            
            # Armazenar feeds no session_state para uso na segunda aba
            st.session_state.feeds_disponiveis = feeds
        else:
            st.warning("Nenhum feed RSS encontrado.")
    
    with tab2:
        st.subheader("Notícias do Feed")

        if 'feeds_disponiveis' not in st.session_state or not st.session_state.feeds_disponiveis:
            with st.spinner("Carregando feeds RSS..."):
                st.session_state.feeds_disponiveis = extrair_feeds_rss()
        
        if 'feeds_disponiveis' in st.session_state and st.session_state.feeds_disponiveis:
            if st.button("⬇️ Importar todas as notícias dos feeds", type="primary"):
                with st.spinner("Importando notícias para o PostgreSQL..."):
                    status_importacao = importar_noticias_feeds_para_postgres(st.session_state.feeds_disponiveis)

                if status_importacao.get('erro'):
                    st.error(f"Erro durante a importação: {status_importacao['erro']}")
                else:
                    st.success(f"✅ Importação concluída. {status_importacao['importadas']} notícia(s) importada(s).")
                    st.info(
                        f"Feeds processados: {status_importacao['total_feeds']} | "
                        f"Notícias lidas: {status_importacao['total_lidas']} | "
                        f"Relacionadas encontradas: {status_importacao['relacionadas_encontradas']} | "
                        f"Relacionadas importadas: {status_importacao['relacionadas_importadas']} | "
                        f"Duplicadas: {status_importacao['duplicadas']} | "
                        f"Sem link: {status_importacao['sem_link']} | "
                        f"Falhas: {status_importacao['falhas']}"
                    )

            # Criar selectbox com os feeds disponíveis
            feed_opcoes = {f['titulo']: f['url'] for f in st.session_state.feeds_disponiveis}
            feed_selecionado = st.selectbox(
                "Selecione um feed para visualizar as notícias:",
                options=list(feed_opcoes.keys())
            )
            
            if feed_selecionado:
                url_feed = feed_opcoes[feed_selecionado]
                
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.info(f"📡 Feed: {feed_selecionado}")
                with col2:
                    if st.button("🔄 Atualizar Notícias"):
                        # Limpar apenas o cache desta função
                        st.cache_data.clear()
                        st.rerun()
                
                with st.spinner("Carregando notícias..."):
                    noticias = buscar_noticias_rss(url_feed)
                
                if noticias:
                    st.success(f"✅ {len(noticias)} notícia(s) encontrada(s)")
                    
                    # Criar DataFrame com as notícias
                    df_noticias = pd.DataFrame(noticias)
                    
                    # Exibir tabela com links clicáveis
                    st.dataframe(
                        df_noticias,
                        column_config={
                            "Título": st.column_config.TextColumn(
                                "Título",
                                width="large"
                            ),
                            "Link": st.column_config.LinkColumn(
                                "Link",
                                display_text="Abrir"
                            ),
                            "Descrição": st.column_config.TextColumn(
                                "Descrição",
                                width="large"
                            ),
                            "Data": st.column_config.TextColumn(
                                "Data de Publicação",
                                width="medium"
                            )
                        },
                        hide_index=True,
                        width='stretch'
                    )
                else:
                    st.warning("Nenhuma notícia encontrada neste feed.")
        else:
            st.info("Nenhum feed disponível para importação ou visualização.")

# ========== ALESC ==========
elif opcao == "__ALESC__":
    st.title("🏛️ Assembleia Legislativa do Estado de Santa Catarina - ALESC")
    st.markdown("---")

    def conectar_postgresql_banco_alesc():
        return psycopg2.connect(
            host=os.getenv('POSTGREE_HOST'),
            port=int(os.getenv('POSTGREE_PORT', 5432)),
            user=os.getenv('POSTGREE_USER'),
            password=os.getenv('POSTGREE_PASSWORD'),
            database='banco',
            connect_timeout=15,
            sslmode='require',
        )

    @st.cache_data(ttl=3600)
    def carregar_deputados_alesc():
        try:
            conn = conectar_postgresql_banco_alesc()
            cur = conn.cursor()
            cur.execute("""
                SELECT nome, partido, foto_url, link_perfil
                FROM doutorado.deputados_alesc
                ORDER BY nome
            """)
            rows = cur.fetchall()
            cur.close()
            conn.close()
            return [
                {'nome': r[0], 'partido': r[1], 'foto_url': r[2], 'link_perfil': r[3]}
                for r in rows
            ]
        except Exception as e:
            return []

    deputados_alesc = carregar_deputados_alesc()

    if not deputados_alesc:
        st.warning(
            "Nenhum deputado cadastrado ainda. "
            "Execute o script **alesc_scraper.py** na sua máquina local para popular os dados:\n\n"
            "```bash\n"
            "python alesc_scraper.py\n"
            "```"
        )
        st.info(
            "**Por quê rodar localmente?**\n\n"
            "O site www.alesc.sc.gov.br bloqueia conexões de IPs fora do Brasil. "
            "O script deve ser executado na sua máquina (IP brasileiro) e salvará os dados diretamente no banco PostgreSQL."
        )
    else:
        st.subheader(f"👤 Deputados Estaduais ({len(deputados_alesc)} encontrados)")

        # Filtros
        col_f1, col_f2 = st.columns([2, 1])
        with col_f1:
            busca = st.text_input("🔍 Buscar por nome", placeholder="Digite parte do nome...")
        with col_f2:
            partidos_disponiveis = sorted({d['partido'] for d in deputados_alesc if d['partido']})
            partido_filtro = st.selectbox("Filtrar por partido", ["Todos"] + partidos_disponiveis)

        # Aplicar filtros
        lista_filtrada = deputados_alesc
        if busca:
            lista_filtrada = [d for d in lista_filtrada if busca.lower() in d['nome'].lower()]
        if partido_filtro != "Todos":
            lista_filtrada = [d for d in lista_filtrada if d['partido'] == partido_filtro]

        st.markdown(f"*Exibindo {len(lista_filtrada)} deputado(s)*")
        st.markdown("---")

        # Grid de cards (4 por linha)
        cols_por_linha = 4
        for i in range(0, len(lista_filtrada), cols_por_linha):
            linha = lista_filtrada[i:i + cols_por_linha]
            cols = st.columns(cols_por_linha)
            for j, dep in enumerate(linha):
                with cols[j]:
                    if dep['foto_url']:
                        st.image(dep['foto_url'], width=140)
                    else:
                        st.markdown(
                            "<div style='width:140px;height:140px;background:#e0e0e0;"
                            "border-radius:8px;display:flex;align-items:center;"
                            "justify-content:center;font-size:40px;'>👤</div>",
                            unsafe_allow_html=True
                        )
                    nome_exibicao = dep['nome']
                    if dep['partido']:
                        nome_exibicao = f"{dep['nome']} ({dep['partido']})"
                    st.markdown(f"**{nome_exibicao}**")
                    if dep['link_perfil']:
                        st.markdown(f"[Ver perfil]({dep['link_perfil']})")

        if st.button("🔄 Atualizar lista de deputados"):
            st.cache_data.clear()
            st.rerun()

# ========== TESTE POSTGRESQL ==========
elif opcao == "Teste PostgreSQL":
    st.header("🔌 Teste de Conexão PostgreSQL")
    
    # Inicializar estado da conexão
    if 'pg_connection' not in st.session_state:
        st.session_state.pg_connection = None
    if 'pg_connected' not in st.session_state:
        st.session_state.pg_connected = False
    
    # Obter credenciais do .env
    pg_host = os.getenv('POSTGREE_HOST', 'pgsql.hetzner.welm.com.br')
    pg_port = os.getenv('POSTGREE_PORT', '443')
    pg_user = os.getenv('POSTGREE_USER', 'marcio')
    pg_password = os.getenv('POSTGREE_PASSWORD', '')
    
    # Exibir informações de conexão
    st.subheader("Configurações de Conexão")
    col1, col2 = st.columns(2)
    with col1:
        st.text_input("Host", value=pg_host, disabled=True)
        st.text_input("Usuário", value=pg_user, disabled=True)
    with col2:
        st.text_input("Porta", value=pg_port, disabled=True)
        st.text_input("Password", value="*" * len(pg_password), type="password", disabled=True)
    
    st.markdown("---")
    
    # Status visual de conexão
    st.subheader("Status da Conexão")
    
    if st.session_state.pg_connected:
        st.success("🟢 **CONECTADO** - A conexão com o PostgreSQL está ativa!")
    else:
        st.error("🔴 **DESCONECTADO** - Não há conexão ativa com o PostgreSQL.")
    
    st.markdown("---")
    
    # Botões de ação
    col1, col2, col3 = st.columns([1, 1, 3])
    
    with col1:
        if st.button("🔌 Conectar", disabled=st.session_state.pg_connected):
            with st.spinner("Conectando ao PostgreSQL..."):
                try:
                    # Tentar conectar ao PostgreSQL
                    connection = psycopg2.connect(
                        host=pg_host,
                        port=int(pg_port),
                        user=pg_user,
                        password=pg_password,
                        database='banco',  # banco específico
                        connect_timeout=10
                    )
                    
                    st.session_state.pg_connection = connection
                    st.session_state.pg_connected = True
                    st.success("✅ Conexão estabelecida com sucesso!")
                    
                    # Testar a conexão executando uma query simples
                    cursor = connection.cursor()
                    cursor.execute("SELECT version();")
                    version = cursor.fetchone()
                    cursor.close()
                    
                    st.info(f"**Versão do PostgreSQL:** {version[0]}")
                    st.rerun()
                    
                except OperationalError as e:
                    st.error(f"❌ Erro ao conectar: {str(e)}")
                    st.session_state.pg_connected = False
                    st.session_state.pg_connection = None
                except Exception as e:
                    st.error(f"❌ Erro inesperado: {str(e)}")
                    st.session_state.pg_connected = False
                    st.session_state.pg_connection = None
    
    with col2:
        if st.button("🔌 Desconectar", disabled=not st.session_state.pg_connected):
            try:
                if st.session_state.pg_connection:
                    st.session_state.pg_connection.close()
                st.session_state.pg_connection = None
                st.session_state.pg_connected = False
                st.success("✅ Desconectado com sucesso!")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Erro ao desconectar: {str(e)}")
                st.session_state.pg_connection = None
                st.session_state.pg_connected = False
    
    # Se conectado, mostrar informações adicionais
    if st.session_state.pg_connected and st.session_state.pg_connection:
        st.markdown("---")
        st.subheader("Informações do Banco de Dados")
        
        try:
            cursor = st.session_state.pg_connection.cursor()
            
            # Listar bancos de dados
            cursor.execute("SELECT datname FROM pg_database WHERE datistemplate = false;")
            databases = cursor.fetchall()
            
            st.write("**Bancos de dados disponíveis:**")
            for db in databases:
                st.write(f"- {db[0]}")
            
            # Informações de conexão
            st.write("**Detalhes da conexão:**")
            st.write(f"- Banco atual: banco")
            st.write(f"- Status: {st.session_state.pg_connection.status}")
            st.write(f"- Server Version: {st.session_state.pg_connection.server_version}")
            
            # Listar tabelas do schema 'doutorado'
            st.markdown("---")
            st.write("**Tabelas do schema 'doutorado':**")
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'doutorado' 
                AND table_type = 'BASE TABLE'
                ORDER BY table_name;
            """)
            tables = cursor.fetchall()
            
            if tables:
                for table in tables:
                    st.write(f"- {table[0]}")
            else:
                st.info("Nenhuma tabela encontrada no schema 'doutorado'.")
            
            cursor.close()
            
        except Exception as e:
            st.error(f"Erro ao buscar informações: {str(e)}")

# Footer
st.markdown("---")
st.markdown(
    """
    **Fonte dos Dados:** [Dados Abertos - Câmara dos Deputados](https://dadosabertos.camara.leg.br/)
    
    **Documentação da API:** [https://dadosabertos.camara.leg.br/swagger/api.html](https://dadosabertos.camara.leg.br/swagger/api.html)
    """
)

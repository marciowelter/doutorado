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
import re
import subprocess
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse, urlunparse

# Forçar recarga do módulo api_client
if 'api_client' in sys.modules:
    importlib.reload(sys.modules['api_client'])

from api_client import CamaraAPIClient
from datetime import datetime, timedelta
import alesc_diario_plenario_scraper as _diario_scraper
import alesc_noticias_deputados_scraper as _noticias_deputados_scraper
import alesc_noticias_agenciaal_scraper as _noticias_agenciaal_scraper

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

    @st.cache_data(ttl=3600)
    def contar_atas_alesc():
        try:
            conn = conectar_postgresql_banco_alesc()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM doutorado.atas_alesc")
            total = cur.fetchone()[0]
            cur.close()
            conn.close()
            return total
        except Exception:
            return 0

    @st.cache_data(ttl=3600)
    def carregar_atas_alesc(pagina: int, itens_por_pagina: int):
        try:
            offset = (pagina - 1) * itens_por_pagina

            conn = conectar_postgresql_banco_alesc()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                    data_evento,
                    local_evento,
                    tipo_evento,
                    ementa,
                    conteudo_ata,
                    url_visualizacao,
                    url_download,
                    data_importacao
                FROM doutorado.atas_alesc
                ORDER BY data_evento DESC NULLS LAST, data_importacao DESC NULLS LAST
                LIMIT %s OFFSET %s
                """,
                (itens_por_pagina, offset),
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()

            atas = []
            for r in rows:
                atas.append(
                    {
                        'data_evento': r[0].strftime('%d/%m/%Y') if r[0] else None,
                        'local_evento': r[1],
                        'tipo_evento': r[2],
                        'ementa': r[3],
                        'conteudo_ata': r[4],
                        'url_visualizacao': r[5],
                        'url_download': r[6],
                        'data_importacao': r[7].strftime('%d/%m/%Y %H:%M:%S') if r[7] else None,
                    }
                )
            return atas
        except Exception:
            return []

    def _montar_filtro_atas_plenarias(
        filtro_diario: str,
        filtro_numero_ata: str,
        filtro_sessao_legislativa: int | None,
        filtro_tipo_sessao: str | None,
    ):
        where = []
        params = []

        if filtro_diario:
            where.append("CAST(diario_numero AS TEXT) LIKE %s")
            params.append(f"%{filtro_diario}%")

        if filtro_numero_ata:
            where.append("CAST(numero_ata AS TEXT) LIKE %s")
            params.append(f"%{filtro_numero_ata}%")

        if filtro_sessao_legislativa is not None:
            where.append("sessao_legislativa = %s")
            params.append(filtro_sessao_legislativa)

        if filtro_tipo_sessao:
            where.append("tipo_sessao = %s")
            params.append(filtro_tipo_sessao)

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        return where_sql, params

    @st.cache_data(ttl=3600)
    def carregar_sessoes_legislativas_plenarias_alesc():
        try:
            conn = conectar_postgresql_banco_alesc()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT DISTINCT sessao_legislativa
                FROM doutorado.atas_sessoes_plenarias_alesc
                WHERE sessao_legislativa IS NOT NULL
                ORDER BY sessao_legislativa DESC
                """
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()
            return [r[0] for r in rows]
        except Exception:
            return []

    @st.cache_data(ttl=3600)
    def carregar_tipos_sessao_plenarias_alesc():
        try:
            conn = conectar_postgresql_banco_alesc()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT DISTINCT tipo_sessao
                FROM doutorado.atas_sessoes_plenarias_alesc
                WHERE tipo_sessao IS NOT NULL
                ORDER BY tipo_sessao ASC
                """
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()
            return [r[0] for r in rows]
        except Exception:
            return []

    @st.cache_data(ttl=3600)
    def contar_atas_plenarias_alesc(
        filtro_diario: str = '',
        filtro_numero_ata: str = '',
        filtro_sessao_legislativa: int | None = None,
        filtro_tipo_sessao: str | None = None,
    ):
        try:
            where_sql, params = _montar_filtro_atas_plenarias(
                filtro_diario,
                filtro_numero_ata,
                filtro_sessao_legislativa,
                filtro_tipo_sessao,
            )

            conn = conectar_postgresql_banco_alesc()
            cur = conn.cursor()
            cur.execute(
                f"SELECT COUNT(*) FROM doutorado.atas_sessoes_plenarias_alesc {where_sql}",
                params,
            )
            total = cur.fetchone()[0]
            cur.close()
            conn.close()
            return total
        except Exception:
            return 0

    @st.cache_data(ttl=3600)
    def carregar_atas_plenarias_alesc(
        pagina: int,
        itens_por_pagina: int,
        filtro_diario: str = '',
        filtro_numero_ata: str = '',
        filtro_sessao_legislativa: int | None = None,
        filtro_tipo_sessao: str | None = None,
    ):
        try:
            where_sql, params = _montar_filtro_atas_plenarias(
                filtro_diario,
                filtro_numero_ata,
                filtro_sessao_legislativa,
                filtro_tipo_sessao,
            )
            offset = (pagina - 1) * itens_por_pagina

            conn = conectar_postgresql_banco_alesc()
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT
                    diario_numero,
                    diario_data_publicacao,
                    diario_url_download,
                    numero_ata,
                    sessao_legislativa,
                    legislatura,
                    titulo_ata,
                    conteudo_ata,
                    tipo_sessao,
                    data_importacao
                FROM doutorado.atas_sessoes_plenarias_alesc
                {where_sql}
                ORDER BY diario_numero DESC, numero_ata DESC, data_importacao DESC NULLS LAST
                LIMIT %s OFFSET %s
                """,
                params + [itens_por_pagina, offset],
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()

            atas = []
            for r in rows:
                atas.append(
                    {
                        'diario_numero': r[0],
                        'diario_data_publicacao': r[1].strftime('%d/%m/%Y') if r[1] else None,
                        'diario_url_download': r[2],
                        'numero_ata': r[3],
                        'sessao_legislativa': r[4],
                        'legislatura': r[5],
                        'titulo_ata': r[6],
                        'conteudo_ata': r[7],
                        'tipo_sessao': r[8],
                        'data_importacao': r[9].strftime('%d/%m/%Y %H:%M:%S') if r[9] else None,
                    }
                )
            return atas
        except Exception:
            return []

    def _montar_filtro_noticias_deputados_alesc(
        filtro_titulo: str,
        filtro_deputado_id: int | None,
        filtro_data_inicio,
        filtro_data_fim,
    ):
        where = []
        params = []

        if filtro_titulo:
            where.append("n.titulo ILIKE %s")
            params.append(f"%{filtro_titulo}%")

        if filtro_deputado_id is not None:
            where.append("n.deputado_id = %s")
            params.append(filtro_deputado_id)

        if filtro_data_inicio is not None:
            where.append("n.data_materia >= %s")
            params.append(filtro_data_inicio)

        if filtro_data_fim is not None:
            where.append("n.data_materia <= %s")
            params.append(filtro_data_fim)

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        return where_sql, params

    @st.cache_data(ttl=3600)
    def carregar_filtro_deputados_noticias_alesc():
        try:
            conn = conectar_postgresql_banco_alesc()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT DISTINCT d.id, d.nome, d.partido
                FROM doutorado.noticias_deputados_alesc n
                JOIN doutorado.deputados_alesc d ON d.id = n.deputado_id
                ORDER BY d.nome
                """
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()
            return [
                {
                    'id': r[0],
                    'nome': r[1],
                    'partido': r[2],
                }
                for r in rows
            ]
        except Exception:
            return []

    @st.cache_data(ttl=3600)
    def contar_noticias_deputados_alesc(
        filtro_titulo: str = '',
        filtro_deputado_id: int | None = None,
        filtro_data_inicio=None,
        filtro_data_fim=None,
    ):
        try:
            where_sql, params = _montar_filtro_noticias_deputados_alesc(
                filtro_titulo,
                filtro_deputado_id,
                filtro_data_inicio,
                filtro_data_fim,
            )

            conn = conectar_postgresql_banco_alesc()
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM doutorado.noticias_deputados_alesc n
                LEFT JOIN doutorado.deputados_alesc d ON d.id = n.deputado_id
                {where_sql}
                """,
                params,
            )
            total = cur.fetchone()[0]
            cur.close()
            conn.close()
            return total
        except Exception:
            return 0

    @st.cache_data(ttl=3600)
    def carregar_noticias_deputados_alesc(
        pagina: int,
        itens_por_pagina: int,
        filtro_titulo: str = '',
        filtro_deputado_id: int | None = None,
        filtro_data_inicio=None,
        filtro_data_fim=None,
    ):
        try:
            where_sql, params = _montar_filtro_noticias_deputados_alesc(
                filtro_titulo,
                filtro_deputado_id,
                filtro_data_inicio,
                filtro_data_fim,
            )
            offset = (pagina - 1) * itens_por_pagina

            conn = conectar_postgresql_banco_alesc()
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT
                    n.id,
                    n.data_materia,
                    n.titulo,
                    n.url_materia,
                    n.conteudo_noticia,
                    n.data_importacao,
                    d.nome AS deputado_nome,
                    d.partido AS deputado_partido
                FROM doutorado.noticias_deputados_alesc n
                LEFT JOIN doutorado.deputados_alesc d ON d.id = n.deputado_id
                {where_sql}
                ORDER BY n.data_materia DESC NULLS LAST, n.id DESC
                LIMIT %s OFFSET %s
                """,
                params + [itens_por_pagina, offset],
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()

            noticias = []
            for r in rows:
                noticias.append(
                    {
                        'id': r[0],
                        'data_materia': r[1].strftime('%d/%m/%Y') if r[1] else None,
                        'titulo': r[2],
                        'url_materia': r[3],
                        'conteudo_noticia': r[4],
                        'data_importacao': r[5].strftime('%d/%m/%Y %H:%M:%S') if r[5] else None,
                        'deputado_nome': r[6],
                        'deputado_partido': r[7],
                    }
                )
            return noticias
        except Exception:
            return []

    def _extrair_estatisticas_import_noticias_alesc(log_texto: str) -> dict:
        stats = {
            'scrolls_executados': 0,
            'urls_descobertas': 0,
            'noticias_analisadas': 0,
            'noticias_inseridas': 0,
            'noticias_duplicadas': 0,
            'noticias_sem_deputado': 0,
            'falhas_extracao_materia': 0,
            'duracao_segundos': 0.0,
            'motivo_parada': '',
            'mensagens': [ln for ln in log_texto.splitlines() if ln.strip()],
        }

        metricas = {
            'scrolls_executados': r'-\s*Scrolls executados:\s*(\d+)',
            'urls_descobertas': r'-\s*URLs descobertas:\s*(\d+)',
            'noticias_analisadas': r'-\s*Noticias analisadas:\s*(\d+)',
            'noticias_inseridas': r'-\s*Inseridas:\s*(\d+)',
            'noticias_duplicadas': r'-\s*Duplicadas:\s*(\d+)',
            'noticias_sem_deputado': r'-\s*Sem vinculo de deputado:\s*(\d+)',
            'falhas_extracao_materia': r'-\s*Falhas de extracao:\s*(\d+)',
        }

        for campo, pattern in metricas.items():
            m = re.search(pattern, log_texto)
            if m:
                stats[campo] = int(m.group(1))

        m_duracao = re.search(r'-\s*Duracao \(s\):\s*([0-9]+(?:\.[0-9]+)?)', log_texto)
        if m_duracao:
            stats['duracao_segundos'] = float(m_duracao.group(1))

        m_motivo = re.search(r'-\s*Motivo de parada:\s*(.+)', log_texto)
        if m_motivo:
            stats['motivo_parada'] = m_motivo.group(1).strip()

        return stats

    def executar_importacao_noticias_deputados_alesc(
        max_duplicadas_sequenciais: int,
        max_scroll_sem_novidades: int,
    ) -> dict:
        script_path = os.path.abspath(_noticias_deputados_scraper.__file__)
        cmd = [
            sys.executable,
            script_path,
            '--max-duplicadas-sequenciais',
            str(max_duplicadas_sequenciais),
            '--max-scroll-sem-novidades',
            str(max_scroll_sem_novidades),
        ]

        proc = subprocess.run(
            cmd,
            cwd=os.path.dirname(script_path),
            capture_output=True,
            text=True,
        )

        log_texto = ((proc.stdout or '') + '\n' + (proc.stderr or '')).strip()

        if proc.returncode != 0:
            ultimas_linhas = '\n'.join(log_texto.splitlines()[-40:]) if log_texto else 'Sem detalhes no log.'
            raise RuntimeError(
                'Falha ao importar noticias dos deputados via subprocesso.\n'
                f'Codigo de saida: {proc.returncode}\n'
                f'Log:\n{ultimas_linhas}'
            )

        return _extrair_estatisticas_import_noticias_alesc(log_texto)

    def _montar_filtro_noticias_agenciaal_alesc(
        filtro_titulo: str,
        filtro_data_inicio=None,
        filtro_data_fim=None,
    ):
        where = []
        params = []

        if filtro_titulo:
            where.append("n.titulo ILIKE %s")
            params.append(f"%{filtro_titulo}%")

        if filtro_data_inicio is not None:
            where.append("n.data_noticia >= %s")
            params.append(filtro_data_inicio)

        if filtro_data_fim is not None:
            where.append("n.data_noticia <= %s")
            params.append(filtro_data_fim)

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        return where_sql, params

    @st.cache_data(ttl=3600)
    def contar_noticias_agenciaal_alesc(
        filtro_titulo: str = '',
        filtro_data_inicio=None,
        filtro_data_fim=None,
    ):
        try:
            where_sql, params = _montar_filtro_noticias_agenciaal_alesc(
                filtro_titulo,
                filtro_data_inicio,
                filtro_data_fim,
            )

            conn = conectar_postgresql_banco_alesc()
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT COUNT(*)
                FROM doutorado.noticias_agencia_al_alesc n
                {where_sql}
                """,
                params,
            )
            total = cur.fetchone()[0]
            cur.close()
            conn.close()
            return total
        except Exception:
            return 0

    @st.cache_data(ttl=3600)
    def carregar_noticias_agenciaal_alesc(
        pagina: int,
        itens_por_pagina: int,
        filtro_titulo: str = '',
        filtro_data_inicio=None,
        filtro_data_fim=None,
    ):
        try:
            where_sql, params = _montar_filtro_noticias_agenciaal_alesc(
                filtro_titulo,
                filtro_data_inicio,
                filtro_data_fim,
            )
            offset = (pagina - 1) * itens_por_pagina

            conn = conectar_postgresql_banco_alesc()
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT
                    id,
                    data_noticia,
                    titulo,
                    url_noticia,
                    conteudo_noticia,
                    data_importacao
                FROM doutorado.noticias_agencia_al_alesc n
                {where_sql}
                ORDER BY data_noticia DESC NULLS LAST, id DESC
                LIMIT %s OFFSET %s
                """,
                params + [itens_por_pagina, offset],
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()

            noticias = []
            for r in rows:
                noticias.append(
                    {
                        'id': r[0],
                        'data_noticia': r[1].strftime('%d/%m/%Y') if r[1] else None,
                        'titulo': r[2],
                        'url_noticia': r[3],
                        'conteudo_noticia': r[4],
                        'data_importacao': r[5].strftime('%d/%m/%Y %H:%M:%S') if r[5] else None,
                    }
                )
            return noticias
        except Exception:
            return []

    def _extrair_estatisticas_import_noticias_agenciaal(log_texto: str) -> dict:
        stats = {
            'scrolls_executados': 0,
            'urls_descobertas': 0,
            'noticias_analisadas': 0,
            'noticias_inseridas': 0,
            'noticias_duplicadas': 0,
            'falhas_extracao': 0,
            'duracao_segundos': 0.0,
            'motivo_parada': '',
            'mensagens': [ln for ln in log_texto.splitlines() if ln.strip()],
        }

        metricas = {
            'scrolls_executados': r'-\s*Scrolls executados:\s*(\d+)',
            'urls_descobertas': r'-\s*URLs descobertas:\s*(\d+)',
            'noticias_analisadas': r'-\s*Noticias analisadas:\s*(\d+)',
            'noticias_inseridas': r'-\s*Inseridas:\s*(\d+)',
            'noticias_duplicadas': r'-\s*Duplicadas:\s*(\d+)',
            'falhas_extracao': r'-\s*Falhas de extracao:\s*(\d+)',
        }

        for campo, pattern in metricas.items():
            m = re.search(pattern, log_texto)
            if m:
                stats[campo] = int(m.group(1))

        m_duracao = re.search(r'-\s*Duracao \(s\):\s*([0-9]+(?:\.[0-9]+)?)', log_texto)
        if m_duracao:
            stats['duracao_segundos'] = float(m_duracao.group(1))

        m_motivo = re.search(r'-\s*Motivo de parada:\s*(.+)', log_texto)
        if m_motivo:
            stats['motivo_parada'] = m_motivo.group(1).strip()

        return stats

    def executar_importacao_noticias_agenciaal_alesc(
        max_duplicadas_sequenciais: int,
        max_scroll_sem_novidades: int,
    ) -> dict:
        script_path = os.path.abspath(_noticias_agenciaal_scraper.__file__)
        cmd = [
            sys.executable,
            script_path,
            '--max-duplicadas-sequenciais',
            str(max_duplicadas_sequenciais),
            '--max-scroll-sem-novidades',
            str(max_scroll_sem_novidades),
        ]

        proc = subprocess.run(
            cmd,
            cwd=os.path.dirname(script_path),
            capture_output=True,
            text=True,
        )

        log_texto = ((proc.stdout or '') + '\n' + (proc.stderr or '')).strip()

        if proc.returncode != 0:
            ultimas_linhas = '\n'.join(log_texto.splitlines()[-40:]) if log_texto else 'Sem detalhes no log.'
            raise RuntimeError(
                'Falha ao importar noticias da Agencia AL via subprocesso.\n'
                f'Codigo de saida: {proc.returncode}\n'
                f'Log:\n{ultimas_linhas}'
            )

        return _extrair_estatisticas_import_noticias_agenciaal(log_texto)

    deputados_alesc = carregar_deputados_alesc()
    total_atas_alesc = contar_atas_alesc()
    total_atas_plenarias_geral = contar_atas_plenarias_alesc()
    sessoes_legislativas_plenarias = carregar_sessoes_legislativas_plenarias_alesc()
    tipos_sessao_plenarias = carregar_tipos_sessao_plenarias_alesc()
    total_noticias_deputados_alesc = contar_noticias_deputados_alesc()
    total_noticias_agenciaal_alesc = contar_noticias_agenciaal_alesc()
    deputados_com_noticias_alesc = carregar_filtro_deputados_noticias_alesc()

    tab_deputados_alesc, tab_atas_alesc, tab_atas_plenarias_alesc, tab_noticias_deputados_alesc, tab_noticias_agenciaal_alesc = st.tabs(
        ["👤 Deputados Estaduais", "📝 Atas", "🏛️ Atas Plenarias", "📰 Noticias Deputados", "📣 Agencia AL"]
    )

    with tab_deputados_alesc:
        if not deputados_alesc:
            st.warning(
                "Nenhum deputado cadastrado ainda. "
                "Execute o script **alesc_scraper.py** na sua maquina local para popular os dados:\n\n"
                "```bash\n"
                "python alesc_scraper.py\n"
                "```"
            )
            st.info(
                "**Por que rodar localmente?**\n\n"
                "O site www.alesc.sc.gov.br bloqueia conexoes de IPs fora do Brasil. "
                "O script deve ser executado na sua maquina (IP brasileiro) e salvara os dados no PostgreSQL."
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

        if st.button("🔄 Atualizar lista de deputados", key="atualizar_deputados_alesc"):
            st.cache_data.clear()
            st.rerun()

    with tab_atas_alesc:
        st.info("Importacao de Atas configurada para varrer todas as paginas disponiveis no portal da ALESC.")

        if total_atas_alesc == 0:
            st.warning(
                "Nenhuma ata cadastrada ainda. "
                "Execute o script local para importar todas as atas:\n\n"
                "```bash\n"
                "python alesc_atas_scraper.py\n"
                "```"
            )
            st.info(
                "O scraper acessa https://portalelegis.alesc.sc.gov.br/comissoes-permanentes/atas, "
                "percorre todas as paginas (hoje 258), baixa anexos PDF/DOC/DOCX e extrai o conteudo das atas. "
                "A deduplicacao e feita por url de download para evitar registros repetidos em reexecucoes."
            )
        else:
            st.subheader(f"📝 Atas importadas ({total_atas_alesc} registro(s))")

            col_pag1, col_pag2, col_pag3 = st.columns([1, 1, 2])
            with col_pag1:
                itens_por_pagina_atas = st.selectbox(
                    'Itens por pagina',
                    [20, 50, 100],
                    index=1,
                    key='itens_por_pagina_atas_alesc',
                )

            total_paginas_atas = max(1, (total_atas_alesc + itens_por_pagina_atas - 1) // itens_por_pagina_atas)

            with col_pag2:
                pagina_atas = int(
                    st.number_input(
                        'Pagina',
                        min_value=1,
                        max_value=total_paginas_atas,
                        value=min(st.session_state.get('pagina_atas_alesc', 1), total_paginas_atas),
                        step=1,
                        key='pagina_atas_alesc',
                    )
                )

            inicio_atas = ((pagina_atas - 1) * itens_por_pagina_atas) + 1
            fim_atas = min(pagina_atas * itens_por_pagina_atas, total_atas_alesc)
            with col_pag3:
                st.caption(
                    f"Exibindo {inicio_atas}-{fim_atas} de {total_atas_alesc} registros "
                    f"(pagina {pagina_atas} de {total_paginas_atas})."
                )

            atas_alesc = carregar_atas_alesc(pagina_atas, itens_por_pagina_atas)

            df_atas = pd.DataFrame(
                [
                    {
                        'Data do Evento': a['data_evento'],
                        'Local do Evento': a['local_evento'],
                        'Tipo de Evento': a['tipo_evento'],
                        'Ementa': (a['ementa'][:140] + '...') if a['ementa'] and len(a['ementa']) > 140 else a['ementa'],
                        'Visualizacao': a['url_visualizacao'],
                        'Download PDF': a['url_download'],
                        'Importado em': a['data_importacao'],
                    }
                    for a in atas_alesc
                ]
            )

            st.dataframe(
                df_atas,
                hide_index=True,
                width='stretch',
                column_config={
                    'Visualizacao': st.column_config.LinkColumn('Visualizacao', display_text='Abrir'),
                    'Download PDF': st.column_config.LinkColumn('Download PDF', display_text='Baixar'),
                },
            )

            primeira_ata = atas_alesc[0]
            st.markdown("### Primeiro registro da pagina atual")

            col_a, col_b = st.columns(2)
            with col_a:
                st.write(f"**Data do evento:** {primeira_ata.get('data_evento') or 'Nao informado'}")
                st.write(f"**Local do evento:** {primeira_ata.get('local_evento') or 'Nao informado'}")
                st.write(f"**Tipo de evento:** {primeira_ata.get('tipo_evento') or 'Nao informado'}")
            with col_b:
                st.write(f"**Ementa:** {primeira_ata.get('ementa') or 'Nao informado'}")
                if primeira_ata.get('url_visualizacao'):
                    st.markdown(f"[Visualizar no portal]({primeira_ata['url_visualizacao']})")
                if primeira_ata.get('url_download'):
                    st.markdown(f"[Download do PDF]({primeira_ata['url_download']})")

            st.text_area(
                'Conteudo da ata',
                value=primeira_ata.get('conteudo_ata') or 'Conteudo nao extraido.',
                height=380,
            )

        if st.button("🔄 Atualizar lista de atas", key="atualizar_atas_alesc"):
            st.cache_data.clear()
            st.rerun()

    with tab_atas_plenarias_alesc:
        st.info(
            "Importacao de Atas Plenarias configurada para ler o Diario da ALESC "
            "e importar apenas registros da 20a legislatura."
        )

        if total_atas_plenarias_geral == 0:
            st.warning(
                "Nenhuma ata plenaria cadastrada ainda. "
                "Execute o script local para importar os diarios:\n\n"
                "```bash\n"
                "python alesc_diario_plenario_scraper.py --max-sem-ata-sequencial 200\n"
                "```"
            )
            st.info(
                "O scraper percorre os diarios do mais recente para o mais antigo, "
                "analisa apenas a secao de Atas de Sessoes Plenarias, importa a 20a legislatura "
                "e para ao encontrar a 19a legislatura."
            )
        else:
            st.subheader(f"🏛️ Atas Plenarias importadas ({total_atas_plenarias_geral} registro(s))")

            col_f1, col_f2, col_f3, col_f4 = st.columns(4)
            with col_f1:
                filtro_diario = st.text_input(
                    'Filtrar por diario',
                    placeholder='Ex: 9004',
                    key='filtro_diario_atas_plenarias',
                ).strip()
            with col_f2:
                filtro_numero_ata = st.text_input(
                    'Filtrar por numero da ata',
                    placeholder='Ex: 7',
                    key='filtro_numero_ata_atas_plenarias',
                ).strip()
            with col_f3:
                filtro_sessao_legislativa = st.selectbox(
                    'Filtrar por sessao legislativa',
                    [None] + sessoes_legislativas_plenarias,
                    format_func=lambda valor: 'Todas' if valor is None else str(valor),
                    key='filtro_sessao_legislativa_atas_plenarias',
                )
            with col_f4:
                filtro_tipo_sessao = st.selectbox(
                    'Filtrar por tipo de sessao',
                    [None] + tipos_sessao_plenarias,
                    format_func=lambda valor: 'Todas' if valor is None else str(valor),
                    key='filtro_tipo_sessao_atas_plenarias',
                )

            total_atas_plenarias_filtradas = contar_atas_plenarias_alesc(
                filtro_diario,
                filtro_numero_ata,
                filtro_sessao_legislativa,
                filtro_tipo_sessao,
            )

            col_pag1, col_pag2, col_pag3 = st.columns([1, 1, 2])
            with col_pag1:
                itens_por_pagina_plenarias = st.selectbox(
                    'Itens por pagina',
                    [20, 50, 100],
                    index=1,
                    key='itens_por_pagina_atas_plenarias',
                )

            total_paginas_plenarias = max(
                1,
                (total_atas_plenarias_filtradas + itens_por_pagina_plenarias - 1) // itens_por_pagina_plenarias,
            )

            with col_pag2:
                pagina_plenarias = int(
                    st.number_input(
                        'Pagina',
                        min_value=1,
                        max_value=total_paginas_plenarias,
                        value=min(
                            st.session_state.get('pagina_atas_plenarias', 1),
                            total_paginas_plenarias,
                        ),
                        step=1,
                        key='pagina_atas_plenarias',
                    )
                )

            if total_atas_plenarias_filtradas > 0:
                inicio_plenarias = ((pagina_plenarias - 1) * itens_por_pagina_plenarias) + 1
                fim_plenarias = min(
                    pagina_plenarias * itens_por_pagina_plenarias,
                    total_atas_plenarias_filtradas,
                )
            else:
                inicio_plenarias = 0
                fim_plenarias = 0

            with col_pag3:
                st.caption(
                    f"Exibindo {inicio_plenarias}-{fim_plenarias} de {total_atas_plenarias_filtradas} registros "
                    f"(pagina {pagina_plenarias} de {total_paginas_plenarias})."
                )

            col_m1, col_m2, col_m3 = st.columns(3)
            with col_m1:
                st.metric('Total geral', total_atas_plenarias_geral)
            with col_m2:
                st.metric('Total filtrado', total_atas_plenarias_filtradas)
            with col_m3:
                st.metric('Pagina atual', f'{pagina_plenarias}/{total_paginas_plenarias}')

            if total_atas_plenarias_filtradas == 0:
                st.warning('Nenhuma ata plenaria encontrada com os filtros informados.')
            else:
                atas_plenarias_pagina = carregar_atas_plenarias_alesc(
                    pagina_plenarias,
                    itens_por_pagina_plenarias,
                    filtro_diario,
                    filtro_numero_ata,
                    filtro_sessao_legislativa,
                    filtro_tipo_sessao,
                )

                st.markdown(
                    f"*Exibindo {len(atas_plenarias_pagina)} registro(s) na pagina atual com os filtros aplicados.*"
                )

                df_atas_plenarias = pd.DataFrame(
                    [
                        {
                            'Diario': a['diario_numero'],
                            'Data Publicacao': a['diario_data_publicacao'],
                            'Ata': a['numero_ata'],
                            'Sessao Legislativa': a['sessao_legislativa'],
                            'Legislatura': a['legislatura'],
                            'Tipo Sessao': a['tipo_sessao'],
                            'Titulo': (a['titulo_ata'][:160] + '...') if a['titulo_ata'] and len(a['titulo_ata']) > 160 else a['titulo_ata'],
                            'Download Diario': a['diario_url_download'],
                            'Importado em': a['data_importacao'],
                        }
                        for a in atas_plenarias_pagina
                    ]
                )

                st.dataframe(
                    df_atas_plenarias,
                    hide_index=True,
                    width='stretch',
                    column_config={
                        'Download Diario': st.column_config.LinkColumn('Download Diario', display_text='Baixar'),
                    },
                )

                primeira_ata_plenaria = atas_plenarias_pagina[0]
                st.markdown("### Primeiro registro da pagina atual")

                col_p1, col_p2 = st.columns(2)
                with col_p1:
                    st.write(f"**Diario:** {primeira_ata_plenaria.get('diario_numero') or 'Nao informado'}")
                    st.write(
                        f"**Data de publicacao:** {primeira_ata_plenaria.get('diario_data_publicacao') or 'Nao informado'}"
                    )
                    st.write(f"**Numero da ata:** {primeira_ata_plenaria.get('numero_ata') or 'Nao informado'}")
                    st.write(
                        f"**Sessao legislativa:** {primeira_ata_plenaria.get('sessao_legislativa') or 'Nao informado'}"
                    )
                with col_p2:
                    st.write(f"**Legislatura:** {primeira_ata_plenaria.get('legislatura') or 'Nao informado'}")
                    st.write(f"**Tipo de sessao:** {primeira_ata_plenaria.get('tipo_sessao') or 'Nao informado'}")
                    st.write(f"**Titulo:** {primeira_ata_plenaria.get('titulo_ata') or 'Nao informado'}")
                    if primeira_ata_plenaria.get('diario_url_download'):
                        st.markdown(f"[Download do diario]({primeira_ata_plenaria['diario_url_download']})")

                st.text_area(
                    'Conteudo da ata plenaria',
                    value=primeira_ata_plenaria.get('conteudo_ata') or 'Conteudo nao extraido.',
                    height=380,
                )

        if st.button("🔄 Atualizar lista de atas plenarias", key="atualizar_atas_plenarias_alesc"):
            st.cache_data.clear()
            st.rerun()

        st.markdown("---")
        st.subheader("🔍 Varredura de Diários - Importar / Atualizar")
        st.caption(
            "Informe uma faixa de números de diário para processar. "
            "Atas novas serão inseridas; atas já existentes serão substituídas "
            "apenas se o novo diário tiver número maior (publicação mais recente). "
            "Use para capturar os diários gerados diariamente sem precisar rodar o scraper completo."
        )

        col_v1, col_v2, col_v3 = st.columns([2, 2, 3])
        with col_v1:
            varredura_inicio = st.number_input(
                "Diário início",
                min_value=1,
                value=st.session_state.get('varredura_diario_inicio', 9000),
                step=1,
                key='varredura_diario_inicio',
            )
        with col_v2:
            varredura_fim = st.number_input(
                "Diário fim",
                min_value=1,
                value=st.session_state.get('varredura_diario_fim', 9100),
                step=1,
                key='varredura_diario_fim',
            )
        with col_v3:
            st.write("")
            st.write("")
            iniciar_varredura = st.button(
                "🔍 Iniciar Varredura",
                key="btn_varredura_diarios",
                use_container_width=True,
            )

        if iniciar_varredura:
            d_ini = int(varredura_inicio)
            d_fim = int(varredura_fim)
            if d_ini > d_fim:
                st.error("O diário início deve ser menor ou igual ao diário fim.")
            else:
                with st.spinner(f"Varrendo diários {d_ini} a {d_fim}... (pode levar alguns minutos)"):
                    try:
                        resultado = _diario_scraper.importar_atas_faixa_diarios(
                            diario_inicio=d_ini,
                            diario_fim=d_fim,
                        )
                        st.session_state['varredura_resultado'] = resultado
                        if resultado['atas_inseridas'] + resultado['atas_atualizadas'] > 0:
                            st.cache_data.clear()
                            st.rerun()
                    except Exception as exc:
                        st.session_state['varredura_resultado'] = {'erro': str(exc)}

        if 'varredura_resultado' in st.session_state:
            res = st.session_state['varredura_resultado']
            if 'erro' in res:
                st.error(f"Erro durante a varredura: {res['erro']}")
            else:
                total_mod = res['atas_inseridas'] + res['atas_atualizadas']
                if total_mod > 0:
                    st.success(
                        f"✅ Varredura concluída: {res['diarios_processados']} diário(s) processado(s) — "
                        f"{res['atas_inseridas']} ata(s) inserida(s), "
                        f"{res['atas_atualizadas']} ata(s) atualizada(s), "
                        f"{res['atas_duplicadas']} já existente(s) sem alteração."
                    )
                else:
                    st.info(
                        f"Varredura concluída: {res['diarios_processados']} diário(s) processado(s). "
                        "Nenhuma ata nova ou atualização encontrada."
                    )
                if res.get('mensagens'):
                    with st.expander("📋 Log da varredura"):
                        st.text('\n'.join(res['mensagens']))

    with tab_noticias_deputados_alesc:
        st.info(
            "Importacao de noticias dos deputados com scroll dinamico no portal da ALESC, "
            "deduplicacao por URL e parada automatica apos 20 duplicadas consecutivas (configuravel)."
        )

        st.markdown("### 🔄 Importar noticias")
        col_i1, col_i2, col_i3 = st.columns([2, 2, 3])
        with col_i1:
            max_duplicadas_seq = st.number_input(
                'Parada por duplicadas consecutivas',
                min_value=1,
                value=20,
                step=1,
                key='max_duplicadas_noticias_dep',
            )
        with col_i2:
            max_scroll_sem_novidade = st.number_input(
                'Parada por scroll sem novidades',
                min_value=1,
                value=8,
                step=1,
                key='max_scroll_sem_novidade_noticias_dep',
            )
        with col_i3:
            st.write('')
            st.write('')
            importar_noticias = st.button(
                '🔄 Importar noticias dos deputados',
                key='importar_noticias_deputados_alesc',
                use_container_width=True,
            )

        if importar_noticias:
            with st.spinner('Importando noticias dos deputados... isso pode levar alguns minutos.'):
                try:
                    resultado_import = executar_importacao_noticias_deputados_alesc(
                        max_duplicadas_sequenciais=int(max_duplicadas_seq),
                        max_scroll_sem_novidades=int(max_scroll_sem_novidade),
                    )
                    st.session_state['import_noticias_deputados_resultado'] = resultado_import
                    st.cache_data.clear()
                    st.rerun()
                except Exception as exc:
                    st.session_state['import_noticias_deputados_resultado'] = {'erro': str(exc)}

        if 'import_noticias_deputados_resultado' in st.session_state:
            resumo_import = st.session_state['import_noticias_deputados_resultado']
            if 'erro' in resumo_import:
                st.error(f"Erro na importacao de noticias: {resumo_import['erro']}")
            else:
                st.success(
                    f"Importacao concluida: {resumo_import['noticias_inseridas']} inserida(s), "
                    f"{resumo_import['noticias_duplicadas']} duplicada(s), "
                    f"{resumo_import['noticias_sem_deputado']} sem vinculo de deputado, "
                    f"{resumo_import['falhas_extracao_materia']} falha(s)."
                )

                col_s1, col_s2, col_s3, col_s4 = st.columns(4)
                with col_s1:
                    st.metric('URLs descobertas', resumo_import.get('urls_descobertas', 0))
                with col_s2:
                    st.metric('Noticias analisadas', resumo_import.get('noticias_analisadas', 0))
                with col_s3:
                    st.metric('Inseridas', resumo_import.get('noticias_inseridas', 0))
                with col_s4:
                    st.metric('Duracao (s)', resumo_import.get('duracao_segundos', 0))

                if resumo_import.get('motivo_parada'):
                    st.caption(f"Motivo de parada: {resumo_import['motivo_parada']}")

                if resumo_import.get('mensagens'):
                    with st.expander('📋 Log da importacao'):
                        st.text('\n'.join(resumo_import['mensagens']))

        st.markdown('---')

        if total_noticias_deputados_alesc == 0:
            st.warning(
                "Nenhuma noticia de deputado importada ainda. "
                "Use o botao acima para iniciar a primeira carga."
            )
            st.info(
                "Fonte: https://www.alesc.sc.gov.br/deputados/noticias/. "
                "A importacao abre as materias para extrair o conteudo integral e "
                "evita duplicidade pela URL da materia."
            )
        else:
            st.subheader(f"📰 Noticias importadas ({total_noticias_deputados_alesc} registro(s))")

            mapa_deputados_noticias = {
                dep['id']: (
                    f"{dep['nome']} ({dep['partido']})"
                    if dep.get('partido')
                    else dep['nome']
                )
                for dep in deputados_com_noticias_alesc
            }

            col_f1, col_f2 = st.columns(2)
            with col_f1:
                filtro_titulo_noticia = st.text_input(
                    'Filtrar por titulo',
                    placeholder='Ex: educacao, saude, mobilidade...',
                    key='filtro_titulo_noticias_dep',
                ).strip()
            with col_f2:
                filtro_deputado_id = st.selectbox(
                    'Filtrar por deputado',
                    [None] + list(mapa_deputados_noticias.keys()),
                    format_func=lambda valor: 'Todos' if valor is None else mapa_deputados_noticias.get(valor, str(valor)),
                    key='filtro_deputado_noticias_dep',
                )

            total_noticias_filtradas = contar_noticias_deputados_alesc(
                filtro_titulo=filtro_titulo_noticia,
                filtro_deputado_id=filtro_deputado_id,
            )

            col_p1, col_p2, col_p3 = st.columns([1, 1, 2])
            with col_p1:
                itens_por_pagina_noticias = st.selectbox(
                    'Itens por pagina',
                    [20, 50, 100],
                    index=1,
                    key='itens_por_pagina_noticias_dep',
                )

            total_paginas_noticias = max(
                1,
                (total_noticias_filtradas + itens_por_pagina_noticias - 1) // itens_por_pagina_noticias,
            )

            with col_p2:
                pagina_noticias = int(
                    st.number_input(
                        'Pagina',
                        min_value=1,
                        max_value=total_paginas_noticias,
                        value=min(st.session_state.get('pagina_noticias_dep', 1), total_paginas_noticias),
                        step=1,
                        key='pagina_noticias_dep',
                    )
                )

            if total_noticias_filtradas > 0:
                inicio_noticias = ((pagina_noticias - 1) * itens_por_pagina_noticias) + 1
                fim_noticias = min(pagina_noticias * itens_por_pagina_noticias, total_noticias_filtradas)
            else:
                inicio_noticias = 0
                fim_noticias = 0

            with col_p3:
                st.caption(
                    f"Exibindo {inicio_noticias}-{fim_noticias} de {total_noticias_filtradas} registros "
                    f"(pagina {pagina_noticias} de {total_paginas_noticias})."
                )

            if total_noticias_filtradas == 0:
                st.warning('Nenhuma noticia encontrada com os filtros informados.')
            else:
                noticias_pagina = carregar_noticias_deputados_alesc(
                    pagina=pagina_noticias,
                    itens_por_pagina=itens_por_pagina_noticias,
                    filtro_titulo=filtro_titulo_noticia,
                    filtro_deputado_id=filtro_deputado_id,
                )

                df_noticias = pd.DataFrame(
                    [
                        {
                            'Data': n['data_materia'],
                            'Deputado': (
                                f"{n['deputado_nome']} ({n['deputado_partido']})"
                                if n.get('deputado_nome') and n.get('deputado_partido')
                                else (n.get('deputado_nome') or 'Nao identificado')
                            ),
                            'Titulo': (n['titulo'][:180] + '...') if n['titulo'] and len(n['titulo']) > 180 else n['titulo'],
                            'Materia': n['url_materia'],
                            'Importado em': n['data_importacao'],
                        }
                        for n in noticias_pagina
                    ]
                )

                st.dataframe(
                    df_noticias,
                    hide_index=True,
                    width='stretch',
                    column_config={
                        'Materia': st.column_config.LinkColumn('Materia', display_text='Abrir'),
                    },
                )

                primeira_noticia = noticias_pagina[0]
                st.markdown('### Primeiro registro da pagina atual')
                st.write(f"**Data da materia:** {primeira_noticia.get('data_materia') or 'Nao informado'}")
                st.write(
                    "**Deputado:** "
                    + (
                        f"{primeira_noticia.get('deputado_nome')} ({primeira_noticia.get('deputado_partido')})"
                        if primeira_noticia.get('deputado_nome') and primeira_noticia.get('deputado_partido')
                        else (primeira_noticia.get('deputado_nome') or 'Nao identificado')
                    )
                )
                st.write(f"**Titulo:** {primeira_noticia.get('titulo') or 'Nao informado'}")
                if primeira_noticia.get('url_materia'):
                    st.markdown(f"[Abrir materia completa]({primeira_noticia['url_materia']})")

                st.text_area(
                    'Conteudo integral da noticia',
                    value=primeira_noticia.get('conteudo_noticia') or 'Conteudo nao extraido.',
                    height=320,
                )

        if st.button('🔄 Atualizar lista de noticias', key='atualizar_noticias_deputados_alesc'):
            st.cache_data.clear()
            st.rerun()

    with tab_noticias_agenciaal_alesc:
        st.info(
            "Importacao de noticias da Agencia AL com scroll dinamico, "
            "deduplicacao por URL e parada automatica apos 20 duplicadas consecutivas (configuravel)."
        )

        st.markdown("### 🔄 Importar noticias da Agencia AL")
        col_a1, col_a2, col_a3 = st.columns([2, 2, 3])
        with col_a1:
            max_duplicadas_seq_ag = st.number_input(
                'Parada por duplicadas consecutivas',
                min_value=1,
                value=20,
                step=1,
                key='max_duplicadas_noticias_agenciaal',
            )
        with col_a2:
            max_scroll_sem_novidade_ag = st.number_input(
                'Parada por scroll sem novidades',
                min_value=1,
                value=8,
                step=1,
                key='max_scroll_sem_novidade_noticias_agenciaal',
            )
        with col_a3:
            st.write('')
            st.write('')
            importar_noticias_agencia = st.button(
                '🔄 Importar noticias da Agencia AL',
                key='importar_noticias_agenciaal_alesc',
                use_container_width=True,
            )

        if importar_noticias_agencia:
            with st.spinner('Importando noticias da Agencia AL... isso pode levar alguns minutos.'):
                try:
                    resultado_import_ag = executar_importacao_noticias_agenciaal_alesc(
                        max_duplicadas_sequenciais=int(max_duplicadas_seq_ag),
                        max_scroll_sem_novidades=int(max_scroll_sem_novidade_ag),
                    )
                    st.session_state['import_noticias_agenciaal_resultado'] = resultado_import_ag
                    st.cache_data.clear()
                    st.rerun()
                except Exception as exc:
                    st.session_state['import_noticias_agenciaal_resultado'] = {'erro': str(exc)}

        if 'import_noticias_agenciaal_resultado' in st.session_state:
            resumo_import_ag = st.session_state['import_noticias_agenciaal_resultado']
            if 'erro' in resumo_import_ag:
                st.error(f"Erro na importacao de noticias da Agencia AL: {resumo_import_ag['erro']}")
            else:
                st.success(
                    f"Importacao concluida: {resumo_import_ag['noticias_inseridas']} inserida(s), "
                    f"{resumo_import_ag['noticias_duplicadas']} duplicada(s), "
                    f"{resumo_import_ag['falhas_extracao']} falha(s)."
                )

                col_ag_s1, col_ag_s2, col_ag_s3, col_ag_s4 = st.columns(4)
                with col_ag_s1:
                    st.metric('URLs descobertas', resumo_import_ag.get('urls_descobertas', 0))
                with col_ag_s2:
                    st.metric('Noticias analisadas', resumo_import_ag.get('noticias_analisadas', 0))
                with col_ag_s3:
                    st.metric('Inseridas', resumo_import_ag.get('noticias_inseridas', 0))
                with col_ag_s4:
                    st.metric('Duracao (s)', resumo_import_ag.get('duracao_segundos', 0))

                if resumo_import_ag.get('motivo_parada'):
                    st.caption(f"Motivo de parada: {resumo_import_ag['motivo_parada']}")

                if resumo_import_ag.get('mensagens'):
                    with st.expander('📋 Log da importacao'):
                        st.text('\n'.join(resumo_import_ag['mensagens']))

        st.markdown('---')

        if total_noticias_agenciaal_alesc == 0:
            st.warning(
                "Nenhuma noticia da Agencia AL importada ainda. "
                "Use o botao acima para iniciar a primeira carga."
            )
            st.info(
                "Fonte: https://www.alesc.sc.gov.br/agenciaal/. "
                "A importacao abre as materias para extrair o conteudo integral e "
                "evita duplicidade pela URL da noticia."
            )
        else:
            st.subheader(f"📣 Noticias da Agencia AL ({total_noticias_agenciaal_alesc} registro(s))")

            col_fag1, col_fag2, col_fag3 = st.columns(3)
            with col_fag1:
                filtro_titulo_noticia_agencia = st.text_input(
                    'Filtrar por titulo',
                    placeholder='Ex: plenario, comissao, projeto...',
                    key='filtro_titulo_noticias_agenciaal',
                ).strip()
            with col_fag2:
                usar_data_inicio_agencia = st.checkbox(
                    'Usar data inicial',
                    key='usar_data_inicio_noticias_agenciaal',
                )
                if usar_data_inicio_agencia:
                    filtro_data_inicio_agencia = st.date_input(
                        'Data inicial',
                        value=datetime.now().date() - timedelta(days=30),
                        key='filtro_data_inicio_noticias_agenciaal',
                    )
                else:
                    filtro_data_inicio_agencia = None
            with col_fag3:
                usar_data_fim_agencia = st.checkbox(
                    'Usar data final',
                    key='usar_data_fim_noticias_agenciaal',
                )
                if usar_data_fim_agencia:
                    filtro_data_fim_agencia = st.date_input(
                        'Data final',
                        value=datetime.now().date(),
                        key='filtro_data_fim_noticias_agenciaal',
                    )
                else:
                    filtro_data_fim_agencia = None

            if filtro_data_inicio_agencia and filtro_data_fim_agencia and filtro_data_inicio_agencia > filtro_data_fim_agencia:
                st.error('A data inicial deve ser menor ou igual a data final.')

            total_noticias_agencia_filtradas = contar_noticias_agenciaal_alesc(
                filtro_titulo=filtro_titulo_noticia_agencia,
                filtro_data_inicio=filtro_data_inicio_agencia,
                filtro_data_fim=filtro_data_fim_agencia,
            )

            col_pag_a1, col_pag_a2, col_pag_a3 = st.columns([1, 1, 2])
            with col_pag_a1:
                itens_por_pagina_noticias_ag = st.selectbox(
                    'Itens por pagina',
                    [20, 50, 100],
                    index=1,
                    key='itens_por_pagina_noticias_agenciaal',
                )

            total_paginas_noticias_ag = max(
                1,
                (total_noticias_agencia_filtradas + itens_por_pagina_noticias_ag - 1) // itens_por_pagina_noticias_ag,
            )

            with col_pag_a2:
                pagina_noticias_ag = int(
                    st.number_input(
                        'Pagina',
                        min_value=1,
                        max_value=total_paginas_noticias_ag,
                        value=min(st.session_state.get('pagina_noticias_agenciaal', 1), total_paginas_noticias_ag),
                        step=1,
                        key='pagina_noticias_agenciaal',
                    )
                )

            if total_noticias_agencia_filtradas > 0:
                inicio_noticias_ag = ((pagina_noticias_ag - 1) * itens_por_pagina_noticias_ag) + 1
                fim_noticias_ag = min(pagina_noticias_ag * itens_por_pagina_noticias_ag, total_noticias_agencia_filtradas)
            else:
                inicio_noticias_ag = 0
                fim_noticias_ag = 0

            with col_pag_a3:
                st.caption(
                    f"Exibindo {inicio_noticias_ag}-{fim_noticias_ag} de {total_noticias_agencia_filtradas} registros "
                    f"(pagina {pagina_noticias_ag} de {total_paginas_noticias_ag})."
                )

            if total_noticias_agencia_filtradas == 0:
                st.warning('Nenhuma noticia da Agencia AL encontrada com os filtros informados.')
            else:
                noticias_agencia_pagina = carregar_noticias_agenciaal_alesc(
                    pagina=pagina_noticias_ag,
                    itens_por_pagina=itens_por_pagina_noticias_ag,
                    filtro_titulo=filtro_titulo_noticia_agencia,
                    filtro_data_inicio=filtro_data_inicio_agencia,
                    filtro_data_fim=filtro_data_fim_agencia,
                )

                df_noticias_agencia = pd.DataFrame(
                    [
                        {
                            'Data': n['data_noticia'],
                            'Titulo': (n['titulo'][:180] + '...') if n['titulo'] and len(n['titulo']) > 180 else n['titulo'],
                            'Materia': n['url_noticia'],
                            'Importado em': n['data_importacao'],
                        }
                        for n in noticias_agencia_pagina
                    ]
                )

                st.dataframe(
                    df_noticias_agencia,
                    hide_index=True,
                    width='stretch',
                    column_config={
                        'Materia': st.column_config.LinkColumn('Materia', display_text='Abrir'),
                    },
                )

                primeira_noticia_ag = noticias_agencia_pagina[0]
                st.markdown('### Primeiro registro da pagina atual')
                st.write(f"**Data da noticia:** {primeira_noticia_ag.get('data_noticia') or 'Nao informado'}")
                st.write(f"**Titulo:** {primeira_noticia_ag.get('titulo') or 'Nao informado'}")
                if primeira_noticia_ag.get('url_noticia'):
                    st.markdown(f"[Abrir noticia completa]({primeira_noticia_ag['url_noticia']})")

                st.text_area(
                    'Conteudo integral da noticia',
                    value=primeira_noticia_ag.get('conteudo_noticia') or 'Conteudo nao extraido.',
                    height=320,
                )

        if st.button('🔄 Atualizar lista de noticias da Agencia AL', key='atualizar_noticias_agenciaal_alesc'):
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

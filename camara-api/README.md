# 🏛️ API Câmara dos Deputados - Streamlit App

Aplicação desenvolvida em Python com Streamlit para consumir a API RESTful de Dados Abertos da Câmara dos Deputados do Brasil.

## 📋 Descrição

Este projeto fornece uma interface web interativa para explorar os dados abertos da Câmara dos Deputados, incluindo:

- **Deputados**: Busca, detalhes e despesas
- **Proposições**: Listagem, detalhes, autores e tramitações
- **Partidos**: Informações e membros dos partidos políticos
- **Blocos**: Blocos parlamentares
- **Eventos**: Eventos da Câmara
- **Votações**: Histórico de votações e votos individuais
- **Órgãos**: Órgãos da Câmara e seus membros
- **ALESC**: Deputados estaduais e importadores de Atas

## 🚀 Instalação

### Pré-requisitos

- Python 3.8 ou superior
- pip (gerenciador de pacotes Python)

### Passos para instalação

1. Clone ou baixe este repositório

2. Navegue até o diretório do projeto:
```powershell
cd camara-api
```

3. Instale as dependências:
```powershell
pip install -r requirements.txt
```

## 💻 Como Usar

### Executar a aplicação

No diretório do projeto, execute:

```powershell
streamlit run app.py
```

A aplicação será aberta automaticamente no seu navegador padrão em `http://localhost:8501`

### Importar Atas da ALESC (todas as paginas)

No diretório do projeto, execute localmente:

```powershell
python alesc_atas_scraper.py
```

O script acessa a página de Atas da ALESC, percorre todas as páginas,
baixa os anexos (PDF, DOC e DOCX), extrai o conteúdo e salva na tabela `doutorado.atas_alesc`.

Por padrão, o scraper percorre todas as páginas disponíveis (atualmente 258) e
evita duplicidades em reexecuções com chave única em `url_download`.

Para testes rápidos:

```powershell
python alesc_atas_scraper.py --max-pages 5
```

### Importar Atas de Sessões Plenárias (Diário da ALESC)

No diretório do projeto, execute:

```powershell
python alesc_diario_plenario_scraper.py
```

O script varre os Diários da ALESC do mais recente para o mais antigo, analisa
apenas a seção de Atas de Sessões Plenárias, importa somente atas da 20ª
legislatura e para ao encontrar atas da 19ª legislatura.

Para evitar parada prematura em períodos com muitos diários sem ata plenária,
o limite de segurança pode ser configurado:

```powershell
python alesc_diario_plenario_scraper.py --max-sem-ata-sequencial 200
```

Para testes rápidos:

```powershell
python alesc_diario_plenario_scraper.py --max-pages 10 --max-sem-ata-sequencial 200
```

### Funcionalidades Principais

#### 1. Deputados
- **Listar Deputados**: Busque deputados por nome, UF ou partido
- **Detalhes**: Visualize informações completas de um deputado específico
- **Despesas**: Consulte as despesas por ano e mês com gráficos

#### 2. Proposições
- **Buscar**: Filtre por tipo (PL, PEC, PLP, etc.), número, ano e data
- **Detalhes**: Veja informações completas da proposição
- **Autores**: Liste os autores de uma proposição
- **Tramitações**: Acompanhe o histórico de tramitação

#### 3. Partidos
- Liste todos os partidos políticos
- Visualize detalhes e membros de cada partido

#### 4. Votações
- Consulte votações por proposição e período
- Veja detalhes da votação e todos os votos registrados
- Visualize gráficos de distribuição de votos

#### 5. Órgãos
- Liste os órgãos da Câmara
- Consulte membros de cada órgão

#### 6. ALESC
- Visualize deputados estaduais importados no PostgreSQL
- Importe e visualize Atas da ALESC (todas as páginas, com deduplicação)
- Importe Atas de Sessões Plenárias via Diário da ALESC

## 📁 Estrutura do Projeto

```
camara-api/
│
├── app.py              # Aplicação Streamlit (interface)
├── api_client.py       # Cliente para consumir a API REST
├── alesc_scraper.py    # Scraper de deputados da ALESC
├── alesc_atas_scraper.py # Scraper de todas as atas da ALESC (com leitura de PDF)
├── alesc_diario_plenario_scraper.py # Scraper de atas plenárias no Diário da ALESC
├── requirements.txt    # Dependências do projeto
└── README.md          # Este arquivo
```

## 🔧 Componentes

### api_client.py

Classe `CamaraAPIClient` que implementa métodos para consumir todos os endpoints da API:

- Gerenciamento de sessão HTTP
- Tratamento de erros
- Métodos para todos os recursos da API

### app.py

Interface Streamlit com:

- Navegação por abas
- Formulários de busca interativos
- Visualização de dados em tabelas e gráficos
- Cache de recursos para melhor performance

## 📚 API Utilizada

- **Documentação**: https://dadosabertos.camara.leg.br/swagger/api.html
- **Base URL**: https://dadosabertos.camara.leg.br/api/v2
- **Formato**: JSON
- **Autenticação**: Não requerida

## 🛠️ Tecnologias

- **Python 3**: Linguagem de programação
- **Streamlit**: Framework para criação de aplicações web
- **Requests**: Biblioteca para requisições HTTP
- **Pandas**: Análise e manipulação de dados

## 📊 Exemplos de Uso

### Buscar deputados por UF
1. Acesse a aba "Deputados"
2. Na aba "Listar Deputados"
3. Digite a UF desejada (ex: SP)
4. Clique em "Buscar Deputados"

### Consultar despesas de um deputado
1. Obtenha o ID do deputado (use a busca)
2. Acesse a aba "Despesas"
3. Informe o ID, ano e mês (opcional)
4. Clique em "Buscar Despesas"
5. Visualize a tabela e gráfico de despesas

### Acompanhar tramitação de uma proposição
1. Busque a proposição desejada
2. Anote o ID da proposição
3. Acesse "Detalhes da Proposição"
4. Informe o ID e clique em "Buscar Tramitações"

## ⚠️ Observações

- A API tem limites de paginação (máximo de itens por requisição)
- Alguns dados podem não estar disponíveis para períodos antigos
- A performance depende da disponibilidade da API oficial

## 🤝 Contribuições

Este é um projeto educacional. Sinta-se livre para:
- Reportar bugs
- Sugerir melhorias
- Adicionar novas funcionalidades

## 📄 Licença

Este projeto utiliza dados públicos disponibilizados pela Câmara dos Deputados.

## 🔗 Links Úteis

- [Dados Abertos - Câmara dos Deputados](https://dadosabertos.camara.leg.br/)
- [Documentação Streamlit](https://docs.streamlit.io/)
- [Documentação Requests](https://requests.readthedocs.io/)

---

Desenvolvido com 🐍 Python e ❤️ para transparência pública

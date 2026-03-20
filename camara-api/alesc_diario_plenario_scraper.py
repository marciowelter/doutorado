"""
alesc_diario_plenario_scraper.py
================================
Importa atas de sessoes plenarias a partir do Diario da Assembleia (ALESC).

Regras implementadas:
1) Processa diarios do mais recente para o mais antigo.
2) Analisa apenas a secao "ATAS" e a subsecao "SESSAO/SESSOES PLENARIA(S)".
3) Identifica atas com padrao "ATA DA XXXª SESSAO ... Xª SESSAO LEGISLATIVA DA YYª LEGISLATURA".
4) Importa apenas atas da 20ª legislatura.
5) Ao encontrar ata da 19ª legislatura, interrompe o processamento.
6) Se ficar 20 diarios sequenciais sem encontrar nenhuma ata, interrompe (anti-loop).
7) Evita duplicidade com indice unico e ON CONFLICT DO NOTHING.

Uso:
    python alesc_diario_plenario_scraper.py
    python alesc_diario_plenario_scraper.py --max-pages 30
"""

import argparse
import os
import re
import sys
import unicodedata
from datetime import datetime
from io import BytesIO
from urllib.parse import parse_qs, urljoin, urlparse

import psycopg2
import requests
import urllib3
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pypdf import PdfReader

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = 'https://portal-dados.alesc.sc.gov.br'
LIST_URL = f'{BASE_URL}/v2/diario-alesc'
TARGET_LEGISLATURA = 20
STOP_LEGISLATURA = 19
DEFAULT_MAX_SEM_ATA_SEQUENCIAL = 20


def _headers() -> dict[str, str]:
    return {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/125.0.0.0 Safari/537.36'
        )
    }


def _normalizar_texto(texto: str) -> str:
    return re.sub(r'\s+', ' ', (texto or '')).strip()


def _parse_data(valor: str):
    try:
        return datetime.strptime(valor.strip(), '%d/%m/%Y').date()
    except Exception:
        return None


def _get_soup(url: str) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, timeout=60, headers=_headers())
        resp.raise_for_status()
        return BeautifulSoup(resp.text, 'html.parser')
    except requests.exceptions.SSLError:
        try:
            resp = requests.get(url, timeout=60, headers=_headers(), verify=False)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, 'html.parser')
        except Exception as exc:
            print(f'ERRO ao abrir {url}: {exc}')
            return None
    except Exception as exc:
        print(f'ERRO ao abrir {url}: {exc}')
        return None


def _descobrir_total_paginas(soup: BeautifulSoup) -> int:
    texto = _normalizar_texto(soup.get_text(' ', strip=True))
    m = re.search(r'P[aá]gina\s+\d+\s+de\s+(\d+)', texto, flags=re.IGNORECASE)
    if m:
        return int(m.group(1))

    paginas = [1]
    for a in soup.select('a[href*="page="]'):
        href = (a.get('href') or '').strip()
        if not href:
            continue
        p = parse_qs(urlparse(href).query).get('page', [None])[0]
        if p and p.isdigit():
            paginas.append(int(p))
    return max(paginas)


def _extrair_diarios_pagina(soup: BeautifulSoup) -> list[dict]:
    diarios = []

    for col in soup.select('div.col-lg-8 div.col-12'):
        h4 = col.find('h4')
        if not h4:
            continue

        titulo = _normalizar_texto(h4.get_text(' ', strip=True))
        m_num = re.search(r'Di[áa]rio\s*N[º°o]?\s*(\d+)', titulo, flags=re.IGNORECASE)
        if not m_num:
            continue

        numero_diario = int(m_num.group(1))
        bloco_texto = _normalizar_texto(col.get_text(' ', strip=True))

        m_data = re.search(r'Publicado\s+em\s*(\d{2}/\d{2}/\d{4})', bloco_texto, flags=re.IGNORECASE)
        data_publicacao = _parse_data(m_data.group(1)) if m_data else None

        a_download = None
        for a in col.select('a[href]'):
            href = (a.get('href') or '').strip()
            txt = _normalizar_texto(a.get_text(' ', strip=True)).lower()
            if not href:
                continue
            if 'download' in txt or href.lower().endswith('.pdf'):
                a_download = a
                break

        if not a_download:
            continue

        download_url = urljoin(BASE_URL, a_download.get('href'))

        diarios.append(
            {
                'numero_diario': numero_diario,
                'data_publicacao': data_publicacao,
                'download_url': download_url,
            }
        )

    # Garante ordem do mais recente para o mais antigo dentro da pagina
    diarios.sort(key=lambda d: d['numero_diario'], reverse=True)
    return diarios


def _baixar_pdf(url: str) -> bytes:
    try:
        resp = requests.get(url, timeout=120, headers=_headers())
        resp.raise_for_status()
        return resp.content
    except requests.exceptions.SSLError:
        resp = requests.get(url, timeout=120, headers=_headers(), verify=False)
        resp.raise_for_status()
        return resp.content


def _extrair_texto_pdf(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    partes = []
    for page in reader.pages:
        texto = page.extract_text() or ''
        if texto:
            partes.append(texto)
    return '\n'.join(partes)


def _recortar_subsecao_plenaria(texto: str) -> str:
    if not texto:
        return ''

    upper = texto.upper()
    idx_atas = upper.find('ATAS')
    if idx_atas < 0:
        return ''

    m_sub = re.search(r'SESS(?:[ÕO]ES?|[ÃA]O)\s+PLEN[ÁA]RIAS?', upper[idx_atas:])
    if not m_sub:
        return ''

    start = idx_atas + m_sub.start()
    return texto[start:]


FOOTER_NOISE_TOKENS_ASCII = (
    'DIARIO DA ASSEMBLEIA',
    'DIARIO OFICIAL ASSINADO',
    'REDACOES PUBLICADAS',
)

SECTION_HEADING_COMPACT_TOKENS = (
    'COMISSOESPERMANENTES',
    'COMISSAOPERMANENTE',
    'ATOSDAPRESIDENCIA',
    'ATOSDAMESA',
    'CADERNOADMINISTRATIVO',
    'PROPOSICOESDEORIGEMDOLEGISLATIVO',
    'PROPOSICOES',
    'MENSAGENSGOVERNAMENTAIS',
    'COMUNICACOESPARLAMENTARES',
    'REDACOESFINAIS',
    'ORDEMDODIA',
    'PEQUENOEXPEDIENTE',
    'GRANDEEXPEDIENTE',
    'JUSTIFICACAO',
)

ATA_REUNIAO_HEADER_RE = re.compile(
    r'\bATA\s+DA\s+\d{1,4}\s*[A]?\s+REUNIAO\b.*\bCOMISSAO\b',
    flags=re.IGNORECASE,
)

SECTION_START_FALLBACK_PATTERNS = (
    re.compile(r'(?im)^\s*C\s*A\s*D\s*E\s*R\s*N\s*O\s+A\s*D\s*M\s*I\s*N\s*I\s*S\s*T\s*R\s*A\s*T'),
    re.compile(r'(?im)^\s*A\s*T\s*O\s*S?\s+D\s*A\s+(?:P\s*R\s*E\s*S\s*I\s*D|M\s*E\s*S\s*A)'),
    re.compile(r'(?im)^\s*C\s*O\s*M\s*I\s*S\s*S\s*O?\s*E?\s*S?\s+P\s*E\s*R\s*M\s*A\s*N\s*E\s*N\s*T'),
    re.compile(r'(?im)^\s*P\s*R\s*O\s*P\s*O\s*S\s*I'),
    re.compile(r'(?im)^\s*M\s*E\s*N\s*S\s*A\s*G\s*E\s*N'),
    re.compile(r'(?im)^\s*C\s*O\s*M\s*U\s*N\s*I\s*C\s*A'),
    re.compile(r'(?im)^\s*R\s*E\s*D\s*A'),
    re.compile(r'(?im)^\s*ATA\s+DA\s+\d{1,4}\s*[ªA]?\s+REUNI\S*'),
)

ENCERRAMENTO_SESSAO_PATTERNS = (
    re.compile(r'EST[ÁA]\s+ENCERRADA\s+A\s+SESS[ÃA]O', flags=re.IGNORECASE),
    re.compile(r'DECLARO\s+ENCERRADA\s+A\s+SESS[ÃA]O', flags=re.IGNORECASE),
    re.compile(r'ENCERRADA\s+A\s+SESS[ÃA]O', flags=re.IGNORECASE),
    re.compile(r'NADA\s+MAIS\s+HAVENDO\s+A\s+TRATAR', flags=re.IGNORECASE),
)

SECTION_START_INLINE_PATTERNS = (
    re.compile(r'C\s*A\s*D\s*E\s*R\s*N\s*O\s+A\s*D\s*M\s*I\s*N\s*I\s*S\s*T\s*R\s*A\s*T', flags=re.IGNORECASE),
    re.compile(r'A\s*T\s*O\s*S?\s+D\s*A\s+(?:P\s*R\s*E\s*S\s*I\s*D|M\s*E\s*S\s*A)', flags=re.IGNORECASE),
    re.compile(r'C\s*O\s*M\s*I\s*S\s*S\s*O?\s*E?\s*S?\s+P\s*E\s*R\s*M\s*A\s*N\s*E\s*N\s*T', flags=re.IGNORECASE),
    re.compile(r'P\s*R\s*O\s*P\s*O\s*S\s*I', flags=re.IGNORECASE),
    re.compile(r'M\s*E\s*N\s*S\s*A\s*G\s*E\s*N', flags=re.IGNORECASE),
    re.compile(r'C\s*O\s*M\s*U\s*N\s*I\s*C\s*A', flags=re.IGNORECASE),
    re.compile(r'R\s*E\s*D\s*A', flags=re.IGNORECASE),
    re.compile(r'ATA\s+DA\s+\d{1,4}\s*[ªA]?\s+REUNI\S*.*?\bCOMISS[ÃA]O\b', flags=re.IGNORECASE),
)


def _to_ascii_upper(texto: str) -> str:
    texto = texto or ''
    ascii_texto = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('ascii')
    return _normalizar_texto(ascii_texto).upper()


def _compact_letters_ascii(texto: str) -> str:
    return re.sub(r'[^A-Z]', '', _to_ascii_upper(texto))


def _linha_parece_inicio_nova_secao(linha: str) -> bool:
    """Heurística para detectar início de seção posterior ao bloco de atas plenárias."""
    linha_bruta = _normalizar_texto(linha)
    if not linha_bruta:
        return False

    linha_ascii = _to_ascii_upper(linha_bruta)
    letras_ascii = re.sub(r'[^A-Z]', '', linha_ascii)
    if len(letras_ascii) < 6:
        return False

    # Mantém apenas linhas majoritariamente em caixa alta no texto original.
    letras_orig = [ch for ch in linha_bruta if ch.isalpha()]
    qtd_upper = sum(1 for ch in letras_orig if ch.isupper())
    if letras_orig and (qtd_upper / len(letras_orig)) < 0.60:
        return False

    if len(linha_ascii) < 8 or len(linha_ascii) > 260:
        return False

    if any(token in linha_ascii for token in FOOTER_NOISE_TOKENS_ASCII):
        return False

    # Evita cortar em linhas de assinatura com muitos nomes.
    if linha_ascii.count(' - ') >= 2:
        return False

    if ATA_REUNIAO_HEADER_RE.search(linha_ascii):
        return True

    linha_compact = re.sub(r'[^A-Z]', '', linha_ascii)
    return any(token in linha_compact for token in SECTION_HEADING_COMPACT_TOKENS)


def _encontrar_fim_ultima_ata(subsecao: str, inicio_ata: int) -> int:
    """
    Para a última ata plenária do diário, corta no primeiro cabeçalho de seção posterior.
    Se não encontrar marcador confiável, mantém até o fim da subsecao.
    """
    if not subsecao:
        return inicio_ata

    if inicio_ata >= len(subsecao):
        return len(subsecao)

    # Evita cortar no cabeçalho inicial da própria ata, mas sem pular transições
    # de seção muito próximas do fim da ata (casos limítrofes no OCR/PDF).
    busca_min = min(len(subsecao), inicio_ata + 1000)

    # 1) Prioriza transição explícita de encerramento da sessão para uma nova seção,
    # inclusive quando o PDF concatenar tudo na mesma linha.
    cauda = subsecao[busca_min:]
    cortes = []
    janela_max = 12000
    for enc_pat in ENCERRAMENTO_SESSAO_PATTERNS:
        for m_enc in enc_pat.finditer(cauda):
            # Procura marcadores de nova seção logo após o encerramento.
            janela = cauda[m_enc.end():m_enc.end() + janela_max]
            for sec_pat in SECTION_START_INLINE_PATTERNS:
                m_sec = sec_pat.search(janela)
                if m_sec:
                    cortes.append(busca_min + m_enc.end() + m_sec.start())

    if cortes:
        return min(cortes)

    # 2) Heurística por linhas em caixa alta.
    pos = 0
    for linha in subsecao.splitlines(keepends=True):
        inicio_linha = pos
        pos += len(linha)

        if inicio_linha < busca_min:
            continue

        if _linha_parece_inicio_nova_secao(linha):
            return inicio_linha

    # 3) Fallback: busca direta por padrões de início de seção em modo multiline.
    cauda = subsecao[busca_min:]
    cortes = []
    for pattern in SECTION_START_FALLBACK_PATTERNS:
        m = pattern.search(cauda)
        if m:
            cortes.append(busca_min + m.start())

    if cortes:
        return min(cortes)

    return len(subsecao)


ATA_HEADER_RE = re.compile(
    r'ATA\s+DA\s+(\d{1,4})\s*[ªA]\s+SESS[ÃA]O\b(.*?)(?:\s+DA\s+)?(\d{1,2})\s*[ªA]\s+SESS[ÃA]O\s+LEGISLATIVA\s+DA\s+(\d{1,2})\s*[ªA]\s+LEGISLATURA',
    flags=re.IGNORECASE | re.DOTALL,
)


def _extrair_tipo_sessao(titulo: str) -> str | None:
    """
    Extrai o tipo da sessão do título da ata.
    Formato: "ATA DA XXXª SESSÃO <TIPO> YYYª SESSÃO LEGISLATIVA DA ZZZª LEGISLATURA"
    Retorna: "Ordinária", "Extraordinária", "Especial", etc. (sem "da" no final)
    """
    if not titulo:
        return None
    # Captura tudo entre "SESSÃO " e "Nª SESSÃO LEGISLATIVA"
    # O padrão: SESSÃO <tipo...> <numero>ª SESSÃO LEGISLATIVA
    match = re.search(
        r'SESSÃO\s+(.+?)\s+\d+ª\s+SESSÃO\s+LEGISLATIVA',
        titulo,
        flags=re.IGNORECASE,
    )
    if match:
        tipo = _normalizar_texto(match.group(1))
        # Remove "da" do final se existir (ex: "Especial da" -> "Especial")
        tipo = re.sub(r'\s+da\s*$', '', tipo, flags=re.IGNORECASE)
        # Capitaliza corretamente
        tipo = ' '.join([palavra.capitalize() for palavra in tipo.split()])
        return tipo if tipo else None
    return None


def _extrair_atas_da_subsecao(subsecao: str) -> list[dict]:
    if not subsecao:
        return []

    matches = list(ATA_HEADER_RE.finditer(subsecao))
    atas = []
    for i, m in enumerate(matches):
        start = m.start()
        if i + 1 < len(matches):
            end = matches[i + 1].start()
        else:
            end = _encontrar_fim_ultima_ata(subsecao, start)
        if end <= start:
            end = len(subsecao)
        conteudo = _normalizar_texto(subsecao[start:end])

        numero_ata = int(m.group(1))
        sessao_legislativa = int(m.group(3))
        legislatura = int(m.group(4))

        titulo = _normalizar_texto(subsecao[start:min(end, start + 500)])
        tipo_sessao = _extrair_tipo_sessao(titulo)

        atas.append(
            {
                'numero_ata': numero_ata,
                'sessao_legislativa': sessao_legislativa,
                'legislatura': legislatura,
                'titulo_ata': titulo,
                'tipo_sessao': tipo_sessao,
                'conteudo_ata': conteudo,
            }
        )

    return atas


def _conectar_banco():
    return psycopg2.connect(
        host=os.getenv('POSTGREE_HOST'),
        port=int(os.getenv('POSTGREE_PORT', 5432)),
        user=os.getenv('POSTGREE_USER'),
        password=os.getenv('POSTGREE_PASSWORD'),
        database='banco',
        connect_timeout=15,
        sslmode='require',
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5,
    )


def _preparar_tabela(conn, cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS doutorado.atas_sessoes_plenarias_alesc (
            id SERIAL PRIMARY KEY,
            diario_numero INTEGER,
            diario_data_publicacao DATE,
            diario_url_download TEXT,
            numero_ata INTEGER,
            sessao_legislativa INTEGER,
            legislatura INTEGER,
            titulo_ata TEXT,
            conteudo_ata TEXT,
            tipo_sessao VARCHAR(50),
            data_importacao TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        )
        """
    )

    # Adicionar coluna tipo_sessao se não existir
    cur.execute(
        """
        ALTER TABLE doutorado.atas_sessoes_plenarias_alesc
        ADD COLUMN IF NOT EXISTS tipo_sessao VARCHAR(50)
        """
    )

    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_atas_plenarias_diario_ata
        ON doutorado.atas_sessoes_plenarias_alesc (
            diario_numero,
            numero_ata,
            sessao_legislativa,
            legislatura
        )
        """
    )


def _inserir_ata(cur, registro: dict) -> bool:
    cur.execute(
        """
        INSERT INTO doutorado.atas_sessoes_plenarias_alesc (
            diario_numero,
            diario_data_publicacao,
            diario_url_download,
            numero_ata,
            sessao_legislativa,
            legislatura,
            titulo_ata,
            conteudo_ata,
            tipo_sessao
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (diario_numero, numero_ata, sessao_legislativa, legislatura) DO NOTHING
        RETURNING id
        """,
        (
            registro.get('diario_numero'),
            registro.get('diario_data_publicacao'),
            registro.get('diario_url_download'),
            registro.get('numero_ata'),
            registro.get('sessao_legislativa'),
            registro.get('legislatura'),
            registro.get('titulo_ata'),
            registro.get('conteudo_ata'),
            registro.get('tipo_sessao'),
        ),
    )
    return cur.fetchone() is not None


def importar_atas_plenarias(
    max_pages: int | None = None,
    max_sem_ata_sequencial: int = DEFAULT_MAX_SEM_ATA_SEQUENCIAL,
) -> None:
    conn = _conectar_banco()
    cur = conn.cursor()
    _preparar_tabela(conn, cur)
    conn.commit()

    soup_inicio = _get_soup(LIST_URL)
    if not soup_inicio:
        cur.close()
        conn.close()
        return

    total_paginas = _descobrir_total_paginas(soup_inicio)
    if max_pages is not None:
        total_paginas = min(total_paginas, max_pages)

    stats = {
        'paginas_lidas': 0,
        'diarios_lidos': 0,
        'atas_identificadas': 0,
        'atas_20_leg': 0,
        'atas_19_leg': 0,
        'atas_inseridas': 0,
        'atas_duplicadas': 0,
        'falhas_download_pdf': 0,
        'sem_ata_sequencial': 0,
    }
    ultimo_marco_commit = 0

    stop_reason = None

    print(f'Total de paginas para varrer: {total_paginas}')

    for pagina in range(1, total_paginas + 1):
        if pagina == 1:
            soup = soup_inicio
        else:
            soup = _get_soup(f'{LIST_URL}?page={pagina}')
            if not soup:
                continue

        stats['paginas_lidas'] += 1
        diarios = _extrair_diarios_pagina(soup)
        print(f'Pagina {pagina}/{total_paginas}: {len(diarios)} diario(s)')

        for diario in diarios:
            stats['diarios_lidos'] += 1
            numero_diario = diario['numero_diario']
            url_pdf = diario['download_url']

            try:
                pdf_bytes = _baixar_pdf(url_pdf)
                texto_pdf = _extrair_texto_pdf(pdf_bytes)
            except Exception as exc:
                stats['falhas_download_pdf'] += 1
                stats['sem_ata_sequencial'] += 1
                print(f"  [Falha Diario {numero_diario}] {url_pdf} - {exc}")

                if stats['sem_ata_sequencial'] >= max_sem_ata_sequencial:
                    stop_reason = (
                        f'Parada por seguranca: {max_sem_ata_sequencial} diarios sequenciais sem encontrar ata da {TARGET_LEGISLATURA}ª legislatura.'
                    )
                    break
                continue

            subsecao = _recortar_subsecao_plenaria(texto_pdf)
            atas = _extrair_atas_da_subsecao(subsecao)

            stats['atas_identificadas'] += len(atas)

            atas_alvo_no_diario = 0
            for ata in atas:
                if ata['legislatura'] == STOP_LEGISLATURA:
                    stats['atas_19_leg'] += 1
                    continue

                if ata['legislatura'] != TARGET_LEGISLATURA:
                    continue

                atas_alvo_no_diario += 1
                stats['atas_20_leg'] += 1

                registro = {
                    'diario_numero': numero_diario,
                    'diario_data_publicacao': diario['data_publicacao'],
                    'diario_url_download': url_pdf,
                    'numero_ata': ata['numero_ata'],
                    'sessao_legislativa': ata['sessao_legislativa'],
                    'legislatura': ata['legislatura'],
                    'titulo_ata': ata['titulo_ata'],
                    'tipo_sessao': ata['tipo_sessao'],
                    'conteudo_ata': ata['conteudo_ata'],
                }

                inserida = _inserir_ata(cur, registro)
                if inserida:
                    stats['atas_inseridas'] += 1
                else:
                    stats['atas_duplicadas'] += 1

            if atas_alvo_no_diario == 0:
                stats['sem_ata_sequencial'] += 1
            else:
                stats['sem_ata_sequencial'] = 0

            marco_atual = (stats['atas_inseridas'] // 20) * 20
            if marco_atual > 0 and marco_atual > ultimo_marco_commit:
                conn.commit()
                ultimo_marco_commit = marco_atual
                print(f"  Progresso: {marco_atual} atas inseridas...")

            if stats['sem_ata_sequencial'] >= max_sem_ata_sequencial:
                stop_reason = (
                    f'Parada por seguranca: {max_sem_ata_sequencial} diarios sequenciais sem encontrar ata da {TARGET_LEGISLATURA}ª legislatura.'
                )
                break

        if stop_reason:
            break

    conn.commit()
    cur.close()
    conn.close()

    print('\n=== Resumo Importacao - Atas de Sessao Plenaria ===')
    print(f"- Paginas lidas: {stats['paginas_lidas']}")
    print(f"- Diarios lidos: {stats['diarios_lidos']}")
    print(f"- Atas identificadas na subsecao plenaria: {stats['atas_identificadas']}")
    print(f"- Atas da 20ª legislatura encontradas: {stats['atas_20_leg']}")
    print(f"- Atas da 19ª legislatura encontradas: {stats['atas_19_leg']}")
    print(f"- Inseridas: {stats['atas_inseridas']}")
    print(f"- Duplicadas ignoradas: {stats['atas_duplicadas']}")
    print(f"- Falhas de diario/PDF: {stats['falhas_download_pdf']}")
    print(f"- Sem ata sequencial (contador final): {stats['sem_ata_sequencial']}")
    if stop_reason:
        print(f"- Motivo de parada: {stop_reason}")
    else:
        print('- Motivo de parada: fim das paginas configuradas.')
    print('Concluido.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Importa atas de sessoes plenarias da ALESC a partir do Diario da Assembleia.'
    )
    parser.add_argument(
        '--max-pages',
        type=int,
        default=None,
        help='Limita paginas para teste (padrao: todas disponiveis ate criterio de parada).',
    )
    parser.add_argument(
        '--max-sem-ata-sequencial',
        type=int,
        default=DEFAULT_MAX_SEM_ATA_SEQUENCIAL,
        help='Parada de seguranca por diarios seguidos sem ata (padrao: 20).',
    )
    args = parser.parse_args()

    if args.max_pages is not None and args.max_pages <= 0:
        print('ERRO: --max-pages deve ser > 0.')
        sys.exit(1)

    if args.max_sem_ata_sequencial <= 0:
        print('ERRO: --max-sem-ata-sequencial deve ser > 0.')
        sys.exit(1)

    print('=== Scraper Diario ALESC - Atas de Sessao Plenaria ===\n')

    try:
        importar_atas_plenarias(
            max_pages=args.max_pages,
            max_sem_ata_sequencial=args.max_sem_ata_sequencial,
        )
    except KeyboardInterrupt:
        print('\nInterrompido pelo usuario.')
        sys.exit(1)

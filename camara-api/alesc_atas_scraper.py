"""
alesc_atas_scraper.py
=====================
Script para extrair atas de reunioes da ALESC (todas as paginas) e salvar no banco.

EXECUTE ESTE SCRIPT NA SUA MAQUINA LOCAL (nao no servidor),
pois o site da ALESC pode bloquear conexoes fora do Brasil.

Dependencias:
    python -m pip install requests beautifulsoup4 psycopg2-binary python-dotenv pypdf

Uso:
    python alesc_atas_scraper.py
    python alesc_atas_scraper.py --max-pages 5

Padrao:
    percorre todas as paginas disponiveis (hoje 258) e evita duplicidade
    na tabela doutorado.atas_alesc usando url_download como chave unica.
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from io import BytesIO
from urllib.parse import parse_qs, urljoin, urlparse
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import psycopg2
import requests
import urllib3
from bs4 import BeautifulSoup, Tag
from dotenv import load_dotenv
from pypdf import PdfReader

# Carrega credenciais do .env no mesmo diretorio
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))

BASE_URL = 'https://portalelegis.alesc.sc.gov.br'
ATAS_URL = f'{BASE_URL}/comissoes-permanentes/atas'

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


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


def _normalizar_texto_multilinha(texto: str) -> str:
    if not texto:
        return ''
    linhas = [re.sub(r'\s+', ' ', l).strip() for l in texto.splitlines()]
    linhas = [l for l in linhas if l]
    return '\n'.join(linhas)


def _parse_data_evento(valor: str):
    try:
        return datetime.strptime(valor.strip(), '%d/%m/%Y').date()
    except Exception:
        return None


def _local_parece_valido(local: str) -> bool:
    if not local or len(local) < 8:
        return False

    local_l = local.lower()
    termos_esperados = (
        'plenario',
        'sala',
        'auditorio',
        'alesc',
        'assembleia',
        'florianopolis',
        'palacio',
        'rua',
    )
    return any(t in local_l for t in termos_esperados)


def _extrair_local_do_texto(texto_pdf: str) -> str | None:
    if not texto_pdf:
        return None

    linhas = [_normalizar_texto(linha) for linha in texto_pdf.splitlines() if _normalizar_texto(linha)]

    for linha in linhas:
        match = re.match(r'(?i)^local(?: da reuniao)?\s*[:\-]\s*(.+)$', linha)
        if not match:
            continue

        local = _normalizar_texto(match.group(1))
        local = re.split(
            r'\b(Data|Horario|Assunto|Ementa|Tipo)\b',
            local,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip(' .;:-')

        if _local_parece_valido(local):
            return local

    for linha in linhas:
        if re.match(r'(?i)^(plenario|auditorio|sala)\b', linha):
            local = linha.strip(' .;:-')
            if _local_parece_valido(local):
                return local

    return None


def _baixar_documento(download_url: str) -> tuple[bytes, str]:
    try:
        resp = requests.get(download_url, timeout=120, headers=_headers())
        resp.raise_for_status()
        return resp.content, (resp.headers.get('Content-Type') or '').lower()
    except requests.exceptions.SSLError:
        # Alguns ambientes locais nao reconhecem a cadeia de certificados do host.
        resp = requests.get(download_url, timeout=120, headers=_headers(), verify=False)
        resp.raise_for_status()
        return resp.content, (resp.headers.get('Content-Type') or '').lower()


def _extrair_texto_pdf(pdf_bytes: bytes) -> tuple[str, str | None]:
    reader = PdfReader(BytesIO(pdf_bytes))
    partes = []
    for page in reader.pages:
        texto_pagina = page.extract_text() or ''
        if texto_pagina:
            partes.append(texto_pagina)

    texto_bruto = '\n'.join(partes)
    texto_normalizado = _normalizar_texto(texto_bruto)
    local_evento = _extrair_local_do_texto(texto_bruto)
    return texto_normalizado, local_evento


def _extrair_texto_docx(docx_bytes: bytes) -> str:
    textos = []
    with ZipFile(BytesIO(docx_bytes)) as zf:
        for nome in (
            'word/document.xml',
            'word/header1.xml',
            'word/header2.xml',
            'word/footer1.xml',
            'word/footer2.xml',
        ):
            if nome not in zf.namelist():
                continue
            xml_raw = zf.read(nome)
            root = ET.fromstring(xml_raw)
            for t in root.iter():
                if t.tag.endswith('}t') and t.text:
                    textos.append(t.text)
                elif t.tag.endswith('}tab'):
                    textos.append('\t')
                elif t.tag.endswith('}br') or t.tag.endswith('}cr'):
                    textos.append('\n')
                elif t.tag.endswith('}p'):
                    textos.append('\n')

    return _normalizar_texto_multilinha(''.join(textos))


def _extrair_texto_doc_antiword(doc_bytes: bytes) -> str | None:
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.doc') as tmp:
            tmp.write(doc_bytes)
            tmp_path = tmp.name

        proc = subprocess.run(
            ['antiword', tmp_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='ignore',
            timeout=90,
        )
        if proc.returncode != 0:
            return None

        texto = _normalizar_texto_multilinha(proc.stdout)
        return texto if len(texto) >= 80 else None
    except Exception:
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def _extrair_texto_binario_heuristico(blob: bytes) -> str:
    partes = []

    for m in re.finditer(rb'(?:[\x20-\x7e]\x00){8,}', blob):
        trecho = m.group(0)
        try:
            txt = trecho.decode('utf-16le', errors='ignore')
        except Exception:
            continue
        txt = _normalizar_texto(txt)
        if len(txt) >= 8:
            partes.append(txt)

    for m in re.finditer(rb'[\x20-\x7e]{12,}', blob):
        trecho = m.group(0)
        try:
            txt = trecho.decode('latin-1', errors='ignore')
        except Exception:
            continue
        txt = _normalizar_texto(txt)
        if len(txt) >= 12:
            partes.append(txt)

    # Preserva ordem removendo duplicatas.
    vistos = set()
    unicos = []
    for p in partes:
        if p in vistos:
            continue
        vistos.add(p)
        unicos.append(p)

    texto = '\n'.join(unicos)
    return _normalizar_texto_multilinha(texto)


def _detectar_tipo_arquivo(download_url: str, content_type: str, blob: bytes) -> str:
    low_url = (download_url or '').lower()
    low_ct = (content_type or '').lower()

    if low_url.endswith('.pdf') or 'application/pdf' in low_ct or blob.startswith(b'%PDF'):
        return 'pdf'

    if low_url.endswith('.docx') or 'wordprocessingml.document' in low_ct or blob.startswith(b'PK\x03\x04'):
        return 'docx'

    if low_url.endswith('.doc') or 'application/msword' in low_ct or blob.startswith(b'\xd0\xcf\x11\xe0'):
        return 'doc'

    return 'desconhecido'


def _extrair_conteudo_documento(download_url: str) -> tuple[str | None, str | None, str]:
    blob, content_type = _baixar_documento(download_url)
    tipo = _detectar_tipo_arquivo(download_url, content_type, blob)

    if tipo == 'pdf':
        texto, local = _extrair_texto_pdf(blob)
        return (texto or None), local, tipo

    if tipo == 'docx':
        texto = _extrair_texto_docx(blob)
        return (texto or None), None, tipo

    if tipo == 'doc':
        texto = _extrair_texto_doc_antiword(blob)
        if not texto:
            texto = _extrair_texto_binario_heuristico(blob)
        if not texto:
            texto = 'Documento DOC importado. Nao foi possivel extrair texto legivel automaticamente.'
        return (texto or None), None, tipo

    texto = _extrair_texto_binario_heuristico(blob)
    if not texto:
        texto = 'Documento importado. Nao foi possivel identificar texto legivel automaticamente.'
    return (texto or None), None, tipo


def _obter_soup(url: str) -> BeautifulSoup | None:
    try:
        response = requests.get(url, timeout=60, headers=_headers())
        response.raise_for_status()
        return BeautifulSoup(response.text, 'html.parser')
    except Exception as exc:
        print(f"ERRO ao abrir {url}: {exc}")
        return None


def _cards_de_ata(soup: BeautifulSoup) -> list[Tag]:
    cards = []
    for candidate in soup.select('div.card.card-alesc.mb-3'):
        if candidate.select_one('a[href*=".pdf"], a[href*="taquigrafiacomissoes"], a[href*="download.alesc.sc.gov.br"]'):
            cards.append(candidate)
    return cards


def _descobrir_total_paginas(soup: BeautifulSoup) -> int:
    paginas = [1]
    for link in soup.select('ul.pagination a[href*="page="]'):
        href = (link.get('href') or '').strip()
        if not href:
            continue
        pagina = parse_qs(urlparse(href).query).get('page', [None])[0]
        if pagina and str(pagina).isdigit():
            paginas.append(int(pagina))
    return max(paginas)


def _extrair_dados_card(card: Tag) -> dict | None:
    data_texto = _normalizar_texto(
        card.select_one('div.text-success').get_text(' ', strip=True)
        if card.select_one('div.text-success')
        else ''
    )
    comissao = _normalizar_texto(
        card.select_one('h5.mb-1').get_text(' ', strip=True)
        if card.select_one('h5.mb-1')
        else ''
    )
    ementa = _normalizar_texto(
        card.select_one('p.text-secondary').get_text(' ', strip=True)
        if card.select_one('p.text-secondary')
        else ''
    )
    tipo_evento = _normalizar_texto(
        card.select_one('div.badge').get_text(' ', strip=True)
        if card.select_one('div.badge')
        else ''
    )

    visualizar_url = None
    download_url = None

    for link in card.select('a[href]'):
        href = (link.get('href') or '').strip()
        texto_link = _normalizar_texto(link.get_text(' ', strip=True)).lower()

        if href and not visualizar_url and 'visualizar' in texto_link:
            visualizar_url = urljoin(BASE_URL, href)

        if href and not download_url and ('download' in texto_link or href.lower().endswith('.pdf')):
            download_url = urljoin(BASE_URL, href)

    if not download_url:
        return None

    return {
        'data_evento': _parse_data_evento(data_texto),
        'comissao': comissao or None,
        'tipo_evento': tipo_evento or None,
        'ementa': ementa or None,
        'url_visualizacao': visualizar_url,
        'url_download': download_url,
    }


def iterar_atas(max_pages: int | None = None):
    print(f"Abrindo {ATAS_URL} ...")
    primeira_pagina = _obter_soup(ATAS_URL)
    if not primeira_pagina:
        return

    total_paginas = _descobrir_total_paginas(primeira_pagina)
    if max_pages:
        total_paginas = min(total_paginas, max_pages)

    print(f"Total de paginas para processar: {total_paginas}")

    for pagina in range(1, total_paginas + 1):
        if pagina == 1:
            soup = primeira_pagina
        else:
            soup = _obter_soup(f"{ATAS_URL}?page={pagina}")
            if not soup:
                print(f"AVISO: pagina {pagina} indisponivel, seguindo para a proxima.")
                continue

        cards = _cards_de_ata(soup)
        print(f"Pagina {pagina}/{total_paginas}: {len(cards)} ata(s) encontrada(s)")

        for card in cards:
            dados = _extrair_dados_card(card)
            if not dados:
                continue
            dados['pagina'] = pagina
            yield dados


def _conectar_banco():
    return psycopg2.connect(
        host=os.getenv('POSTGREE_HOST'),
        port=int(os.getenv('POSTGREE_PORT', 5432)),
        user=os.getenv('POSTGREE_USER'),
        password=os.getenv('POSTGREE_PASSWORD'),
        database='banco',
        connect_timeout=15,
        sslmode='require',
    )


def _preparar_tabela(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS doutorado.atas_alesc (
            id SERIAL PRIMARY KEY,
            data_evento DATE,
            local_evento TEXT,
            tipo_evento TEXT,
            ementa TEXT,
            conteudo_ata TEXT,
            url_visualizacao TEXT,
            url_download TEXT,
            data_importacao TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        )
        """
    )

    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_atas_alesc_url_download
        ON doutorado.atas_alesc (url_download)
        """
    )


def _carregar_urls_existentes(cur) -> set[str]:
    cur.execute(
        """
        SELECT url_download
        FROM doutorado.atas_alesc
        WHERE url_download IS NOT NULL
        """
    )
    return {r[0] for r in cur.fetchall() if r and r[0]}


def _inserir_ata(cur, ata: dict) -> bool:
    cur.execute(
        """
        INSERT INTO doutorado.atas_alesc (
            data_evento,
            local_evento,
            tipo_evento,
            ementa,
            conteudo_ata,
            url_visualizacao,
            url_download
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (url_download) DO NOTHING
        RETURNING id
        """,
        (
            ata.get('data_evento'),
            ata.get('local_evento'),
            ata.get('tipo_evento'),
            ata.get('ementa'),
            ata.get('conteudo_ata'),
            ata.get('url_visualizacao'),
            ata.get('url_download'),
        ),
    )
    return cur.fetchone() is not None


def importar_atas(max_pages: int | None = None) -> None:
    conn = _conectar_banco()
    cur = conn.cursor()

    _preparar_tabela(cur)
    conn.commit()

    urls_existentes = _carregar_urls_existentes(cur)
    print(f"Registros ja existentes no banco (url_download): {len(urls_existentes)}")

    stats = {
        'atas_lidas': 0,
        'novas': 0,
        'duplicadas': 0,
        'falhas_documento': 0,
        'pdf': 0,
        'docx': 0,
        'doc': 0,
        'desconhecido': 0,
    }

    for dados in iterar_atas(max_pages=max_pages):
        stats['atas_lidas'] += 1
        download_url = dados.get('url_download')

        if not download_url:
            continue

        if download_url in urls_existentes:
            stats['duplicadas'] += 1
            continue

        try:
            conteudo_ata, local_extraido_pdf, tipo_documento = _extrair_conteudo_documento(download_url)
            stats[tipo_documento] = stats.get(tipo_documento, 0) + 1
        except Exception as exc:
            stats['falhas_documento'] += 1
            print(f"  [Falha Documento] pag {dados.get('pagina')} - {download_url} - {exc}")
            continue

        registro = {
            'data_evento': dados.get('data_evento'),
            'local_evento': local_extraido_pdf or dados.get('comissao'),
            'tipo_evento': dados.get('tipo_evento'),
            'ementa': dados.get('ementa'),
            'conteudo_ata': conteudo_ata or None,
            'url_visualizacao': dados.get('url_visualizacao'),
            'url_download': download_url,
        }

        inserida = _inserir_ata(cur, registro)
        if inserida:
            stats['novas'] += 1
            urls_existentes.add(download_url)
        else:
            stats['duplicadas'] += 1

        # Commit em lotes para reduzir risco de perda em execucoes longas.
        if stats['novas'] % 20 == 0:
            conn.commit()
            print(f"  Progresso: {stats['novas']} novas atas gravadas...")

    conn.commit()
    cur.close()
    conn.close()

    print('\n=== Resumo da importacao de Atas ALESC ===')
    print(f"- Atas lidas no portal: {stats['atas_lidas']}")
    print(f"- Novas inseridas: {stats['novas']}")
    print(f"- Duplicadas ignoradas: {stats['duplicadas']}")
    print(f"- Falhas na leitura de documento: {stats['falhas_documento']}")
    print(f"- Arquivos processados: PDF={stats['pdf']} DOCX={stats['docx']} DOC={stats['doc']} DESCONHECIDO={stats['desconhecido']}")
    print('Concluido.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Importa atas da ALESC para PostgreSQL.')
    parser.add_argument(
        '--max-pages',
        type=int,
        default=None,
        help='Limita a quantidade de paginas para teste (padrao: todas as paginas disponiveis).',
    )
    args = parser.parse_args()

    if args.max_pages is not None and args.max_pages <= 0:
        print('ERRO: --max-pages deve ser maior que zero.')
        sys.exit(1)

    print('=== Scraper de Atas da ALESC (todas as paginas) ===\n')

    try:
        importar_atas(max_pages=args.max_pages)
    except KeyboardInterrupt:
        print('\nInterrompido pelo usuario.')
        sys.exit(1)

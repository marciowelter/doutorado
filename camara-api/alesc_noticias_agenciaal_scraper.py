"""
alesc_noticias_agenciaal_scraper.py
===================================
Importa noticias da Agencia AL (Comunicacao Social da ALESC).

Regras principais:
1) A listagem de noticias e dinamica (carregada por scroll).
2) Cada noticia e deduplicada pela URL da materia completa.
3) Em reprocessamentos, ao encontrar 20 noticias consecutivas ja importadas,
   encerra a execucao para evitar varrer todo o historico novamente.

Uso:
    python alesc_noticias_agenciaal_scraper.py
    python alesc_noticias_agenciaal_scraper.py --max-duplicadas-sequenciais 20
"""

import argparse
import os
import re
import sys
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse, urlunparse

import psycopg2
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))

LIST_URL = 'https://www.alesc.sc.gov.br/agenciaal/'
USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/125.0.0.0 Safari/537.36'
)


def _normalizar_espacos(texto: str) -> str:
    return re.sub(r'\s+', ' ', (texto or '')).strip()


def _normalizar_url_noticia(url: str) -> str:
    if not url:
        return ''

    full = urljoin(LIST_URL, url)
    parsed = urlparse(full)
    path = parsed.path or ''
    if not path.endswith('/'):
        path = f'{path}/'

    return urlunparse((parsed.scheme, parsed.netloc, path, '', '', ''))


def _parse_data(valor: str):
    try:
        return datetime.strptime(valor.strip(), '%d/%m/%Y').date()
    except Exception:
        return None


def _headers() -> dict[str, str]:
    return {'User-Agent': USER_AGENT}


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


def _preparar_tabela(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS doutorado.noticias_agencia_al_alesc (
            id SERIAL PRIMARY KEY,
            data_noticia DATE,
            titulo TEXT NOT NULL,
            url_noticia TEXT NOT NULL,
            conteudo_noticia TEXT,
            data_importacao TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        )
        """
    )

    cur.execute(
        """
        ALTER TABLE doutorado.noticias_agencia_al_alesc
        ADD COLUMN IF NOT EXISTS data_noticia DATE
        """
    )
    cur.execute(
        """
        ALTER TABLE doutorado.noticias_agencia_al_alesc
        ADD COLUMN IF NOT EXISTS titulo TEXT
        """
    )
    cur.execute(
        """
        ALTER TABLE doutorado.noticias_agencia_al_alesc
        ADD COLUMN IF NOT EXISTS url_noticia TEXT
        """
    )
    cur.execute(
        """
        ALTER TABLE doutorado.noticias_agencia_al_alesc
        ADD COLUMN IF NOT EXISTS conteudo_noticia TEXT
        """
    )
    cur.execute(
        """
        ALTER TABLE doutorado.noticias_agencia_al_alesc
        ADD COLUMN IF NOT EXISTS data_importacao TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        """
    )

    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_noticias_agencia_al_alesc_url
        ON doutorado.noticias_agencia_al_alesc (url_noticia)
        """
    )


def _capturar_links_noticias(page) -> list[dict]:
    raw = page.eval_on_selector_all(
        "a[href*='/agenciaal/noticia/']",
        """
        els => els.map(el => ({
            href: el.href || '',
            text: (el.textContent || '').replace(/\\s+/g, ' ').trim(),
        }))
        """,
    )

    ordem_urls = []
    melhor_titulo_por_url: dict[str, str] = {}

    for item in raw:
        href = _normalizar_url_noticia(item.get('href', ''))
        if not href:
            continue
        if '/agenciaal/noticia/' not in href:
            continue

        txt = _normalizar_espacos(item.get('text', ''))
        if href not in melhor_titulo_por_url:
            ordem_urls.append(href)
            melhor_titulo_por_url[href] = txt
        elif len(txt) > len(melhor_titulo_por_url[href]):
            melhor_titulo_por_url[href] = txt

    return [{'url_noticia': url, 'titulo_hint': melhor_titulo_por_url.get(url, '')} for url in ordem_urls]


def _extrair_detalhes_noticia(url: str, sessao_http: requests.Session) -> dict | None:
    try:
        resp = sessao_http.get(url, timeout=90, headers=_headers())
        resp.raise_for_status()
    except requests.exceptions.SSLError:
        try:
            resp = sessao_http.get(url, timeout=90, headers=_headers(), verify=False)
            resp.raise_for_status()
        except Exception:
            return None
    except Exception:
        return None

    soup = BeautifulSoup(resp.text, 'html.parser')

    titulo = ''
    for sel in ['h1.lab-title-news', 'h1', 'h2.lab-title-news', 'h2']:
        node = soup.select_one(sel)
        if node and _normalizar_espacos(node.get_text(' ', strip=True)):
            titulo = _normalizar_espacos(node.get_text(' ', strip=True))
            break

    if not titulo:
        og = soup.select_one("meta[property='og:title']")
        if og and og.get('content'):
            titulo = _normalizar_espacos(og.get('content'))

    titulo = re.sub(
        r'\s*-\s*Assembleia\s+Legislativa\s+do\s+Estado\s+de\s+Santa\s+Catarina\s*$',
        '',
        titulo,
        flags=re.IGNORECASE,
    )

    main_node = soup.select_one('main')
    main_texto = _normalizar_espacos(main_node.get_text(' ', strip=True) if main_node else soup.get_text(' ', strip=True))

    data_noticia = None
    m_data_hora = re.search(r'(\d{1,2}/\d{1,2}/\d{4})\s*-\s*\d{1,2}h\d{2}min', main_texto)
    if m_data_hora:
        data_noticia = _parse_data(m_data_hora.group(1))
    else:
        m_data = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', main_texto)
        if m_data:
            data_noticia = _parse_data(m_data.group(1))

    conteudo = ''
    for sel in ['.lab-blog-content', '.entry-content', '.post-content', '.node__content', 'main', 'article']:
        node = soup.select_one(sel)
        if not node:
            continue
        txt = _normalizar_espacos(node.get_text(' ', strip=True))
        if len(txt) > len(conteudo):
            conteudo = txt

    if len(conteudo) < 80:
        conteudo = main_texto

    if not titulo:
        return None

    return {
        'titulo': titulo,
        'data_noticia': data_noticia,
        'conteudo_noticia': conteudo,
    }


def _inserir_noticia(cur, registro: dict) -> bool:
    cur.execute(
        """
        INSERT INTO doutorado.noticias_agencia_al_alesc (
            data_noticia,
            titulo,
            url_noticia,
            conteudo_noticia
        )
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (url_noticia) DO NOTHING
        RETURNING id
        """,
        (
            registro.get('data_noticia'),
            registro.get('titulo'),
            registro.get('url_noticia'),
            registro.get('conteudo_noticia'),
        ),
    )
    return cur.fetchone() is not None


def importar_noticias_agencia_al_alesc(
    max_duplicadas_sequenciais: int = 20,
    max_scroll_sem_novidades: int = 8,
    headless: bool = True,
    callback_progresso=None,
) -> dict:
    if max_duplicadas_sequenciais <= 0:
        raise ValueError('max_duplicadas_sequenciais deve ser > 0')

    if max_scroll_sem_novidades <= 0:
        raise ValueError('max_scroll_sem_novidades deve ser > 0')

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    except ImportError as exc:
        raise RuntimeError(
            'Playwright nao instalado. Execute: pip install playwright e python -m playwright install chromium'
        ) from exc

    conn = _conectar_banco()
    cur = conn.cursor()

    _preparar_tabela(cur)
    conn.commit()

    cur.execute('SELECT url_noticia FROM doutorado.noticias_agencia_al_alesc')
    urls_existentes = {
        _normalizar_url_noticia(r[0])
        for r in cur.fetchall()
        if r and r[0]
    }

    stats = {
        'scrolls_executados': 0,
        'urls_descobertas': 0,
        'noticias_analisadas': 0,
        'noticias_inseridas': 0,
        'noticias_duplicadas': 0,
        'falhas_extracao': 0,
        'duplicadas_consecutivas': 0,
        'motivo_parada': '',
        'duracao_segundos': 0.0,
        'mensagens': [],
    }

    def _log(msg: str) -> None:
        stats['mensagens'].append(msg)
        print(msg)
        if callback_progresso:
            callback_progresso(msg)

    inicio = time.time()
    _log('Iniciando importacao de noticias da Agencia AL...')
    _log(f'URLs ja existentes no banco: {len(urls_existentes)}')

    urls_processadas_na_execucao: set[str] = set()
    duplicadas_consecutivas = 0
    sessao_http = requests.Session()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(
                viewport={'width': 1366, 'height': 900},
                user_agent=USER_AGENT,
            )
            page = context.new_page()

            try:
                page.goto(LIST_URL, timeout=120000, wait_until='domcontentloaded')
            except PlaywrightTimeoutError as exc:
                raise RuntimeError('Timeout ao abrir a pagina da Agencia AL.') from exc

            time.sleep(4)
            scrolls_sem_novidade = 0

            while True:
                itens_visiveis = _capturar_links_noticias(page)
                novos_itens = [
                    item
                    for item in itens_visiveis
                    if item['url_noticia'] not in urls_processadas_na_execucao
                ]

                for item in novos_itens:
                    urls_processadas_na_execucao.add(item['url_noticia'])

                stats['urls_descobertas'] = len(urls_processadas_na_execucao)

                if novos_itens:
                    scrolls_sem_novidade = 0
                    _log(
                        f'Novas noticias detectadas nesta rodada: {len(novos_itens)} '
                        f'(total descobertas: {stats["urls_descobertas"]})'
                    )
                else:
                    scrolls_sem_novidade += 1

                for item in novos_itens:
                    url_noticia = item['url_noticia']
                    stats['noticias_analisadas'] += 1

                    if url_noticia in urls_existentes:
                        stats['noticias_duplicadas'] += 1
                        duplicadas_consecutivas += 1
                        stats['duplicadas_consecutivas'] = duplicadas_consecutivas

                        if duplicadas_consecutivas >= max_duplicadas_sequenciais:
                            stats['motivo_parada'] = (
                                f'Parada por seguranca: {max_duplicadas_sequenciais} '
                                'noticias duplicadas consecutivas.'
                            )
                            _log(stats['motivo_parada'])
                            break
                        continue

                    duplicadas_consecutivas = 0
                    stats['duplicadas_consecutivas'] = 0

                    detalhes = _extrair_detalhes_noticia(url_noticia, sessao_http)
                    if not detalhes:
                        stats['falhas_extracao'] += 1
                        _log(f'[FALHA] Nao foi possivel extrair noticia: {url_noticia}')
                        continue

                    registro = {
                        'data_noticia': detalhes.get('data_noticia'),
                        'titulo': detalhes.get('titulo') or item.get('titulo_hint') or 'Sem titulo',
                        'url_noticia': url_noticia,
                        'conteudo_noticia': detalhes.get('conteudo_noticia') or '',
                    }

                    inserida = _inserir_noticia(cur, registro)
                    if inserida:
                        conn.commit()
                        urls_existentes.add(url_noticia)
                        stats['noticias_inseridas'] += 1
                    else:
                        stats['noticias_duplicadas'] += 1

                if stats['motivo_parada']:
                    break

                if scrolls_sem_novidade >= max_scroll_sem_novidades:
                    stats['motivo_parada'] = (
                        f'Parada por fim de carregamento: {max_scroll_sem_novidades} '
                        'scroll(s) sem novidades.'
                    )
                    _log(stats['motivo_parada'])
                    break

                page.evaluate('window.scrollBy(0, Math.floor(window.innerHeight * 0.90))')
                stats['scrolls_executados'] += 1
                time.sleep(1.2)

            context.close()
            browser.close()

    finally:
        cur.close()
        conn.close()

    stats['duracao_segundos'] = round(time.time() - inicio, 2)

    _log('\n=== Resumo Importacao Noticias Agencia AL ===')
    _log(f"- Scrolls executados: {stats['scrolls_executados']}")
    _log(f"- URLs descobertas: {stats['urls_descobertas']}")
    _log(f"- Noticias analisadas: {stats['noticias_analisadas']}")
    _log(f"- Inseridas: {stats['noticias_inseridas']}")
    _log(f"- Duplicadas: {stats['noticias_duplicadas']}")
    _log(f"- Falhas de extracao: {stats['falhas_extracao']}")
    _log(f"- Duracao (s): {stats['duracao_segundos']}")
    if stats['motivo_parada']:
        _log(f"- Motivo de parada: {stats['motivo_parada']}")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description='Importa noticias da Agencia AL com deduplicacao por URL.'
    )
    parser.add_argument(
        '--max-duplicadas-sequenciais',
        type=int,
        default=20,
        help='Encerra apos N noticias duplicadas consecutivas (padrao: 20).',
    )
    parser.add_argument(
        '--max-scroll-sem-novidades',
        type=int,
        default=8,
        help='Encerra apos N scrolls sem novas noticias detectadas (padrao: 8).',
    )
    parser.add_argument(
        '--show-browser',
        action='store_true',
        help='Mostra o navegador durante a execucao (padrao: headless).',
    )
    args = parser.parse_args()

    if args.max_duplicadas_sequenciais <= 0:
        print('ERRO: --max-duplicadas-sequenciais deve ser > 0.')
        sys.exit(1)

    if args.max_scroll_sem_novidades <= 0:
        print('ERRO: --max-scroll-sem-novidades deve ser > 0.')
        sys.exit(1)

    try:
        importar_noticias_agencia_al_alesc(
            max_duplicadas_sequenciais=args.max_duplicadas_sequenciais,
            max_scroll_sem_novidades=args.max_scroll_sem_novidades,
            headless=not args.show_browser,
        )
    except KeyboardInterrupt:
        print('\nInterrompido pelo usuario.')
        sys.exit(1)
    except Exception as exc:
        print(f'ERRO: {exc}')
        sys.exit(1)


if __name__ == '__main__':
    main()

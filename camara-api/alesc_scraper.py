"""
alesc_scraper.py
================
Script para extrair a lista de deputados da ALESC e salvar no banco de dados.

EXECUTE ESTE SCRIPT NA SUA MÁQUINA LOCAL (não no servidor),
pois o site www.alesc.sc.gov.br bloqueia conexões de IPs fora do Brasil.

Dependências:
    python -m pip install playwright psycopg2-binary python-dotenv beautifulsoup4
    python -m playwright install chromium

Uso:
    python alesc_scraper.py

O script se conecta ao PostgreSQL usando as mesmas variáveis do .env e
substitui todos os registros de doutorado.deputados_alesc com os dados atuais.
"""

import os
import sys
import time
import psycopg2
from dotenv import load_dotenv
from bs4 import BeautifulSoup

# Carrega credenciais do .env no mesmo diretório
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))


def extrair_deputados_alesc() -> list[dict]:
    """
    Abre a página https://www.alesc.sc.gov.br/deputados/ com Playwright,
    rola a página até carregar todos os cards e retorna lista de dicts
    com nome, partido, foto_url e link_perfil.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    except ImportError:
        print("ERRO: playwright não instalado. Execute: python -m pip install playwright && python -m playwright install chromium")
        sys.exit(1)

    URL = 'https://www.alesc.sc.gov.br/deputados/'
    deputados = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1280, 'height': 900},
            user_agent=(
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
            )
        )
        page = context.new_page()

        print(f"Abrindo {URL} ...")
        try:
            page.goto(URL, timeout=120000, wait_until='domcontentloaded')
        except PlaywrightTimeoutError:
            browser.close()
            print("ERRO: Timeout ao conectar em https://www.alesc.sc.gov.br/deputados/.")
            print("Este ambiente provavelmente nao tem acesso ao site da ALESC.")
            print("Execute este script localmente na sua maquina com internet brasileira.")
            return []
        except Exception as exc:
            browser.close()
            print(f"ERRO ao abrir a pagina da ALESC: {exc}")
            return []
        time.sleep(4)  # aguarda JS inicializar

        # Scroll progressivo para carregar lazy-load
        print("Rolando a página para carregar todos os deputados...")
        prev_count = 0
        no_change_rounds = 0
        for i in range(40):
            page.evaluate("window.scrollBy(0, 600)")
            time.sleep(1.5)

            # Conta cards visíveis
            current_count = page.locator('img[src*="deputad"], img[alt], .card, article').count()
            if current_count == prev_count:
                no_change_rounds += 1
                if no_change_rounds >= 4:
                    print(f"  Sem novos elementos após {i+1} scrolls. Parando.")
                    break
            else:
                no_change_rounds = 0
            prev_count = current_count
            print(f"  scroll {i+1}: {current_count} elementos detectados")

        # Scroll final para o topo (garantir que a página renderizou tudo)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(2)

        html = page.content()
        browser.close()

    # Parse do HTML
    soup = BeautifulSoup(html, 'html.parser')

    # Estratégia 1: estrutura atual da ALESC (nome em h3.lab-title-news)
    name_nodes = soup.select('h3.lab-title-news')
    if name_nodes:
        print(f"Encontrados {len(name_nodes)} cards de deputados (lab-title-news).")
        for name_node in name_nodes:
            nome = name_node.get_text(strip=True)
            if not nome:
                continue

            info_col = name_node.find_parent('div', class_='col') or name_node.parent

            partido = ''
            if info_col:
                partido_el = info_col.select_one(
                    'span.lab-button, span[class*="button"], span[class*="partido"], .partido, .sigla'
                )
                if partido_el and partido_el.get_text(strip=True):
                    partido = partido_el.get_text(strip=True)

            foto_url = ''
            link_perfil = ''
            row = name_node.find_parent('div', class_='row') or info_col
            if row:
                img = row.find('img')
                if img:
                    foto_url = img.get('src') or img.get('data-src') or ''
                    if foto_url and foto_url.startswith('/'):
                        foto_url = 'https://www.alesc.sc.gov.br' + foto_url

                a = row.find_parent('a', href=True) or row.find('a', href=True)
                if a:
                    link_perfil = a['href']
                    if link_perfil.startswith('/'):
                        link_perfil = 'https://www.alesc.sc.gov.br' + link_perfil

            deputados.append({
                'nome': nome,
                'partido': partido or None,
                'foto_url': foto_url or None,
                'link_perfil': link_perfil or None,
            })

        if deputados:
            return deputados

    # Estratégias de extração em ordem de prioridade
    # 1. Cards com classe contendo "deputad" ou "parlamentar"
    cards = soup.find_all(
        lambda tag: tag.name in ('div', 'article', 'li') and
        any(c for c in (tag.get('class') or [])
            if 'deputad' in c.lower() or 'parlamentar' in c.lower() or 'member' in c.lower())
    )

    # 2. Fallback: qualquer bloco com foto + texto próximos
    if not cards:
        print("  Tentando estratégia alternativa de extração...")
        cards = soup.select('.card, .person, .vereador, article')

    if not cards:
        # Dump do HTML para debug
        debug_file = os.path.join(os.path.dirname(__file__), 'alesc_debug.html')
        with open(debug_file, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"AVISO: Nenhum card encontrado. HTML salvo em {debug_file} para inspeção.")
        print("Inspecione o arquivo e ajuste os seletores CSS neste script.")
        return []

    print(f"Encontrados {len(cards)} cards de deputados.")

    for card in cards:
        # Nome
        nome = ''
        for sel in ['h2', 'h3', 'h4', '.nome', '.title', '.name']:
            el = card.select_one(sel)
            if el and el.get_text(strip=True):
                nome = el.get_text(strip=True)
                break
        if not nome:
            el = card.find(['h2', 'h3', 'h4', 'strong'])
            if el:
                nome = el.get_text(strip=True)

        # Partido
        partido = ''
        for sel in [
            '.partido',
            '.party',
            '.sigla',
            '.lab-button',
            'span[class*="button"]',
            'span[class*="partido"]',
            'span[style*="background"]',
        ]:
            el = card.select_one(sel)
            if el and el.get_text(strip=True):
                partido = el.get_text(strip=True)
                break

        # Foto
        foto_url = ''
        img = card.find('img')
        if img:
            foto_url = img.get('src') or img.get('data-src') or ''
            if foto_url and foto_url.startswith('/'):
                foto_url = 'https://www.alesc.sc.gov.br' + foto_url

        # Link do perfil
        link_perfil = ''
        a = card.find('a', href=True)
        if a:
            link_perfil = a['href']
            if link_perfil.startswith('/'):
                link_perfil = 'https://www.alesc.sc.gov.br' + link_perfil

        if nome:
            deputados.append({
                'nome': nome,
                'partido': partido or None,
                'foto_url': foto_url or None,
                'link_perfil': link_perfil or None,
            })

    return deputados


def salvar_no_banco(deputados: list[dict]) -> None:
    """Limpa a tabela e insere os deputados extraídos."""
    if not deputados:
        print("Nenhum deputado para salvar.")
        return

    conn = psycopg2.connect(
        host=os.getenv('POSTGREE_HOST'),
        port=int(os.getenv('POSTGREE_PORT', 5432)),
        user=os.getenv('POSTGREE_USER'),
        password=os.getenv('POSTGREE_PASSWORD'),
        database='banco',
        connect_timeout=15,
        sslmode='require',
    )
    cur = conn.cursor()

    cur.execute("TRUNCATE TABLE doutorado.deputados_alesc RESTART IDENTITY")

    for dep in deputados:
        cur.execute(
            """
            INSERT INTO doutorado.deputados_alesc (nome, partido, foto_url, link_perfil)
            VALUES (%s, %s, %s, %s)
            """,
            (dep['nome'], dep['partido'], dep['foto_url'], dep['link_perfil'])
        )

    conn.commit()
    print(f"{len(deputados)} deputados salvos em doutorado.deputados_alesc.")
    cur.close()
    conn.close()


if __name__ == '__main__':
    print("=== Scraper de Deputados da ALESC ===\n")
    deputies = extrair_deputados_alesc()
    if deputies:
        print("\nExemplo (3 primeiros):")
        for d in deputies[:3]:
            print(f"  {d['nome']} - {d['partido']}")
        salvar_no_banco(deputies)
    else:
        print("Nenhum deputado extraído. Verifique o HTML e ajuste os seletores.")
    print("\nConcluído.")

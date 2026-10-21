"""
Coletor em massa de produtos - TerabyteShop
---------------------------------------------
A página de BUSCA também é SSR (renderizada no servidor): não existe uma
API JSON separada. Cada produto aparece num card HTML assim:

    <div class="product-item"
         data-tss-product="6240"
         data-tss-brand="SuperFrame"
         data-tss-price="999.99"
         data-tss-frete="0"
         data-tss-estoque="1"
         data-tss-promo="1">
        ...
        <a href="/produto/27544/placa-mae-..." title="Nome do produto" class="product-item__image">

Ou seja, dá pra extrair ID, marca, preço, frete grátis, estoque e promoção
direto dos atributos data-tss-*, sem precisar nem de BeautifulSoup.

URL de busca (GET simples, sem body):
    https://www.terabyteshop.com.br/busca?str={termo}&pg={pagina}

Parâmetros úteis vistos no HTML:
    str              -> termo de busca (ex: "placa mãe")
    pg               -> número da página (1, 2, 3, ...)
    order (opcional) -> preco_asc | preco_desc | ordem_asc ...
    manufacturer (opcional) -> ID numérico do fabricante, para filtrar por marca

Este arquivo agora é só a "biblioteca" de scraping (funções puras). Quem
decide QUANDO rodar e O QUE fazer com o resultado é o main.py (API FastAPI)
ou o bloco `if __name__ == "__main__":` lá embaixo, se você rodar direto.
"""

from __future__ import annotations

import csv
import json
import re
import time

import requests

# ---------------------------------------------------------------------------
# Termos de busca. Edite esta lista para mudar o que é coletado — não tem
# mais argumento de linha de comando para o termo. Adicione, remova ou
# comente (#) linhas à vontade.
# ---------------------------------------------------------------------------
SEARCH_TERMS: list[str] = [
    "placa mãe",
    "memoria ram",
    "ssd nvme",
]

BASE_URL = "https://www.terabyteshop.com.br/busca"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

# Captura o bloco de atributos data-tss-* do card e, logo depois (non-greedy),
# o <a href="/produto/.../slug" title="Nome"> que vem dentro do mesmo card.
CARD_RE = re.compile(
    r'<div class="product-item" data-tss-product="(?P<id>\d+)" '
    r'data-tss-brand="(?P<brand>[^"]*)" '
    r'data-tss-price="(?P<price>[^"]*)" '
    r'data-tss-frete="(?P<frete>[^"]*)" '
    r'data-tss-estoque="(?P<estoque>[^"]*)" '
    r'data-tss-promo="(?P<promo>[^"]*)">'
    r'.*?href="(?P<url>/produto/\d+/[a-z0-9\-]+)" '
    r'title="(?P<name>[^"]*)" class="product-item__image"',
    re.DOTALL,
)


def parse_products(html: str) -> list[dict]:
    products = []
    for m in CARD_RE.finditer(html):
        d = m.groupdict()
        products.append(
            {
                "id": d["id"],
                "name": d["name"],
                "brand": d["brand"],
                "price": float(d["price"]) if d["price"] else None,
                "free_shipping": d["frete"] == "1",
                "in_stock": d["estoque"] == "1",
                "promo": d["promo"] == "1",
                "url": "https://www.terabyteshop.com.br" + d["url"],
            }
        )
    return products


def fetch_search_page(
    session: requests.Session,
    term: str,
    page: int,
    order: str | None = None,
    manufacturer: str | None = None,
) -> str:
    params = {"str": term, "pg": page}
    if order:
        params["order"] = order
    if manufacturer:
        params["manufacturer"] = manufacturer

    resp = session.get(BASE_URL, params=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.text


def collect_all(
    term: str,
    max_pages: int = 20,
    delay: float = 2.0,
    order: str | None = None,
    manufacturer: str | None = None,
) -> list[dict]:
    session = requests.Session()
    all_products: dict[str, dict] = {}  # dedup por id

    for page in range(1, max_pages + 1):
        html = fetch_search_page(session, term, page, order, manufacturer)
        products = parse_products(html)

        if not products:
            print(f"  Página {page}: 0 produtos -> fim da paginação.")
            break

        novos = 0
        for p in products:
            if p["id"] not in all_products:
                all_products[p["id"]] = p
                novos += 1

        print(f"  Página {page}: {len(products)} produtos ({novos} novos).")

        # Se a página não trouxe nenhum produto novo, provavelmente
        # a paginação "deu a volta" (repetiu a última página) -> parar.
        if novos == 0:
            print("  Nenhum produto novo nesta página -> parando.")
            break

        time.sleep(delay)  # educado: evita martelar o servidor

    return list(all_products.values())


def run_all_searches(
    max_pages: int = 20,
    delay: float = 2.0,
    order: str | None = None,
    manufacturer: str | None = None,
) -> dict[str, list[dict]]:
    """Roda collect_all() para CADA termo de SEARCH_TERMS.

    Retorna um dict {termo: [produtos]}. É isso que o main.py (FastAPI)
    chama e manda pro n8n.
    """
    results: dict[str, list[dict]] = {}
    for term in SEARCH_TERMS:
        print(f"Buscando: {term!r}")
        results[term] = collect_all(
            term, max_pages=max_pages, delay=delay, order=order, manufacturer=manufacturer
        )
    return results


def save_csv(products: list[dict], path: str):
    if not products:
        return
    fieldnames = list(products[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(products)


def main():
    """Modo linha de comando: roda todos os termos de SEARCH_TERMS e salva
    um CSV/JSON por termo. Não usa mais argparse — a lista de termos é
    editada aqui no arquivo, não passada por parâmetro."""
    results = run_all_searches()

    total = 0
    for term, products in results.items():
        slug = re.sub(r"[^a-z0-9]+", "_", term.lower()).strip("_")
        save_csv(products, f"produtos_{slug}.csv")
        with open(f"produtos_{slug}.json", "w", encoding="utf-8") as f:
            json.dump(products, f, ensure_ascii=False, indent=2)
        print(f"-> {term!r}: {len(products)} produtos salvos em produtos_{slug}.csv/.json")
        total += len(products)

    print(f"\nTotal coletado: {total} produtos em {len(SEARCH_TERMS)} termo(s).")


if __name__ == "__main__":
    main()
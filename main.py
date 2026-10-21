"""
API FastAPI que dispara o scraper e manda o resultado pro n8n.
-----------------------------------------------------------------
Rode com:
    uvicorn main:app --reload --port 8000

E então acesse http://localhost:8000/docs para testar pelo navegador,
ou veja os comentários no final deste arquivo para testar com curl.
"""

import os

import requests
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException

from scraper import SEARCH_TERMS, run_all_searches

# Lê o arquivo .env (mesma pasta deste main.py) e injeta as variáveis dele
# em os.environ, ANTES da linha que faz os.environ.get() logo abaixo.
# Se o .env não existir, load_dotenv() simplesmente não faz nada (não dá erro).
load_dotenv()

app = FastAPI(title="TerabyteShop Scraper API")

# URL do Webhook do n8n. Pegue copiando a URL do node "Webhook" dentro do
# seu workflow n8n (serve tanto a "Test URL" quanto a "Production URL").
#
# O valor vem do arquivo .env (veja .env.example neste projeto) — assim
# você não depende de setar a variável no terminal toda vez, e não precisa
# lembrar se já reiniciou o uvicorn depois de mudar o valor no terminal.
N8N_GETHOOK = os.environ.get("N8N_WEBHOOK_URL", "")

N8N_WEBHOOK_URL = f"http://localhost:5678/webhook/{N8N_GETHOOK}"


def scrape_and_send() -> dict:
    """Roda o scraper para todos os termos de SEARCH_TERMS e envia o
    resultado em JSON para o webhook do n8n. Retorna um resumo."""
    results = run_all_searches()

    payload = {
        "terms": SEARCH_TERMS,
        "total_products": sum(len(v) for v in results.values()),
        "results": results,
    }

    resp = requests.post(N8N_WEBHOOK_URL, json=payload, timeout=60)
    resp.raise_for_status()

    return {
        "status": "ok",
        "terms": SEARCH_TERMS,
        "total_products": payload["total_products"],
        "n8n_status_code": resp.status_code,
    }


@app.get("/")
def root():
    return {
        "message": "POST em /scrape para rodar o coletor e mandar o resultado pro n8n.",
        "terms_configurados": SEARCH_TERMS,
    }


@app.post("/scrape")
def scrape_sync():
    """Roda o scraping NA HORA e só responde quando terminar (e já tiver
    mandado pro n8n). Simples de entender, mas se SEARCH_TERMS tiver muitos
    termos/páginas, a requisição pode demorar bastante para responder."""
    if not N8N_WEBHOOK_URL:
        raise HTTPException(500, "N8N_WEBHOOK_URL não configurada (defina a variável de ambiente).")

    try:
        return scrape_and_send()
    except requests.RequestException as e:
        raise HTTPException(502, f"Falha ao enviar para o n8n: {e}")


@app.post("/scrape-async")
def scrape_async(background_tasks: BackgroundTasks):
    """Dispara o scraping em segundo plano e responde IMEDIATAMENTE.
    O resultado chega no n8n quando o scraping terminar — útil se a lista
    de termos for grande e você não quiser deixar o cliente HTTP esperando."""
    if not N8N_WEBHOOK_URL:
        raise HTTPException(500, "N8N_WEBHOOK_URL não configurada (defina a variável de ambiente).")

    background_tasks.add_task(scrape_and_send)
    return {"status": "started", "terms": SEARCH_TERMS}


# ---------------------------------------------------------------------------
# Como testar depois de rodar `uvicorn main:app --reload`:
#
#   curl -X POST http://localhost:8000/scrape
#
# ou simplesmente abra http://localhost:8000/docs no navegador, clique em
# POST /scrape -> "Try it out" -> "Execute".
# ---------------------------------------------------------------------------
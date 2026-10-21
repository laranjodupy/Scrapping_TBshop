"""
Script para rodar o scraping UMA VEZ e sair - feito para o GitHub Actions
(ou qualquer cron job). Não sobe servidor nenhum, só chama a mesma função
que o endpoint /scrape do main.py usa.

Uso:
    python run_once.py
"""

import sys

from main import scrape_and_send


def run():
    try:
        result = scrape_and_send()
    except Exception as e:
        print(f"Erro ao rodar o scraping: {e}", file=sys.stderr)
        sys.exit(1)

    print(result)
    sys.exit(0)


if __name__ == "__main__":
    run()
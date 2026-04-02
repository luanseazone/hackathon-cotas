import os
import httpx

METABASE_URL = os.getenv("METABASE_URL", "")
METABASE_API_KEY = os.getenv("METABASE_API_KEY", "")
METABASE_DB_ID = int(os.getenv("METABASE_DB_ID", "2"))

_BCB = "https://api.bcb.gov.br/dados/serie/bcdata.sgs"


async def _bcb(serie: int, n: int) -> list[dict]:
    url = f"{_BCB}.{serie}/dados/ultimos/{n}?formato=json"
    async with httpx.AsyncClient(timeout=8.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def _metabase_query(sql: str) -> list[dict]:
    if not METABASE_URL or not METABASE_API_KEY:
        return []
    url = f"{METABASE_URL}/api/dataset"
    headers = {"X-Api-Key": METABASE_API_KEY, "Content-Type": "application/json"}
    body = {"database": METABASE_DB_ID, "type": "native", "native": {"query": sql}}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
    cols = [c["name"] for c in data["data"]["cols"]]
    return [dict(zip(cols, row)) for row in data["data"]["rows"]]


async def get_economic_indicators() -> dict:
    # Selic: série 432 (Meta Selic % a.a., decisões Copom)
    # IPCA: série 433 (variação mensal %)
    try:
        selic_rows = await _bcb(432, 6)
        selic_atual = float(selic_rows[-1]["valor"])
        selic_historico = [
            {"data": r["data"], "valor": float(r["valor"])} for r in selic_rows
        ]
    except Exception:
        selic_atual = 13.75
        selic_historico = []

    try:
        ipca_rows = await _bcb(433, 12)
        ipca_12m = round(sum(float(r["valor"]) for r in ipca_rows), 2)
        ipca_historico = [
            {"data": r["data"], "valor": float(r["valor"])} for r in ipca_rows
        ]
    except Exception:
        ipca_12m = None
        ipca_historico = []

    return {
        "selic_aa": selic_atual,
        "selic_historico_6m": selic_historico,
        "ipca_12m": ipca_12m,
        "ipca_historico": ipca_historico,
    }


async def get_cub_history(meses: int = 12, estado: str = "SC") -> list[dict]:
    sql = f"""
        SELECT data_referencia, valor, variacao_mensal
        FROM indexer_quotations
        WHERE indexer_code = 'CUB'
          AND estado = '{estado}'
        ORDER BY data_referencia DESC
        LIMIT {meses}
    """
    try:
        return await _metabase_query(sql)
    except Exception:
        return []

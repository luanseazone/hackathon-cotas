import os
import httpx

METABASE_URL = os.getenv("METABASE_URL", "")
METABASE_API_KEY = os.getenv("METABASE_API_KEY", "")
METABASE_DB_ID = int(os.getenv("METABASE_DB_ID", "2"))


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


async def get_comparable_units(
    empreendimento_id: int,
    tipologia: str,
    area_min: float,
    area_max: float,
) -> list[dict]:
    # Busca unidades similares: mesmo empreendimento, tipologia e faixa de área.
    # Fallback: abre para qualquer unidade do mesmo empreendimento se não encontrar.
    sql = f"""
        SELECT
            u.codigo,
            u.area,
            u.tipologia,
            u.status,
            u.data_contrato,
            rf.net_revenue_total AS net_revenue,
            e.nome AS empreendimento
        FROM szi.unidades u
        JOIN szi.empreendimentos e ON e.id = u.empreendimento_id
        LEFT JOIN szi.resumo_financeiro rf ON rf.unidade_id = u.id
        WHERE u.empreendimento_id = {empreendimento_id}
          AND u.tipologia ILIKE '%{tipologia}%'
          AND u.area BETWEEN {area_min} AND {area_max}
        ORDER BY u.data_contrato DESC NULLS LAST
        LIMIT 10
    """
    try:
        rows = await _metabase_query(sql)
        if rows:
            return rows
    except Exception:
        pass

    # Fallback: sem filtro de tipologia/área
    sql_fallback = f"""
        SELECT
            u.codigo,
            u.area,
            u.tipologia,
            u.status,
            u.data_contrato,
            rf.net_revenue_total AS net_revenue,
            e.nome AS empreendimento
        FROM szi.unidades u
        JOIN szi.empreendimentos e ON e.id = u.empreendimento_id
        LEFT JOIN szi.resumo_financeiro rf ON rf.unidade_id = u.id
        WHERE u.empreendimento_id = {empreendimento_id}
        ORDER BY u.data_contrato DESC NULLS LAST
        LIMIT 10
    """
    try:
        return await _metabase_query(sql_fallback)
    except Exception:
        return []

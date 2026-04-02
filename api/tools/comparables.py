import os
import httpx

METABASE_URL = os.getenv("METABASE_URL", "")
METABASE_API_KEY = os.getenv("METABASE_API_KEY", "")
METABASE_DB_ID = int(os.getenv("METABASE_DB_ID", "2"))

_SEA_VIEW_POSITIONS = {"ampla_mar", "parcial_mar", "lateral_mar"}

_UNIDADES_SQL = """
WITH contrato_recente AS (
  SELECT * FROM (
    SELECT con.*,
      ROW_NUMBER() OVER (
        PARTITION BY con.spot_building_unit_id
        ORDER BY COALESCE(con.signature_date, con.created_at) DESC, con.id DESC
      ) AS rn
    FROM szi.spot_building_unit_contracts con
  ) t WHERE rn = 1
),
totais_pagos AS (
  SELECT sbu.id AS unidade_id, COALESCE(SUM(p.amount), 0) AS valor_pago
  FROM szi.spot_building_units sbu
  JOIN szi.spot_building_unit_contracts con ON con.spot_building_unit_id = sbu.id
  JOIN szi.financing_flows ff ON ff.spot_building_unit_contract_id = con.id
  JOIN szi.financing_flow_installments ffi ON ffi.financing_flow_id = ff.id
  JOIN szi.financing_flow_installment_billings ffib ON ffib.financing_flow_installment_id = ffi.id
  LEFT JOIN szi.installment_billing_payments p ON p.financing_flow_installment_billing_id = ffib.id
  GROUP BY sbu.id
),
cubs_totais AS (
  SELECT sbu.id AS unidade_id, COALESCE(sbu.index, 0) AS cubs_totais
  FROM szi.spot_building_units sbu
),
cubs_pagos_raw AS (
  SELECT sbu.id AS unidade_id, SUM(ffi.index) AS cubs_pagos
  FROM szi.spot_building_units sbu
  JOIN contrato_recente cr ON cr.spot_building_unit_id = sbu.id
  JOIN szi.financing_flows ff ON ff.spot_building_unit_contract_id = cr.id
  JOIN szi.financing_flow_installments ffi ON ffi.financing_flow_id = ff.id
  JOIN szi.financing_flow_installment_billings ffib ON ffib.financing_flow_installment_id = ffi.id
  JOIN szi.installment_billing_payments p ON p.financing_flow_installment_billing_id = ffib.id
  WHERE p.payment_date IS NOT NULL AND COALESCE(p.amount, 0) > 0
  GROUP BY sbu.id
),
cubs_pagos AS (
  SELECT t.unidade_id,
    LEAST(COALESCE(cp.cubs_pagos, 0), COALESCE(t.cubs_totais, 0)) AS cubs_pagos
  FROM cubs_totais t LEFT JOIN cubs_pagos_raw cp ON cp.unidade_id = t.unidade_id
),
cub_vigente AS (
  SELECT empreendimento_id, cub_max FROM (
    SELECT sb.id AS empreendimento_id, iq.amount AS cub_max,
      ROW_NUMBER() OVER (
        PARTITION BY sb.id
        ORDER BY CASE
          WHEN EXTRACT(YEAR FROM iq.reference_date) = EXTRACT(YEAR FROM CURRENT_DATE)
           AND EXTRACT(MONTH FROM iq.reference_date) = EXTRACT(MONTH FROM CURRENT_DATE) THEN 0
          ELSE 1 END, iq.reference_date DESC
      ) AS rn
    FROM szi.spot_buildings sb
    JOIN szi.indexer_quotations iq ON iq.indexer_id = sb.indexer_id
  ) t WHERE rn = 1
)
SELECT
  sb.id AS empreendimento_id,
  sb.short_name AS empreendimento,
  sb.city,
  sb.state,
  sbu.id AS unidade_id,
  sbu.code AS codigo,
  sbu.total_area AS area,
  sbu.floor AS andar,
  sbu.typology AS tipologia,
  sbu.solar_position,
  sbu.view_position,
  sbu.garden_total_area,
  sbu.terrace_balcony_total_area AS sacada_area,
  sbu.total_capacity AS capacidade,
  cr.percentage_share AS participacao_pct,
  cr.signature_date AS data_assinatura,
  COALESCE(tp.valor_pago, 0) AS valor_pago,
  GREATEST(
    COALESCE(ct.cubs_totais, 0) - COALESCE(cp.cubs_pagos, 0), 0
  ) * COALESCE(cv.cub_max, 0) AS valor_pendente
FROM szi.spot_buildings sb
JOIN szi.spot_building_units sbu ON sbu.spot_building_id = sb.id
LEFT JOIN contrato_recente cr ON cr.spot_building_unit_id = sbu.id
LEFT JOIN totais_pagos tp ON tp.unidade_id = sbu.id
LEFT JOIN cubs_totais ct ON ct.unidade_id = sbu.id
LEFT JOIN cubs_pagos cp ON cp.unidade_id = sbu.id
LEFT JOIN cub_vigente cv ON cv.empreendimento_id = sb.id
WHERE sb.id = {emp_id} AND sbu.is_active IS NOT FALSE
ORDER BY sbu.code
"""


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


async def get_empreendimentos() -> list[dict]:
    sql = """
        SELECT id, short_name, full_name, city, state
        FROM szi.spot_buildings
        ORDER BY short_name
    """
    try:
        return await _metabase_query(sql)
    except Exception:
        return []


async def get_unidades_by_empreendimento(empreendimento_id: int) -> list[dict]:
    try:
        rows = await _metabase_query(_UNIDADES_SQL.format(emp_id=int(empreendimento_id)))
    except Exception:
        return []

    result = []
    for r in rows:
        view = r.get("view_position") or ""
        tipologia = r.get("tipologia") or ""
        garden_area = r.get("garden_total_area") or 0
        sacada_area = r.get("sacada_area") or 0
        participacao = r.get("participacao_pct") or 1
        raw_date = r.get("data_assinatura") or ""

        result.append({
            "empreendimento_id": r["empreendimento_id"],
            "empreendimento": r["empreendimento"],
            "city": r.get("city"),
            "state": r.get("state"),
            "unidade_id": r["unidade_id"],
            "codigo": r["codigo"],
            "area": r.get("area"),
            "andar": r.get("andar"),
            "tipologia": tipologia,
            "solar_position": r.get("solar_position"),
            "view_position": view,
            "garden_total_area": garden_area,
            "sacada_area": sacada_area,
            "capacidade": r.get("capacidade"),
            "participacao_pct": round(float(participacao) * 100, 4),
            "data_assinatura": raw_date[:10] if raw_date else "2020-01-01",
            "valor_pago": float(r.get("valor_pago") or 0),
            "valor_pendente": float(r.get("valor_pendente") or 0),
            "vista_mar": view in _SEA_VIEW_POSITIONS,
            "garden": garden_area > 0 or tipologia in ("garden", "up_garden"),
            "sacada": sacada_area > 0 or tipologia in ("sacada_varanda", "rooftop"),
        })
    return result


async def get_comparable_units(
    empreendimento_id: int | None,
    tipologia: str,
    area_min: float,
    area_max: float,
) -> list[dict]:
    if not empreendimento_id:
        return []
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

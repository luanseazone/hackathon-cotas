from pydantic import BaseModel
from typing import Optional
import math


class CotaData(BaseModel):
    empreendimento_id: int
    empreendimento: str
    codigo: str
    area: float
    andar: Optional[str] = None
    tipologia: str = "padrao"
    valor_pago: float
    saldo_devedor: float
    participacao_pct: float = 100.0
    vista_mar: bool = False
    garden: bool = False
    sacada: bool = False
    posicao_solar: Optional[str] = None
    capacidade: Optional[int] = None
    data_assinatura: str
    imposto_pct: float = 0.0


COMISSAO_SZN = 0.06


def _calcular_cenario(
    cota: CotaData, preco_venda: float, selic_aa: float
) -> dict:
    valor_entrada = preco_venda - cota.saldo_devedor
    comissao_szn = COMISSAO_SZN * preco_venda
    ganho_bruto = max(0.0, valor_entrada - comissao_szn - cota.valor_pago)
    imposto = cota.imposto_pct * ganho_bruto
    valor_liquido = valor_entrada - comissao_szn - imposto
    agio = valor_liquido - cota.valor_pago
    roi_pct = (agio / cota.valor_pago * 100) if cota.valor_pago > 0 else 0.0

    return {
        "preco": round(preco_venda, 2),
        "comissao_szn": round(comissao_szn, 2),
        "valor_liquido": round(valor_liquido, 2),
        "agio": round(agio, 2),
        "roi_pct": round(roi_pct, 2),
    }


def _premium_caracteristicas(cota: CotaData) -> float:
    """Returns extra multiplier for optimistic scenario based on unit characteristics."""
    premium = 0.0
    if cota.vista_mar:
        premium += 0.05
    if cota.garden:
        premium += 0.03
    if cota.posicao_solar in ("nascente", "poente"):
        premium += 0.01
    return premium


def calcular_cenarios(
    cota: CotaData,
    selic_aa: float,
    preco_sugerido: Optional[float] = None,
) -> dict:
    valor_aquisicao = cota.valor_pago + cota.saldo_devedor
    preco_minimo = valor_aquisicao / (1 - COMISSAO_SZN)

    margem_conservadora = selic_aa / 100
    margem_justa = selic_aa / 100 + 0.04
    margem_otimista = selic_aa / 100 + 0.08
    premium = _premium_caracteristicas(cota)

    preco_conservador = math.ceil((preco_minimo + cota.valor_pago * margem_conservadora) / 1000) * 1000
    preco_justo = preco_sugerido or (math.ceil((preco_minimo + cota.valor_pago * margem_justa) / 1000) * 1000)
    preco_otimista = math.ceil((preco_minimo + cota.valor_pago * (margem_otimista + premium)) / 1000) * 1000

    return {
        "preco_minimo": round(preco_minimo, 2),
        "valor_aquisicao": round(valor_aquisicao, 2),
        "cenario_conservador": _calcular_cenario(cota, preco_conservador, selic_aa),
        "cenario_justo": _calcular_cenario(cota, preco_justo, selic_aa),
        "cenario_otimista": _calcular_cenario(cota, preco_otimista, selic_aa),
    }

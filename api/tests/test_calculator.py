import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.calculator import calcular_cenarios, CotaData

BASE_COTA = CotaData(
    empreendimento_id=1,
    empreendimento="Resort Teste",
    codigo="209",
    area=58.84,
    andar="2",
    tipologia="garden",
    valor_pago=100_000.0,
    saldo_devedor=100_000.0,
    participacao_pct=100.0,
    vista_mar=True,
    garden=True,
    sacada=False,
    posicao_solar="nascente",
    capacidade=4,
    data_assinatura="2022-03-15",
)


def test_preco_minimo_correto():
    resultado = calcular_cenarios(BASE_COTA, selic_aa=13.75)
    # preco_minimo = (100k + 100k) / (1 - 0.06) = 212765.96...
    assert abs(resultado["preco_minimo"] - 212765.96) < 1.0


def test_cenario_justo_acima_do_minimo():
    resultado = calcular_cenarios(BASE_COTA, selic_aa=13.75)
    assert resultado["cenario_justo"]["preco"] > resultado["preco_minimo"]


def test_cenario_otimista_acima_do_justo():
    resultado = calcular_cenarios(BASE_COTA, selic_aa=13.75)
    assert resultado["cenario_otimista"]["preco"] > resultado["cenario_justo"]["preco"]


def test_conservador_abaixo_do_justo():
    resultado = calcular_cenarios(BASE_COTA, selic_aa=13.75)
    assert resultado["cenario_conservador"]["preco"] < resultado["cenario_justo"]["preco"]


def test_roi_positivo_no_justo():
    resultado = calcular_cenarios(BASE_COTA, selic_aa=13.75)
    assert resultado["cenario_justo"]["roi_pct"] > 0


def test_comissao_szn_6_pct():
    resultado = calcular_cenarios(BASE_COTA, selic_aa=13.75, preco_sugerido=200_000.0)
    # comissao = 6% de 200k = 12k
    assert abs(resultado["cenario_justo"]["comissao_szn"] - 12_000.0) < 1.0


def test_preco_sugerido_customizado():
    resultado = calcular_cenarios(BASE_COTA, selic_aa=13.75, preco_sugerido=250_000.0)
    assert resultado["cenario_justo"]["preco"] == 250_000.0


def test_premium_caracteristicas_vista_mar():
    cota_sem_view = BASE_COTA.model_copy(update={"vista_mar": False, "garden": False})
    res_com = calcular_cenarios(BASE_COTA, selic_aa=13.75)
    res_sem = calcular_cenarios(cota_sem_view, selic_aa=13.75)
    assert res_com["cenario_otimista"]["preco"] > res_sem["cenario_otimista"]["preco"]


def test_imposto_reduz_valor_liquido():
    cota_com_imposto = BASE_COTA.model_copy(update={"imposto_pct": 0.15})
    res_sem = calcular_cenarios(BASE_COTA, selic_aa=13.75)
    res_com = calcular_cenarios(cota_com_imposto, selic_aa=13.75)
    assert res_com["cenario_justo"]["valor_liquido"] < res_sem["cenario_justo"]["valor_liquido"]

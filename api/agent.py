import json
import os
from openai import AsyncOpenAI

from tools.calculator import calcular_cenarios, CotaData
from tools.economic import get_economic_indicators, get_cub_history
from tools.comparables import get_comparable_units

MODEL = "anthropic/claude-opus-4-6"

SYSTEM_PROMPT = """Você é o Farol Pricing, especialista em precificação de cotas imobiliárias da Seazone.
Seu trabalho é ajudar investidores e consultores a encontrar o preço ideal de revenda de uma cota.

Antes de recomendar qualquer preço, você DEVE:
1. Buscar indicadores econômicos atuais (Selic, IPCA)
2. Buscar comparáveis reais (mesma tipologia, empreendimento)
3. Calcular ao menos 3 cenários de preço (conservador, justo, otimista)

Nunca invente números. Se os dados não estiverem disponíveis, diga explicitamente.
Responda sempre em português brasileiro com análise clara e fundamentada."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_economic_indicators",
            "description": "Retorna Selic atual, histórico de 6 meses e IPCA acumulado 12 meses via API do Banco Central.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cub_history",
            "description": "Retorna série histórica do CUB (Custo Unitário Básico) via Metabase.",
            "parameters": {
                "type": "object",
                "properties": {
                    "meses": {"type": "integer", "description": "Número de meses (default 12)"},
                    "estado": {"type": "string", "description": "Estado (default SC)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_comparable_units",
            "description": "Busca unidades similares no Metabase (mesmo empreendimento, tipologia, faixa de área).",
            "parameters": {
                "type": "object",
                "properties": {
                    "empreendimento_id": {"type": "integer"},
                    "tipologia": {"type": "string"},
                    "area_min": {"type": "number"},
                    "area_max": {"type": "number"},
                },
                "required": ["empreendimento_id", "tipologia", "area_min", "area_max"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_scenarios",
            "description": "Calcula 3 cenários de preço (conservador, justo, otimista) com ágio, ROI e valor líquido para o vendedor.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cota_data": {
                        "type": "object",
                        "description": "Dados da cota: empreendimento_id, empreendimento, codigo, area, valor_pago, saldo_devedor, tipologia, vista_mar, garden, sacada, posicao_solar, capacidade, participacao_pct, data_assinatura, imposto_pct.",
                    },
                    "selic_aa": {"type": "number", "description": "Taxa Selic anual em % (ex: 13.75)"},
                    "preco_sugerido": {"type": "number", "description": "Preço sugerido (opcional)"},
                },
                "required": ["cota_data", "selic_aa"],
            },
        },
    },
]


async def _execute_tool(name: str, arguments: str) -> tuple[str, dict | list | None]:
    inputs = json.loads(arguments)

    if name == "get_economic_indicators":
        result = await get_economic_indicators()
        return json.dumps(result, ensure_ascii=False), result

    if name == "get_cub_history":
        result = await get_cub_history(
            meses=inputs.get("meses", 12),
            estado=inputs.get("estado", "SC"),
        )
        return json.dumps(result, ensure_ascii=False), None

    if name == "get_comparable_units":
        result = await get_comparable_units(
            empreendimento_id=inputs["empreendimento_id"],
            tipologia=inputs["tipologia"],
            area_min=inputs["area_min"],
            area_max=inputs["area_max"],
        )
        return json.dumps(result, ensure_ascii=False), result

    if name == "calculate_scenarios":
        cota = CotaData(**inputs["cota_data"])
        result = calcular_cenarios(
            cota,
            selic_aa=inputs["selic_aa"],
            preco_sugerido=inputs.get("preco_sugerido"),
        )
        return json.dumps(result, ensure_ascii=False), result

    return json.dumps({"error": f"Tool desconhecida: {name}"}), None


async def run_agent(cota: dict, messages: list[dict]) -> dict:
    client = AsyncOpenAI(
        api_key=os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
    )

    cota_ctx = json.dumps(cota, ensure_ascii=False, indent=2)
    system = f"{SYSTEM_PROMPT}\n\n## Dados da cota em análise\n```json\n{cota_ctx}\n```"

    if not messages:
        messages = [{"role": "user", "content": "Qual o melhor preço para vender minha cota agora?"}]

    tool_calls_made: list[str] = []
    calculos: dict | None = None
    comparaveis: list | None = None
    indicadores: dict | None = None

    conversation = [{"role": "system", "content": system}] + list(messages)

    while True:
        response = await client.chat.completions.create(
            model=MODEL,
            max_tokens=4096,
            tools=TOOLS,
            messages=conversation,
        )

        msg = response.choices[0].message
        conversation.append(msg)

        finish_reason = response.choices[0].finish_reason
        if finish_reason != "tool_calls":
            final_text = msg.content or ""
            break

        # Processa tool calls
        tool_result_msgs = []
        for tc in msg.tool_calls:
            tool_calls_made.append(tc.function.name)
            result_json, structured = await _execute_tool(tc.function.name, tc.function.arguments)

            if tc.function.name == "get_economic_indicators" and structured:
                indicadores = structured
            elif tc.function.name == "get_comparable_units" and structured is not None:
                comparaveis = structured
            elif tc.function.name == "calculate_scenarios" and structured:
                calculos = structured

            tool_result_msgs.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_json,
            })

        conversation.extend(tool_result_msgs)

    return {
        "message": final_text,
        "tool_calls_made": tool_calls_made,
        "calculos": calculos,
        "comparaveis": comparaveis,
        "indicadores": indicadores,
    }

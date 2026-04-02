# Design: Agente de Precificação de Cotas — Hackathon Seazone

**Data:** 2026-04-01  
**Status:** Aprovado  
**Autor:** Farol (Claude Code)

---

## Contexto

O projeto hackathon-cotas é uma plataforma de revenda de cotas imobiliárias (fractional ownership) da Seazone. Investidores possuem participações em unidades dentro de empreendimentos e podem revendê-las no marketplace.

O avaliador sinalizou que o **agente de precificação é o diferencial ("ouro") do projeto**, pois precificar uma cota envolve variáveis complexas que uma planilha não resolve: características físicas da unidade, contexto econômico (Selic, IPCA, CUB), comparáveis reais de mercado, timing, e perfil do vendedor.

A implementação atual (`supabase/functions/price-agent/index.ts`) é uma calculadora com chat — faz os cálculos financeiros básicos e chama o Claude com o resultado. Não busca dados externos, não analisa comparáveis, não raciocina sobre timing.

**Objetivo:** Transformar o agente em um pricing advisor real, que usa ferramentas para buscar dados, raciocina sobre múltiplas variáveis e entrega recomendação fundamentada com cenários.

---

## Arquitetura

```
┌─────────────────────────────────────────────────────┐
│                   Demo UI (React)                   │
│         Chat + Cards de Cenários + Raciocínio       │
└──────────────────────┬──────────────────────────────┘
                       │ POST /api/price-agent
┌──────────────────────▼──────────────────────────────┐
│              FastAPI (Python 3.11)                  │
│                                                     │
│  ┌─────────────────────────────────────────────┐   │
│  │          Claude Agent (tool use loop)       │   │
│  │                                             │   │
│  │  ┌──────────────┐ ┌──────────┐ ┌─────────┐  │   │
│  │  │get_comparable│ │get_econ_ │ │calculate│  │   │
│  │  │    _units    │ │indicators│ │_scenario│  │   │
│  │  │  (Metabase)  │ │(BCB API) │ │  s(mat) │  │   │
│  │  └──────────────┘ └──────────┘ └─────────┘  │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
           │                │
     Metabase DB2         BCB API
     (SZI schema)      (Selic/IPCA)
```

**Stack:**
- Backend: Python 3.11 + FastAPI + `anthropic` SDK (tool use)
- Frontend: React via CDN (sem build step — arquivo único `index.html`)
- Deploy: `docker compose up` — dois containers (api:8000 + frontend:3000)
- Banco de dados dos investidores/cotas: Supabase (auth + RLS, já existente)
- Modelo: `claude-opus-4-6`

---

## Estrutura de Arquivos

```
hackathon-cotas/
├── api/
│   ├── main.py                 # FastAPI app + endpoints
│   ├── agent.py                # Loop de tool use com Claude
│   ├── tools/
│   │   ├── comparables.py      # Metabase DB2 → comparáveis
│   │   ├── economic.py         # BCB API (Selic, IPCA) + Metabase CUB
│   │   └── calculator.py       # Cálculos financeiros puros (sem I/O)
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── index.html              # Entry point
│   ├── App.jsx
│   └── components/
│       ├── CotaSelector.jsx    # Seleção da cota do investidor
│       ├── PricingChat.jsx     # Interface de chat + tool calls visíveis
│       └── ScenariosCard.jsx   # Cards de cenários (conservador/justo/otimista)
├── supabase/                   # (existente — mantido)
│   ├── schema.sql
│   └── functions/price-agent/
├── .env.example
├── docker-compose.yml
└── README.md
```

---

## Agent & Tools

### System Prompt

```
Você é o Farol Pricing, especialista em precificação de cotas imobiliárias 
da Seazone. Seu trabalho é ajudar investidores e consultores a encontrar o 
preço ideal de revenda de uma cota.

Antes de recomendar qualquer preço, você DEVE:
1. Buscar comparáveis reais (mesma tipologia, empreendimento próximo)
2. Verificar indicadores econômicos atuais (Selic, IPCA, CUB)
3. Calcular ao menos 3 cenários de preço (conservador, justo, otimista)

Nunca invente números. Se os dados não estiverem disponíveis, diga 
explicitamente. Responda sempre em português brasileiro.
```

### Ferramentas

| Ferramenta | Input | Output |
|---|---|---|
| `get_comparable_units` | `empreendimento_id`, `tipologia`, `area_min`, `area_max` | Lista de unidades similares: área, net_revenue, status, data_contrato |
| `get_economic_indicators` | — | Selic atual + histórico 6 meses, IPCA 12m |
| `get_cub_history` | `meses` (default: 12), `estado` | Série histórica CUB do Metabase `indexer_quotations` |
| `calculate_scenarios` | `cota_data`, `preco_sugerido` (opcional) | 3 cenários com: preço, ágio, ROI, líquido, preço mínimo |

**Detalhes `calculate_scenarios`:**

```python
valor_aquisicao = valor_pago + saldo_devedor
comissao_szn    = 0.06 * preco_venda
valor_entrada   = preco_venda - saldo_devedor
valor_liquido   = valor_entrada - comissao_szn - imposto
agio            = valor_liquido - valor_pago
roi             = (agio / valor_pago) * 100
preco_minimo    = valor_aquisicao / (1 - 0.06)

# Cenário conservador: preco_minimo + margem Selic pura
# Cenário justo:       preco_minimo + margem (Selic + 4pp)  ← padrão atual
# Cenário otimista:    preco_minimo + margem (Selic + 8pp) + premium características
```

O premium de características (vista_mar, garden, andar alto) eleva o cenário otimista em 3–8%.

### Output estruturado

```json
{
  "message": "string — análise em markdown com recomendação e raciocínio",
  "tool_calls_made": ["get_comparable_units", "get_economic_indicators", "calculate_scenarios"],
  "calculos": {
    "preco_minimo": 170213,
    "cenario_conservador": { "preco": 175000, "roi": 12.3, "liquido": 58200 },
    "cenario_justo":       { "preco": 195000, "roi": 28.1, "liquido": 74800 },
    "cenario_otimista":    { "preco": 220000, "roi": 46.2, "liquido": 95000 }
  },
  "comparaveis": [
    { "codigo": "209", "area": 15.52, "net_revenue": 30961, "tipologia": "padrao" }
  ],
  "indicadores": { "selic": 13.75, "ipca_12m": 4.83, "cub_variacao_12m": 6.2 }
}
```

---

## Modos de Uso

**Investidor (self-service):**
1. Login via Supabase (CPF → auth)
2. Frontend lista as cotas do investidor (RLS do Supabase)
3. Investidor seleciona cota → dados pré-preenchidos
4. Pergunta livre: *"Quanto devo pedir pela minha cota?"*
5. Agente retorna análise + cenários

**Consultor (advisory):**
1. Login com role `consultant` no Supabase
2. Busca investidor por CPF ou nome
3. Seleciona a cota do cliente
4. Usa o agente como ferramenta de apoio durante call
5. Perguntas mais técnicas são bem-vindas: *"Compare com Selic dos últimos 6 meses"*

---

## Dados da Cota (input do frontend)

Todos já presentes no schema Supabase existente — nenhum campo novo necessário:

```json
{
  "empreendimento_id": 42,
  "empreendimento_nome": "Seazone Resort Floripa",
  "codigo": "209",
  "area": 58.84,
  "andar": 2,
  "tipologia": "garden",
  "valor_pago": 100000,
  "saldo_devedor": 100000,
  "participacao_pct": 100.0,
  "vista_mar": "sim",
  "garden": true,
  "sacada": false,
  "posicao_solar": "nascente",
  "capacidade": 4,
  "data_assinatura": "2022-03-15"
}
```

---

## Deploy

**Para o avaliador — 3 comandos:**

```bash
cp .env.example .env
# editar .env: ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_ANON_KEY, METABASE_API_KEY
docker compose up --build
# acesse http://localhost:3000
```

**Variáveis de ambiente necessárias:**

```env
ANTHROPIC_API_KEY=sk-ant-...
SUPABASE_URL=https://snsdjvccgmlybcuwjgln.supabase.co
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_KEY=...
METABASE_URL=https://metabase.seazone.com.br
METABASE_API_KEY=mb_cBN...
```

---

## Script de Demo (para gravação)

1. Fazer login com CPF de investidor de teste
2. Selecionar cota: unit "209", garden, 58m², Empreendimento X
3. Digitar: *"Qual o melhor preço para vender minha cota agora?"*
4. Mostrar no UI: tool calls sendo executados em tempo real
5. Mostrar resultado: análise em markdown + cards de 3 cenários + comparáveis
6. Segunda pergunta: *"E se a Selic cair 2 pontos no próximo trimestre?"*
7. Agente reutiliza comparáveis (cache) e recalcula — resposta mais rápida

---

## Verificação

- [ ] `GET /health` retorna 200
- [ ] Tool `get_economic_indicators` retorna Selic atual real (via BCB)
- [ ] Tool `get_comparable_units` retorna ao menos 1 unidade do Metabase DB2
- [ ] Tool `calculate_scenarios` retorna 3 cenários com valores coerentes
- [ ] Conversa multi-turn mantém histórico (segunda pergunta usa contexto da primeira)
- [ ] Modo investidor: só vê próprias cotas (RLS Supabase)
- [ ] Modo consultor: pode buscar qualquer investidor
- [ ] Docker compose sobe sem erros com apenas as variáveis do `.env.example`

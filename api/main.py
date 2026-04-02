import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from agent import run_agent
from tools.comparables import get_empreendimentos, get_unidades_by_empreendimento

_HTML_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "index.html")

app = FastAPI(title="Farol Pricing API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class PriceAgentRequest(BaseModel):
    cota: dict
    messages: list[dict] = []


@app.get("/")
async def index():
    with open(_HTML_PATH) as f:
        return HTMLResponse(f.read())


@app.get("/debug-path")
async def debug_path():
    return {"msg": "debug-path GET works"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/config")
async def config():
    return {
        "supabase_url": os.getenv("SUPABASE_URL", ""),
        "supabase_service_key": os.getenv("SUPABASE_SERVICE_KEY", ""),
    }


@app.get("/empreendimentos")
async def empreendimentos():
    return await get_empreendimentos()


@app.get("/unidades/{empreendimento_id}")
async def unidades(empreendimento_id: int):
    return await get_unidades_by_empreendimento(empreendimento_id)


@app.post("/price-agent")
async def price_agent(req: PriceAgentRequest):
    result = await run_agent(cota=req.cota, messages=req.messages)
    return result



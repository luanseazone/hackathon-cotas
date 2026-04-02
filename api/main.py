from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os

from agent import run_agent

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


@app.get("/health")
async def health():
    return {"status": "ok"}



@app.post("/api/price-agent")
async def price_agent(req: PriceAgentRequest):
    result = await run_agent(cota=req.cota, messages=req.messages)
    return result

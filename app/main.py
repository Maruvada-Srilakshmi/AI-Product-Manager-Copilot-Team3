from fastapi import FastAPI
from pydantic import BaseModel
from app.agents.orchestrator import run_pipeline

app = FastAPI(title="AI PM Copilot Backend")

class PromptInput(BaseModel):
    prompt: str

@app.get("/")
def home():
    return {"status": "Backend Live"}

@app.post("/api/generate")
def generate_prd(data: PromptInput):
    result = run_pipeline(data.prompt)
    return {"response": str(result)}
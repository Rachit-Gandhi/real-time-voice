from fastapi import FastAPI
from app.routes.agent_one import router

app = FastAPI(title="Agent One")
app.include_router(router)

from fastapi import FastAPI
from app.routes.agent_one import router
from app.routes.l1_support import router as l1_support_router

app = FastAPI(title="Agent One")
app.include_router(router)
app.include_router(l1_support_router)

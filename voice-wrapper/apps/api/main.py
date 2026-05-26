"""FastAPI application entry point."""
from fastapi import FastAPI
from apps.api.routes.voice import router as voice_router

app = FastAPI(title="Voice Wrapper API")
app.include_router(voice_router)

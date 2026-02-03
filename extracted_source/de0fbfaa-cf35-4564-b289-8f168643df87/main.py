from fastapi import FastAPI
from routes import router

app = FastAPI(title="Simple Notes API")

app.include_router(router)

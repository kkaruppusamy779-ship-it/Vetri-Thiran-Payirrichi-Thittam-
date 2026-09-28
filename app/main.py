# app/main.py

from fastapi import FastAPI
from sqlalchemy import inspect, text

from app.config import APP_NAME, APP_VERSION
from app.database.database import Base, engine
from app.database import models
from app.routes import router

Base.metadata.create_all(bind=engine)
if "updated_plan" not in {column["name"] for column in inspect(engine).get_columns("workout_plans")}:
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE workout_plans ADD COLUMN updated_plan TEXT"))

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="AI fitness plan generator powered by Gemini",
)
app.include_router(router)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "application": APP_NAME, "version": APP_VERSION}
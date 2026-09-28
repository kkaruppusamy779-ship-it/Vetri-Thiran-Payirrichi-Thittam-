import os

from dotenv import load_dotenv

load_dotenv()

APP_NAME = os.getenv("APP_NAME", "FitBuddy AI")
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./fitbuddy.db")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
WORKOUT_MODEL = os.getenv("WORKOUT_MODEL", "gemini-2.5-flash")
NUTRITION_MODEL = os.getenv("NUTRITION_MODEL", "gemini-2.5-flash")
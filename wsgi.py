"""
Point d'entrée WSGI.
"""
import os
from pathlib import Path

# ── DOIT être en tout premier, avant tout import Flask/app ───────────────────
try:
    from dotenv import load_dotenv
    _env_file = Path(__file__).resolve().parent / ".env"
    if _env_file.exists():
        load_dotenv(_env_file)
except ImportError:
    pass

# ── Imports après chargement du .env ────────────────────────────────────────
from app import create_app

_env = os.getenv("APP_ENV", "development")
application = create_app(_env)

if __name__ == "__main__":
    application.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000)),
        debug=(_env == "development"),
    )
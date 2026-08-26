import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except Exception:
    pass

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
LICENSE_SECRET = os.getenv("LICENSE_SECRET", "AutoToolLicenseSecret_ChangeMe_2026").encode()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin@123")
PORT = int(os.getenv("PORT", "8001"))
HOST = os.getenv("HOST", "0.0.0.0")
SESSION_TTL = int(os.getenv("SESSION_TTL", "43200"))
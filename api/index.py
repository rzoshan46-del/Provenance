import sys
import os
from pathlib import Path

# Add project root to sys.path so 'app' package is found on Vercel Lambda
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Ensure database path is in writable /tmp on Vercel
if os.environ.get("VERCEL") and not os.environ.get("PROVENANCE_DB"):
    os.environ["PROVENANCE_DB"] = "/tmp/app.db"

try:
    from app.main import app as fastapi_app
    app = fastapi_app
    handler = fastapi_app
except Exception as e:
    import traceback
    traceback.print_exc()
    raise e

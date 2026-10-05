"""
Single-Command Launcher for Fullstack Starter Template.
======================================================
Initializes the SQLite database and starts the FastAPI server on port 8000.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add current directory to path
starter_root = Path(__file__).resolve().parent
if str(starter_root) not in sys.path:
    sys.path.insert(0, str(starter_root))

from database import DEFAULT_DB_PATH, init_database


def main() -> None:
    print("=" * 60)
    print("⚡ Query-Builder Fullstack Starter Template")
    print("=" * 60)

    # 1. Initialize SQLite database
    print(f"[*] Initializing SQLite database at: {DEFAULT_DB_PATH}")
    init_database(DEFAULT_DB_PATH)
    print("[+] Database seeded with categories, products, users, orders.")

    # 2. Inform user about frontend
    print("\nTo start the React frontend:")
    print("  cd frontend")
    print("  pnpm install && pnpm dev\n")

    # 3. Launch FastAPI server
    print("[*] Launching FastAPI backend server on http://127.0.0.1:8000")
    print("    - Health Check: http://127.0.0.1:8000/health")
    print("    - Schema API:   http://127.0.0.1:8000/api/schema")
    print("    - Swagger Docs: http://127.0.0.1:8000/docs\n")

    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()

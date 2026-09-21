"""Removed legacy Flask authentication server.

The old server duplicated account routes without JWT authorization and must
not be run. VidFusion now has one secured API in ``backend.main``.
"""

if __name__ == "__main__":
    raise SystemExit(
        "auth_backend.py is retired for security. Run: "
        "uvicorn backend.main:app --host 127.0.0.1 --port 8000"
    )

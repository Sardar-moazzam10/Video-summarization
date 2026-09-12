import sys
sys.path.insert(0, '/home/weiblocks/Desktop/Video-summarization')
from fastapi.testclient import TestClient
from backend.main import app, rate_limit_store

client = TestClient(app)
rate_limit_store.clear()

for i in range(60):
    client.get("/health")

response = client.get("/health")
assert response.status_code == 429
assert response.json()["detail"] == "Too many requests. Please wait a minute."
print("TEST PASSED: Rate limit returns JSONResponse without UnboundLocalError")

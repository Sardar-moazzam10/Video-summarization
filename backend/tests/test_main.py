import pytest
from fastapi.testclient import TestClient
from backend.main import app, rate_limit_store

client = TestClient(app)

def test_rate_limit_middleware_jsonresponse_scoping():
    """
    Regression test to ensure rate_limit_middleware returns its JSONResponse 
    without throwing UnboundLocalError when rate limit is exceeded.
    """
    # Clear the rate limit store before test
    rate_limit_store.clear()
    
    # Hit the API 60 times to trigger the limit
    for i in range(60):
        # We can hit a non-existent endpoint, it will just 404, but it triggers the middleware
        client.get("/non-existent-endpoint")
        
    # The 61st request should trigger the 429 response, NOT an UnboundLocalError
    response = client.get("/non-existent-endpoint")
    
    assert response.status_code == 429
    assert response.json()["detail"] == "Too many requests. Please wait a minute."

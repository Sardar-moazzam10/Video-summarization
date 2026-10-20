import pytest
from backend.main import rate_limit_store

@pytest.fixture(autouse=True)
def reset_rate_limit_store():
    """Ensure in-memory rate limiting does not leak state across test cases."""
    rate_limit_store.clear()
    yield
    rate_limit_store.clear()


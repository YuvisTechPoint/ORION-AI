import pytest
from fastapi.testclient import TestClient

from main import app
from api import auth


# Mock session data
MOCK_SESSION = {
    "authenticated": True,
    "github_username": "test-user",
    "github_token": "test-github-token",
    "github_email": "test@example.com",
    "token_scope": "repo,read:user,user:email",
}


async def mock_require_auth(request):
    """Mock require_auth dependency for tests."""
    return MOCK_SESSION


async def mock_get_github_token(request):
    """Mock get_github_token dependency for tests."""
    return "test-github-token"


@pytest.fixture
def authenticated_client():
    """Provide a test client with authentication dependencies overridden."""
    # Override the dependency in the app
    app.dependency_overrides[auth.require_auth] = mock_require_auth
    app.dependency_overrides[auth.get_github_token] = mock_get_github_token
    
    client = TestClient(app)
    yield client
    
    # Clean up overrides after test
    app.dependency_overrides.clear()



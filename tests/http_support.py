"""Real ASGI client using the fixture's explicit paths, never personal data."""
from fastapi.testclient import TestClient
from app.config import AppConfig
from app.main import create_app


def client(bridge=None):
    import database_fixture as server
    config = AppConfig(server.ROOT, server.DATA, server.DIST, server.DB_PATH)
    return TestClient(create_app(config, bridge=bridge, agent_factory=None, manage_agent=False),
                      base_url='http://127.0.0.1')

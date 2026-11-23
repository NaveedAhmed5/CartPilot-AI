"""Test fixtures.

The API tests need a real Postgres (memory must survive across requests). They use
a throw-away database `cartpilot_test` on the server in TEST_DATABASE_URL (default:
the docker-compose Postgres on localhost:55432). The LLM is replaced by a scripted
fake model, so the suite is deterministic and costs nothing.
"""

import os
from typing import Any, Callable, List, Optional

import psycopg
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

ADMIN_URL = os.getenv("TEST_DATABASE_ADMIN_URL", "postgresql://postgres:postgres@localhost:55432/postgres")
TEST_DB = "cartpilot_test"
TEST_URL = ADMIN_URL.rsplit("/", 1)[0] + "/" + TEST_DB

os.environ["DATABASE_URL"] = TEST_URL
os.environ["LLM_PROVIDER"] = "anthropic"  # never used: the model is overridden
os.environ["SEED_DEMO_DATA"] = "true"
os.environ["ADMIN_PASSWORD"] = "test-admin"
os.environ["SECRET_KEY"] = "test-secret"


class ScriptedModel(BaseChatModel):
    """Fake chat model: `responder(messages)` returns the next AIMessage."""

    responder: Callable[[List[BaseMessage]], AIMessage]
    calls: List[List[BaseMessage]] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedModel":
        return self

    def _generate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None, **kwargs: Any) -> ChatResult:
        self.calls.append(list(messages))
        msg = self.responder(messages)
        if msg.usage_metadata is None:
            msg.usage_metadata = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
        return ChatResult(generations=[ChatGeneration(message=msg)])


def _db_reachable() -> bool:
    try:
        with psycopg.connect(ADMIN_URL, connect_timeout=3):
            return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def client():
    if not _db_reachable():
        pytest.skip("Postgres not reachable; start it with `docker compose up -d db`")
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE);")
        conn.execute(f"CREATE DATABASE {TEST_DB};")

    from fastapi.testclient import TestClient

    from app import llm
    from app.agent import graph as graph_module
    from app.main import app

    holder = {"responder": lambda msgs: AIMessage(content="Hello from CartPilot!")}
    model = ScriptedModel(responder=lambda msgs: holder["responder"](msgs))
    llm.set_model_override(model)
    graph_module.reset_model()
    with TestClient(app) as c:
        c.script = holder  # type: ignore[attr-defined]
        c.model = model  # type: ignore[attr-defined]
        yield c
    llm.set_model_override(None)
    graph_module.reset_model()

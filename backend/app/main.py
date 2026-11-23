"""CartPilot API.

Public (no login, used by the automated grader):
    POST /chat     {"user_id", "thread_id", "message"} -> {"reply", "tool_calls", "tokens": {"in", "out"}}
    GET  /health   -> ok

Website API (under /api): storefront catalog, customer account (bearer token) and
admin dashboard (admin bearer token).
"""

import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator

from . import database as db
from . import llm
from .agent import service
from .auth import (
    check_admin_password, current_user, hash_password, make_token, require_admin, verify_password,
)
from .config import PRICE_IN_PER_MTOK, PRICE_OUT_PER_MTOK, settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("cartpilot.api")


def _startup() -> None:
    from langgraph.checkpoint.postgres import PostgresSaver

    from .seed import seed_demo_data

    last_err: Optional[Exception] = None
    for attempt in range(1, 6):
        try:
            with db.get_db_connection() as conn:
                db.create_tables(conn)
                db.seed_products(conn)
            if settings.seed_demo_data:
                seed_demo_data()
            saver = PostgresSaver(db.get_pool())
            saver.setup()
            service.init_agent(saver)
            log.info("CartPilot ready (LLM provider: %s)", llm.provider())
            return
        except Exception as e:  # cold Neon/Supabase instances can take a few seconds
            last_err = e
            log.warning("Startup attempt %d failed: %s", attempt, e)
            time.sleep(min(2 * attempt, 8))
    raise RuntimeError(f"Could not initialise database: {last_err}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await run_in_threadpool(_startup)
    yield
    db.close_pool()


app = FastAPI(title="CartPilot API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    errors = [
        {"field": ".".join(str(p) for p in e.get("loc", []) if p != "body"), "message": e.get("msg")}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"error": "invalid_request", "details": errors})


@app.exception_handler(Exception)
async def unhandled_error(_: Request, exc: Exception):
    log.exception("Unhandled error: %s", exc)
    return JSONResponse(status_code=500, content={"error": "internal_error"})


# ------------------------------------------------------------------- grading API
class ChatRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=128)
    thread_id: str = Field(..., min_length=1, max_length=128)
    message: str = Field(..., max_length=8000)

    @field_validator("user_id", "thread_id", mode="before")
    @classmethod
    def _coerce_id(cls, v: Any) -> Any:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            v = str(v)
        return v.strip() if isinstance(v, str) else v

    @field_validator("message", mode="before")
    @classmethod
    def _coerce_msg(cls, v: Any) -> Any:
        return "" if v is None else v


class ChatResponse(BaseModel):
    reply: str
    tool_calls: List[Dict[str, Any]]
    tokens: Dict[str, int]


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> Dict[str, Any]:
    if not req.user_id or not req.thread_id:
        raise HTTPException(422, "user_id and thread_id must be non-empty")
    return service.chat(req.user_id, req.thread_id, req.message)


@app.get("/health", response_class=PlainTextResponse)
def health() -> str:
    return "ok"


@app.get("/health/ready")
def ready() -> Dict[str, Any]:
    try:
        db_ok = db.ping()
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok, "llm_provider": llm.provider()}


@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "name": "CartPilot API",
        "description": "AI sales agent for CartPilot Streetwear (ShopBot track)",
        "endpoints": {"chat": "POST /chat", "health": "GET /health", "docs": "/docs"},
    }


# --------------------------------------------------------------------- storefront
@app.get("/api/products")
def list_products(q: Optional[str] = None, category: Optional[str] = None) -> List[Dict[str, Any]]:
    if q or category:
        return db.search_products(q, category, limit=100)
    return db.get_products()


@app.get("/api/products/{product_id}")
def product_detail(product_id: int) -> Dict[str, Any]:
    p = db.get_product_by_id(product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    return p


@app.get("/api/policies")
def policies() -> Dict[str, str]:
    from .agent.tools import POLICIES

    return POLICIES


# ----------------------------------------------------------------------- accounts
class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(..., min_length=6, max_length=128)
    display_name: Optional[str] = Field(None, max_length=100)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


def _session(username: str, display_name: Optional[str]) -> Dict[str, Any]:
    return {"token": make_token(username, "user"), "user": {"username": username, "display_name": display_name}}


@app.post("/api/auth/register")
def register(req: RegisterRequest) -> Dict[str, Any]:
    username = req.username.lower()
    if username.startswith("guest-"):
        raise HTTPException(400, "This username is reserved")
    if not db.create_user(username, hash_password(req.password), req.display_name or req.username):
        raise HTTPException(409, "Username already taken")
    return _session(username, req.display_name or req.username)


@app.post("/api/auth/login")
def login(req: LoginRequest) -> Dict[str, Any]:
    user = db.get_user(req.username.lower())
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(401, "Wrong username or password")
    return _session(user["username"], user["display_name"])


@app.get("/api/me")
def me(user_id: str = Depends(current_user)) -> Dict[str, Any]:
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(401, "Account no longer exists")
    return {"username": user["username"], "display_name": user["display_name"], "memory": db.get_user_memory(user_id)}


@app.get("/api/me/orders")
def my_orders(user_id: str = Depends(current_user)) -> List[Dict[str, Any]]:
    return db.list_user_orders(user_id, limit=50)


@app.get("/api/me/memory")
def my_memory(user_id: str = Depends(current_user)) -> Dict[str, Any]:
    return {"memory": db.get_user_memory(user_id)}


@app.delete("/api/me/memory")
def forget_me(user_id: str = Depends(current_user)) -> Dict[str, Any]:
    return {"deleted": db.delete_user_memory(user_id)}


@app.get("/api/me/threads")
def my_threads(user_id: str = Depends(current_user)) -> List[Dict[str, Any]]:
    return db.list_user_threads(user_id)


@app.get("/api/me/threads/{thread_id}")
def my_thread(thread_id: str, user_id: str = Depends(current_user)) -> List[Dict[str, Any]]:
    return db.get_thread_log(user_id, thread_id)


# -------------------------------------------------------------------------- admin
class AdminLoginRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=256)


class ProductIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    description: str = Field("", max_length=2000)
    price: float = Field(..., gt=0, le=10_000_000)
    category: str = Field(..., min_length=2, max_length=100)
    sizes: List[str] = Field(..., min_length=1, max_length=20)
    stock: int = Field(0, ge=0, le=1_000_000)
    is_active: bool = True


class ProductPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    price: Optional[float] = Field(None, gt=0, le=10_000_000)
    category: Optional[str] = Field(None, min_length=2, max_length=100)
    sizes: Optional[List[str]] = Field(None, min_length=1, max_length=20)
    stock: Optional[int] = Field(None, ge=0, le=1_000_000)
    is_active: Optional[bool] = None


class OrderStatusPatch(BaseModel):
    status: str


@app.post("/api/admin/login")
def admin_login(req: AdminLoginRequest) -> Dict[str, Any]:
    if not check_admin_password(req.password):
        raise HTTPException(401, "Wrong admin password")
    return {"token": make_token("admin", "admin")}


@app.get("/api/admin/stats")
def admin_stats(_: str = Depends(require_admin)) -> Dict[str, Any]:
    stats = db.admin_stats()
    c = stats["chats"]
    c["est_cost_usd"] = round(
        c.get("tokens_in", 0) / 1e6 * PRICE_IN_PER_MTOK + c.get("tokens_out", 0) / 1e6 * PRICE_OUT_PER_MTOK, 4
    )
    stats["llm_provider"] = llm.provider()
    stats["model"] = settings.claude_model if llm.provider() == "anthropic" else llm.provider()
    return stats


@app.get("/api/admin/orders")
def admin_orders(status: Optional[str] = None, _: str = Depends(require_admin)) -> List[Dict[str, Any]]:
    return db.admin_list_orders(status)


@app.patch("/api/admin/orders/{order_id}")
def admin_order_status(order_id: int, body: OrderStatusPatch, _: str = Depends(require_admin)) -> Dict[str, Any]:
    try:
        order = db.admin_update_order_status(order_id, body.status)
    except db.OrderError as e:
        raise HTTPException(400, str(e))
    if not order:
        raise HTTPException(404, "Order not found")
    return order


@app.get("/api/admin/products")
def admin_products(_: str = Depends(require_admin)) -> List[Dict[str, Any]]:
    return db.get_products(include_inactive=True)


@app.post("/api/admin/products")
def admin_create_product(body: ProductIn, _: str = Depends(require_admin)) -> Dict[str, Any]:
    data = body.model_dump()
    data["sizes"] = [s.strip() for s in data["sizes"] if s.strip()]
    if not data["sizes"]:
        raise HTTPException(422, "At least one size is required")
    return db.create_product(data)


@app.put("/api/admin/products/{product_id}")
def admin_update_product(product_id: int, body: ProductPatch, _: str = Depends(require_admin)) -> Dict[str, Any]:
    data = body.model_dump(exclude_none=True)
    if "sizes" in data:
        data["sizes"] = [s.strip() for s in data["sizes"] if s.strip()]
        if not data["sizes"]:
            raise HTTPException(422, "At least one size is required")
    p = db.update_product(product_id, data)
    if not p:
        raise HTTPException(404, "Product not found")
    return p


@app.delete("/api/admin/products/{product_id}")
def admin_delete_product(product_id: int, _: str = Depends(require_admin)) -> Dict[str, Any]:
    if not db.delete_product(product_id):
        raise HTTPException(404, "Product not found")
    return {"archived": True}


@app.get("/api/admin/conversations")
def admin_conversations(
    user_id: Optional[str] = None,
    blocked_only: bool = False,
    limit: int = Query(100, ge=1, le=500),
    _: str = Depends(require_admin),
) -> List[Dict[str, Any]]:
    return db.admin_list_chats(user_id, blocked_only, limit)


@app.get("/api/admin/customers")
def admin_customers(_: str = Depends(require_admin)) -> List[Dict[str, Any]]:
    return db.admin_list_customers()

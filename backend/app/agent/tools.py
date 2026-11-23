"""The sales agent's tools.

Schemas are bound to the model; execution happens in the graph's `tools` node,
which passes a ToolContext built from graph state. The model never supplies a
user_id, so every data access is scoped to the user who sent the message.

Risky actions (placing an order, cancelling an order, deleting saved data) are
two-step and enforced in code: the first call only *prepares* the action and stores
it as `pending_action`. It runs only when `confirm_pending_action` is called on the
customer's very next message and that message is an unambiguous "yes".
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from .. import database as db
from .memory import format_profile
from .safety import is_confirmation

CATEGORIES = "Hoodies, T-Shirts, Bottoms, Outerwear, Footwear, Accessories"

POLICIES: Dict[str, str] = {
    "shipping": (
        "Shipping: nationwide delivery in Pakistan via TCS and Leopards. Karachi, Lahore, Islamabad and "
        "Rawalpindi: 2-3 working days; all other cities: 3-5 working days. Flat PKR 250 shipping, FREE on "
        "orders of PKR 5,000 or more. Orders confirmed before 3 PM dispatch the same day. A tracking "
        "number is sent by SMS once the order ships."
    ),
    "returns": (
        "Returns & exchanges: 7 days from delivery for unworn items with tags attached. Size exchanges are "
        "free (we cover one return shipment). Refunds go to bank account, JazzCash or Easypaisa within 5 "
        "working days after the item is inspected. Caps and beanies are final sale unless defective. "
        "Customers can cancel an order themselves while it is 'pending' or 'confirmed' (before it ships)."
    ),
    "payment": (
        "Payment: Cash on Delivery (COD) nationwide. Bank transfer, JazzCash and Easypaisa are also accepted; "
        "account details are sent by SMS after the order. We never ask for card numbers or passwords in chat."
    ),
    "sizing": (
        "Sizing: oversized and boxy styles run one size large, so size down for a regular fit. Chest (inches): "
        "S 38-40, M 40-42, L 42-44, XL 44-46, XXL 46-48. Bottoms waist (inches): S 28-30, M 30-32, L 32-34, "
        "XL 34-36. Sneakers use EU sizes 40-45. Caps, beanies and bags are One Size."
    ),
    "discounts": (
        "Discounts: code WELCOME10 gives 10% off the subtotal of a customer's FIRST order. Free shipping on "
        "orders of PKR 5,000 or more. No other codes are active."
    ),
    "contact": (
        "Contact: WhatsApp and email support (support@cartpilot.example), Monday-Saturday 10 AM - 7 PM PKT. "
        "Most questions can be handled right here in chat."
    ),
}


# ---------------------------------------------------------------------------- schemas
class SearchProductsInput(BaseModel):
    query: Optional[str] = Field(None, description="Keywords, e.g. 'black hoodie', 'summer tee', 'cargo'.")
    category: Optional[str] = Field(None, description=f"One of: {CATEGORIES}.")
    max_price: Optional[float] = Field(None, description="Maximum price in PKR.")
    size: Optional[str] = Field(None, description="Only products available in this size, e.g. 'M' or '42'.")
    in_stock_only: bool = Field(False, description="Exclude sold-out products.")


class GetProductDetailsInput(BaseModel):
    product_id: int = Field(..., description="Product ID from search results.")


class GetStorePolicyInput(BaseModel):
    topic: Literal["shipping", "returns", "payment", "sizing", "discounts", "contact", "all"] = Field(
        ..., description="Policy topic."
    )


class OrderItem(BaseModel):
    product_id: int = Field(..., description="Product ID.")
    size: str = Field(..., description="Size exactly as listed for the product (e.g. 'M', '42', 'One Size').")
    quantity: int = Field(1, ge=1, le=10, description="Quantity, 1-10.")


class PlaceOrderInput(BaseModel):
    items: List[OrderItem] = Field(..., min_length=1, max_length=10, description="Items to order.")
    customer_name: str = Field(..., min_length=2, description="Recipient's full name.")
    phone: str = Field(..., description="Pakistani mobile number, e.g. 03001234567.")
    shipping_address: str = Field(..., min_length=8, description="Full street address.")
    city: str = Field(..., min_length=2, description="Delivery city.")
    discount_code: Optional[str] = Field(None, description="Optional discount code, e.g. WELCOME10.")


class NoArgs(BaseModel):
    pass


class GetMyOrdersInput(BaseModel):
    order_id: Optional[int] = Field(None, description="A specific order number; omit to list recent orders.")


class CancelOrderInput(BaseModel):
    order_id: int = Field(..., description="The customer's order number to cancel.")


class SavePreferenceInput(BaseModel):
    name: Optional[str] = Field(None, description="Customer's preferred name.")
    preferred_size: Optional[str] = Field(None, description="Usual clothing size, e.g. 'M'.")
    city: Optional[str] = Field(None, description="Home / delivery city.")
    budget: Optional[str] = Field(None, description="Typical budget, e.g. 'PKR 5000'.")
    style_notes: Optional[str] = Field(
        None, description="Short lasting style preference, e.g. 'likes oversized fits; prefers black'."
    )


# ------------------------------------------------------------------------- execution
@dataclass
class ToolContext:
    user_id: str
    turn: int
    user_message: str
    pending_action: Optional[Dict[str, Any]] = None


@dataclass
class ToolOutcome:
    content: str
    is_error: bool = False
    # Set when the tool changes the pending action. Use CLEAR to remove it.
    pending_action: Any = field(default=None)


CLEAR = object()


def _j(obj: Any) -> str:
    return db.to_json(obj)


def _money(v: float) -> str:
    return f"PKR {v:,.0f}"


def _summarize_product(p: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": p["id"], "name": p["name"], "category": p["category"], "price_pkr": p["price"],
        "sizes": p["sizes"], "in_stock": p["stock"] > 0, "stock": p["stock"],
    }


def _search_products(args: SearchProductsInput, ctx: ToolContext) -> ToolOutcome:
    out: Dict[str, Any] = {}
    results = db.search_products(args.query, args.category, args.max_price, args.size, args.in_stock_only)
    if not results and args.query:
        # Relax the keywords before giving up (e.g. a colour we don't stock).
        results = db.search_products(None, args.category, args.max_price, args.size, args.in_stock_only)
        if results:
            out["note"] = f"No exact match for '{args.query}'. Closest available products:"
    if args.query:
        # Never hide that a requested product exists but is sold out.
        all_matches = db.search_products(args.query, args.category, args.max_price, args.size, False)
        sold_out = [p for p in all_matches if p["stock"] <= 0]
        if sold_out:
            out["sold_out_matches"] = [{"id": p["id"], "name": p["name"]} for p in sold_out]
            out["sold_out_note"] = "These products match but are SOLD OUT: tell the customer and suggest in-stock alternatives."
            results = [p for p in results if p["stock"] > 0]
    out["products"] = [_summarize_product(p) for p in results]
    if not results and "sold_out_matches" not in out:
        out["note"] = "No products match. Suggest other categories."
    return ToolOutcome(_j(out))


def _get_product_details(args: GetProductDetailsInput, ctx: ToolContext) -> ToolOutcome:
    p = db.get_product_by_id(args.product_id)
    if not p:
        return ToolOutcome(f"Product #{args.product_id} not found.", is_error=True)
    out = _summarize_product(p)
    out["description"] = p["description"]
    return ToolOutcome(_j(out))


def _get_store_policy(args: GetStorePolicyInput, ctx: ToolContext) -> ToolOutcome:
    if args.topic == "all":
        return ToolOutcome("\n".join(POLICIES.values()))
    return ToolOutcome(POLICIES[args.topic])


def _normalize_phone(phone: str) -> Optional[str]:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("0092"):
        digits = digits[2:]
    if digits.startswith("92") and len(digits) == 12:
        digits = "0" + digits[2:]
    if len(digits) == 10 and digits.startswith("3"):
        digits = "0" + digits
    return digits if re.fullmatch(r"03\d{9}", digits) else None


def _order_summary(quote: Dict[str, Any], args: PlaceOrderInput, phone: str) -> str:
    lines = [f"- {i['name']} (size {i['size']}) x{i['quantity']} = {_money(i['line_total'])}" for i in quote["items"]]
    parts = ["\n".join(lines), f"Subtotal: {_money(quote['subtotal'])}"]
    if quote["discount"]:
        parts.append(f"Discount ({quote['discount_code']}): -{_money(quote['discount'])}")
    parts.append(f"Shipping: {'FREE' if not quote['shipping_fee'] else _money(quote['shipping_fee'])}")
    parts.append(f"Total (Cash on Delivery): {_money(quote['total'])}")
    parts.append(f"Deliver to: {args.customer_name}, {args.shipping_address}, {args.city} | Phone: {phone}")
    return "\n".join(parts)


def _place_order(args: PlaceOrderInput, ctx: ToolContext) -> ToolOutcome:
    phone = _normalize_phone(args.phone)
    if not phone:
        return ToolOutcome(
            "Invalid phone number. Ask the customer for a Pakistani mobile number like 03001234567.", is_error=True
        )
    items = [i.model_dump() for i in args.items]
    try:
        quote = db.quote_order(ctx.user_id, items, args.discount_code)
    except db.OrderError as e:
        return ToolOutcome(f"Cannot prepare order: {e}", is_error=True)
    summary = _order_summary(quote, args, phone)
    pending = {
        "type": "place_order",
        "turn": ctx.turn,
        "summary": summary,
        "payload": {
            "items": items, "shipping_address": args.shipping_address.strip(), "city": args.city.strip(),
            "phone": phone, "customer_name": args.customer_name.strip(), "discount_code": args.discount_code,
        },
    }
    return ToolOutcome(
        "CONFIRMATION REQUIRED - the order has NOT been placed yet. Show this summary to the customer and ask "
        "them to reply 'yes' to confirm or tell you what to change:\n" + summary,
        pending_action=pending,
    )


def _cancel_order(args: CancelOrderInput, ctx: ToolContext) -> ToolOutcome:
    orders = db.list_user_orders(ctx.user_id, args.order_id)
    if not orders:
        return ToolOutcome(f"The customer has no order #{args.order_id}.", is_error=True)
    order = orders[0]
    if order["status"] not in db.CANCELLABLE_STATUSES:
        return ToolOutcome(
            f"Order #{order['id']} is '{order['status']}' and can no longer be cancelled. "
            "Offer the 7-day return policy instead if it was delivered.",
            is_error=True,
        )
    items = ", ".join(f"{i['name']} ({i['size']}) x{i['quantity']}" for i in order["items"] or [])
    summary = f"Cancel order #{order['id']}: {items} - total {_money(float(order['total_price']))}."
    pending = {"type": "cancel_order", "turn": ctx.turn, "summary": summary, "payload": {"order_id": order["id"]}}
    return ToolOutcome(
        "CONFIRMATION REQUIRED - nothing has been cancelled yet. Ask the customer to reply 'yes' to confirm:\n"
        + summary,
        pending_action=pending,
    )


def _forget_my_data(args: NoArgs, ctx: ToolContext) -> ToolOutcome:
    summary = "Permanently delete the customer's saved preferences (long-term memory). Orders are kept."
    pending = {"type": "forget_memory", "turn": ctx.turn, "summary": summary, "payload": {}}
    return ToolOutcome(
        "CONFIRMATION REQUIRED - nothing has been deleted yet. Ask the customer to reply 'yes' to confirm:\n"
        + summary,
        pending_action=pending,
    )


def _confirm_pending_action(args: NoArgs, ctx: ToolContext) -> ToolOutcome:
    pending = ctx.pending_action
    if not pending:
        return ToolOutcome("There is no pending action to confirm. Prepare the action first.", is_error=True)
    if pending.get("turn") == ctx.turn:
        return ToolOutcome(
            "Not allowed yet: the customer must confirm in their NEXT message after seeing the summary. "
            "Show the summary and ask them to reply 'yes'.",
            is_error=True,
        )
    if pending.get("turn") != ctx.turn - 1:
        return ToolOutcome(
            "The pending action expired because the conversation moved on. Prepare it again and re-confirm.",
            is_error=True, pending_action=CLEAR,
        )
    if not is_confirmation(ctx.user_message, pending.get("type")):
        return ToolOutcome(
            "The customer has NOT clearly confirmed (their message was not an unambiguous yes). Do not proceed; "
            "ask them to reply 'yes' to confirm or say what to change.",
            is_error=True,
        )
    kind, payload = pending["type"], pending["payload"]
    try:
        if kind == "place_order":
            order = db.create_order(ctx.user_id, **payload)
            return ToolOutcome(_j({
                "result": "ORDER PLACED", "order_id": order["id"], "status": order["status"],
                "total_pkr": order["total_price"], "payment": "Cash on Delivery",
                "delivery_estimate": "2-3 working days (major cities) / 3-5 working days (other cities)",
            }), pending_action=CLEAR)
        if kind == "cancel_order":
            order = db.cancel_user_order(ctx.user_id, int(payload["order_id"]))
            return ToolOutcome(_j({"result": "ORDER CANCELLED", "order_id": order["id"]}), pending_action=CLEAR)
        if kind == "forget_memory":
            db.delete_user_memory(ctx.user_id)
            return ToolOutcome(_j({"result": "SAVED PREFERENCES DELETED"}), pending_action=CLEAR)
    except db.OrderError as e:
        return ToolOutcome(f"Action failed: {e}", is_error=True, pending_action=CLEAR)
    return ToolOutcome(f"Unknown pending action '{kind}'.", is_error=True, pending_action=CLEAR)


def _get_my_orders(args: GetMyOrdersInput, ctx: ToolContext) -> ToolOutcome:
    orders = db.list_user_orders(ctx.user_id, args.order_id, limit=5)
    if not orders:
        msg = f"No order #{args.order_id} found for this customer." if args.order_id else "This customer has no orders yet."
        return ToolOutcome(msg)
    out = [
        {
            "order_id": o["id"], "status": o["status"], "placed": (o["created_at"] or "")[:10],
            "items": [f"{i['name']} ({i['size']}) x{i['quantity']}" for i in (o["items"] or [])],
            "total_pkr": o["total_price"], "city": o["city"],
        }
        for o in orders
    ]
    return ToolOutcome(_j({"orders": out}))


def _save_user_preference(args: SavePreferenceInput, ctx: ToolContext) -> ToolOutcome:
    data = {k: (v.strip() if isinstance(v, str) else v) for k, v in args.model_dump().items()}
    data = {k: v for k, v in data.items() if v}
    if not data:
        return ToolOutcome("Nothing to save.", is_error=True)
    if "preferred_size" in data:
        data["preferred_size"] = data["preferred_size"].upper()[:20]
    profile = db.upsert_user_memory(ctx.user_id, **data)
    return ToolOutcome("Saved. Current profile: " + format_profile(profile))


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    schema: type
    handler: Callable[[Any, ToolContext], ToolOutcome]


TOOL_SPECS: List[ToolSpec] = [
    ToolSpec(
        "search_products",
        "Search the live product catalog by keywords, category, max price and/or size. Returns id, name, "
        "price, sizes and stock. Use before recommending anything.",
        SearchProductsInput, _search_products,
    ),
    ToolSpec(
        "get_product_details",
        "Get full details (description, sizes, stock, price) for one product ID.",
        GetProductDetailsInput, _get_product_details,
    ),
    ToolSpec(
        "get_store_policy",
        "Look up official store policy: shipping, returns, payment, sizing (size chart), discounts or contact.",
        GetStorePolicyInput, _get_store_policy,
    ),
    ToolSpec(
        "place_order",
        "PREPARE an order (risky action - it is NOT placed yet). Validates sizes/stock and returns a priced "
        "summary that you must show to the customer for confirmation. Requires product, size, quantity, "
        "customer name, phone, full address and city.",
        PlaceOrderInput, _place_order,
    ),
    ToolSpec(
        "cancel_order",
        "PREPARE cancellation of one of the customer's own orders (risky action - not cancelled yet). "
        "Returns a summary for the customer to confirm.",
        CancelOrderInput, _cancel_order,
    ),
    ToolSpec(
        "forget_my_data",
        "PREPARE deletion of the customer's saved preferences (risky action). Needs confirmation.",
        NoArgs, _forget_my_data,
    ),
    ToolSpec(
        "confirm_pending_action",
        "Execute the action prepared in the PREVIOUS turn (order / cancellation / deletion) - call this only "
        "when the customer's latest message explicitly confirms it (e.g. 'yes').",
        NoArgs, _confirm_pending_action,
    ),
    ToolSpec(
        "get_my_orders",
        "List the current customer's recent orders, or one order by number, with status and totals.",
        GetMyOrdersInput, _get_my_orders,
    ),
    ToolSpec(
        "save_user_preference",
        "Save lasting customer preferences to long-term memory (name, usual size, city, budget, style notes) "
        "so future conversations can use them.",
        SavePreferenceInput, _save_user_preference,
    ),
]
TOOLS_BY_NAME: Dict[str, ToolSpec] = {t.name: t for t in TOOL_SPECS}


def _not_called_directly(**_: Any) -> str:  # pragma: no cover
    raise RuntimeError("Tools are executed by the graph's tools node.")


def langchain_tools() -> List[StructuredTool]:
    return [
        StructuredTool.from_function(
            func=_not_called_directly, name=t.name, description=t.description, args_schema=t.schema
        )
        for t in TOOL_SPECS
    ]


def run_tool(name: str, raw_args: Dict[str, Any], ctx: ToolContext) -> ToolOutcome:
    spec = TOOLS_BY_NAME.get(name)
    if spec is None:
        return ToolOutcome(f"Unknown tool '{name}'.", is_error=True)
    try:
        args = spec.schema.model_validate(raw_args or {})
    except Exception as e:  # pydantic.ValidationError
        return ToolOutcome(f"Invalid arguments for {name}: {str(e)[:400]}", is_error=True)
    try:
        return spec.handler(args, ctx)
    except db.OrderError as e:
        return ToolOutcome(str(e), is_error=True)
    except Exception as e:  # never let one tool crash the turn
        return ToolOutcome(f"Tool {name} failed: {type(e).__name__}. Apologize and offer to retry.", is_error=True)


def compact_args(args: Dict[str, Any]) -> Dict[str, Any]:
    """JSON-safe copy of tool arguments for the API response / logs."""
    return json.loads(json.dumps(args or {}, default=str))

"""
Kavyn Parfums — Stripe-only backend (minimal, deploy-friendly)
Required env: STRIPE_SECRET_KEY
Optional: CORS_ORIGINS, STRIPE_AUTO_CREATE=1
"""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import stripe
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field

load_dotenv()

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY") or os.environ.get("STRIPE_API_KEY") or ""

SHIPPING_FLAT_CAD = 12.0
TAX_RATE = 0.13
AUTO_CREATE = os.environ.get("STRIPE_AUTO_CREATE", "").strip().lower() in ("1", "true", "yes")
PRICES_FILE = Path(__file__).parent / "stripe_prices.json"

PRODUCTS: List[Dict[str, Any]] = [
    {"id": "ambery-bergamot", "name": "Ambery Bergamot", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 9.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 49.99},
    ]},
    {"id": "woody-ginger", "name": "Woody Ginger", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 9.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 49.99},
    ]},
    {"id": "woody-citrus", "name": "Woody Citrus", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 9.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 49.99},
    ]},
    {"id": "kavyn-signature-formula", "name": "Kavyn Signature Formula", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 9.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 49.99},
    ]},
    {"id": "floral-vanilla", "name": "Floral Vanilla", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 9.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 49.99},
    ]},
    {"id": "honeyed-tonka", "name": "Honeyed Tonka", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 9.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 49.99},
    ]},
    {"id": "tropical-floral", "name": "Tropical Floral", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 9.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 49.99},
    ]},
    {"id": "leather-oud", "name": "Leather Oud", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 9.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 49.99},
    ]},
    {"id": "amber-saffron", "name": "Amber Saffron", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 9.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 64.99},
    ]},
    {"id": "smoky-sandalwood", "name": "Smoky Sandalwood", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 9.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 64.99},
    ]},
    {"id": "suede-leather", "name": "Suede Leather", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 9.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 64.99},
    ]},
    {"id": "tobacco-vanilla", "name": "Tobacco Vanilla", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 9.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 64.99},
    ]},
    {"id": "almond-leather", "name": "Almond Leather", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 9.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 64.99},
    ]},
    {"id": "rose-ambroxan", "name": "Rose Ambroxan", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 9.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 64.99},
    ]},
    {"id": "fruity-birch", "name": "Fruity Birch", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 9.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 64.99},
    ]},
    {"id": "green-sandalwood", "name": "Green Sandalwood", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 9.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 64.99},
    ]},
]

BY_ID = {p["id"]: p for p in PRODUCTS}
_PRICE_MAP: Dict[Tuple[str, str], str] = {}
_PRICE_MAP_LOADED = False
_TX_MEMORY: Dict[str, Dict] = {}
_NEWSLETTER: set = set()


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _size_tokens(size_slug: str, size_label: str) -> List[str]:
    raw = f"{size_slug} {size_label}".lower()
    tokens = []
    if "5ml" in raw or "5 ml" in raw or "tester" in raw:
        tokens += ["5ml", "5 ml", "tester"]
    if "50" in raw:
        tokens += ["50ml", "50 ml", "50"]
    return tokens


def _score(stripe_name: str, our_name: str, size_slug: str, size_label: str) -> int:
    sn, on = _norm(stripe_name), _norm(our_name)
    if not sn or not on:
        return 0
    score = 0
    if on in sn or sn in on:
        score += 50
    score += 10 * len(set(on.split()) & set(sn.split()))
    for tok in _size_tokens(size_slug, size_label):
        if _norm(tok) in sn:
            score += 30
            break
    return score


def _load_prices_file() -> Dict[Tuple[str, str], str]:
    if not PRICES_FILE.exists():
        return {}
    try:
        data = json.loads(PRICES_FILE.read_text())
    except Exception:
        return {}
    out = {}
    for key, price_id in data.items():
        if "|" in key and isinstance(price_id, str) and price_id.startswith("price_"):
            a, b = key.split("|", 1)
            out[(a, b)] = price_id
    return out


def _save_prices_file(mapping: Dict[Tuple[str, str], str]) -> None:
    try:
        data = {f"{k[0]}|{k[1]}": v for k, v in mapping.items()}
        PRICES_FILE.write_text(json.dumps(data, indent=2, sort_keys=True))
    except Exception:
        pass


def _list_stripe_prices() -> List[Dict[str, Any]]:
    results = []
    starting_after = None
    while True:
        kwargs: Dict[str, Any] = {"limit": 100, "active": True, "expand": ["data.product"]}
        if starting_after:
            kwargs["starting_after"] = starting_after
        page = stripe.Price.list(**kwargs)
        for p in page.data:
            prod = p.product
            name = getattr(prod, "name", None) or str(prod)
            results.append({
                "price_id": p.id,
                "unit_amount": p.unit_amount,
                "currency": (p.currency or "").lower(),
                "product_name": name or "",
            })
        if not page.has_more:
            break
        starting_after = page.data[-1].id
    return results


def _create_price(product_name: str, size_label: str, amount: float) -> str:
    product = stripe.Product.create(name=f"{product_name} — {size_label}", metadata={"kavyn": "1"})
    price = stripe.Price.create(
        product=product.id,
        unit_amount=int(round(amount * 100)),
        currency="cad",
    )
    return price.id


def refresh_price_map() -> Dict[str, Any]:
    global _PRICE_MAP, _PRICE_MAP_LOADED
    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="STRIPE_SECRET_KEY is not set")

    mapping = _load_prices_file()
    report: Dict[str, Any] = {"matched": [], "missing": [], "created": []}

    try:
        stripe_prices = _list_stripe_prices()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Stripe API error: {e}") from e

    for prod in PRODUCTS:
        for variant in prod["variants"]:
            key = (prod["id"], variant["size_slug"])
            if key in mapping:
                report["matched"].append({"product": prod["name"], "size": variant["size"], "price_id": mapping[key], "source": "file"})
                continue

            best, best_score = None, 0
            for sp in stripe_prices:
                if sp["currency"] and sp["currency"] != "cad":
                    continue
                score = _score(sp["product_name"], prod["name"], variant["size_slug"], variant["size"])
                if sp["unit_amount"] == int(round(variant["price"] * 100)):
                    score += 20
                if score > best_score:
                    best_score, best = score, sp

            if best and best_score >= 50:
                mapping[key] = best["price_id"]
                report["matched"].append({
                    "product": prod["name"], "size": variant["size"],
                    "price_id": best["price_id"], "stripe_name": best["product_name"], "source": "auto",
                })
            elif AUTO_CREATE:
                try:
                    pid = _create_price(prod["name"], variant["size"], variant["price"])
                    mapping[key] = pid
                    report["created"].append({"product": prod["name"], "size": variant["size"], "price_id": pid})
                except Exception as e:
                    report["missing"].append({"product": prod["name"], "size": variant["size"], "error": str(e)})
            else:
                report["missing"].append({
                    "product": prod["name"], "size": variant["size"],
                    "hint": "Set STRIPE_AUTO_CREATE=1 or name Stripe products like 'Ambery Bergamot — 50 ML'",
                })

    _PRICE_MAP = mapping
    _PRICE_MAP_LOADED = True
    if mapping:
        _save_prices_file(mapping)
    report["total_mapped"] = len(mapping)
    report["total_needed"] = sum(len(p["variants"]) for p in PRODUCTS)
    return report


def ensure_price_map() -> None:
    global _PRICE_MAP_LOADED
    if _PRICE_MAP_LOADED:
        return
    file_map = _load_prices_file()
    needed = sum(len(p["variants"]) for p in PRODUCTS)
    if file_map and len(file_map) >= needed:
        _PRICE_MAP.update(file_map)
        _PRICE_MAP_LOADED = True
    else:
        refresh_price_map()


def get_price_id(product_id: str, size_slug: str) -> str:
    ensure_price_map()
    key = (product_id, size_slug or "50-ml")
    pid = _PRICE_MAP.get(key)
    if not pid:
        refresh_price_map()
        pid = _PRICE_MAP.get(key)
    if not pid:
        name = BY_ID.get(product_id, {}).get("name", product_id)
        raise HTTPException(status_code=400, detail=f"No Stripe Price for {name} ({size_slug}). POST /api/stripe/sync first.")
    return pid


class CartItem(BaseModel):
    product_id: str
    quantity: int = Field(ge=1, le=20)
    size_slug: Optional[str] = "50-ml"
    variation_id: Optional[int] = None


class CustomerInfo(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    phone: Optional[str] = ""
    address_1: str
    address_2: Optional[str] = ""
    city: str
    state: str = "ON"
    postcode: str
    order_notes: Optional[str] = ""


class CheckoutSessionCreateRequest(BaseModel):
    items: List[CartItem]
    origin_url: str
    customer: CustomerInfo


class NewsletterRequest(BaseModel):
    email: EmailStr


def _resolve_variant(product: Dict, size_slug: Optional[str]) -> Dict:
    variants = product.get("variants") or []
    if size_slug:
        for v in variants:
            if v.get("size_slug") == size_slug:
                return v
    for v in variants:
        if "50" in (v.get("size") or ""):
            return v
    return variants[-1] if variants else {"size": "50 ML", "size_slug": "50-ml", "price": 0}


def _compute_order(items: List[CartItem]) -> Dict:
    subtotal = 0.0
    line_items, stripe_lines = [], []
    for item in items:
        prod = BY_ID.get(item.product_id)
        if not prod:
            raise HTTPException(status_code=400, detail=f"Unknown product: {item.product_id}")
        variant = _resolve_variant(prod, item.size_slug)
        unit = float(variant["price"])
        line_total = round(unit * item.quantity, 2)
        subtotal += line_total
        price_id = get_price_id(prod["id"], variant["size_slug"])
        line_items.append({
            "product_id": prod["id"], "name": prod["name"], "size": variant.get("size"),
            "unit_price": unit, "quantity": item.quantity, "line_total": line_total,
            "stripe_price_id": price_id,
        })
        stripe_lines.append({"price": price_id, "quantity": item.quantity})
    subtotal = round(subtotal, 2)
    shipping = SHIPPING_FLAT_CAD
    tax = round((subtotal + shipping) * TAX_RATE, 2)
    total = round(subtotal + shipping + tax, 2)
    return {
        "line_items": line_items, "stripe_lines": stripe_lines,
        "subtotal": subtotal, "shipping": shipping, "tax": tax, "total": total,
    }


app = FastAPI(title="Kavyn API", version="2.2.0")
api = APIRouter(prefix="/api")

origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if origins == ["*"] else origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@api.get("/health")
def health():
    mapped = len(_PRICE_MAP) if _PRICE_MAP_LOADED else len(_load_prices_file())
    needed = sum(len(p["variants"]) for p in PRODUCTS)
    return {
        "status": "ok",
        "stripe_configured": bool(stripe.api_key),
        "products": len(PRODUCTS),
        "stripe_prices_mapped": mapped,
        "stripe_prices_needed": needed,
        "ready_for_checkout": mapped >= needed and bool(stripe.api_key),
    }


@api.post("/stripe/sync")
def stripe_sync():
    return refresh_price_map()


@api.get("/stripe/mapping")
def stripe_mapping():
    ensure_price_map()
    return {f"{k[0]}|{k[1]}": v for k, v in sorted(_PRICE_MAP.items())}


@api.get("/products")
def list_products():
    out = []
    for p in PRODUCTS:
        preferred = next((v for v in p["variants"] if "50" in v["size"]), p["variants"][-1])
        out.append({
            "id": p["id"], "name": p["name"], "price": preferred["price"],
            "variants": [{"size": v["size"], "size_slug": v["size_slug"], "price": v["price"]} for v in p["variants"]],
        })
    return out


@api.post("/checkout/quote")
def checkout_quote(items: List[CartItem]):
    subtotal = 0.0
    line_items = []
    for item in items:
        prod = BY_ID.get(item.product_id)
        if not prod:
            continue
        variant = _resolve_variant(prod, item.size_slug)
        unit = float(variant["price"])
        line_total = round(unit * item.quantity, 2)
        subtotal += line_total
        line_items.append({
            "product_id": prod["id"], "name": prod["name"],
            "unit_price": unit, "quantity": item.quantity, "line_total": line_total,
        })
    subtotal = round(subtotal, 2)
    shipping = SHIPPING_FLAT_CAD
    tax = round((subtotal + shipping) * TAX_RATE, 2)
    total = round(subtotal + shipping + tax, 2)
    return {"line_items": line_items, "subtotal": subtotal, "shipping": shipping, "tax": tax, "total": total}


@api.post("/checkout/create-session")
def create_checkout_session(payload: CheckoutSessionCreateRequest):
    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="STRIPE_SECRET_KEY is not configured.")
    if not payload.items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    order = _compute_order(payload.items)
    origin = payload.origin_url.rstrip("/")
    success_url = f"{origin}/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin}/checkout?checkout=cancel"
    cust = payload.customer.model_dump()

    line_items = list(order["stripe_lines"])
    line_items.append({
        "price_data": {
            "currency": "cad",
            "unit_amount": int(round(order["shipping"] * 100)),
            "product_data": {"name": "Shipping (Canada)"},
        },
        "quantity": 1,
    })
    line_items.append({
        "price_data": {
            "currency": "cad",
            "unit_amount": int(round(order["tax"] * 100)),
            "product_data": {"name": "HST (13%)"},
        },
        "quantity": 1,
    })

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            line_items=line_items,
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=cust.get("email"),
            shipping_address_collection={"allowed_countries": ["CA"]},
            phone_number_collection={"enabled": True},
            metadata={
                "source": "kavyn",
                "email": cust.get("email") or "",
                "items": ",".join(f"{li['product_id']}:{li['size']}x{li['quantity']}" for li in order["line_items"]),
                "total": f"{order['total']:.2f}",
            },
        )
    except Exception as e:
        msg = getattr(e, "user_message", None) or str(e)
        raise HTTPException(status_code=400, detail=msg) from e

    tx = {
        "session_id": session.id,
        "amount": order["total"],
        "email": cust.get("email"),
        "customer": cust,
        "cart": order["line_items"],
        "order": {
            "subtotal": order["subtotal"], "shipping": order["shipping"],
            "tax": order["tax"], "total": order["total"],
        },
        "payment_status": "initiated",
    }
    _TX_MEMORY[session.id] = tx
    return {"url": session.url, "session_id": session.id}


@api.get("/checkout/status/{session_id}")
def checkout_status(session_id: str):
    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    tx = _TX_MEMORY.get(session_id) or {}
    if session.payment_status == "paid":
        tx["payment_status"] = "paid"
        _TX_MEMORY[session_id] = tx

    return {
        "session_id": session_id,
        "payment_status": session.payment_status,
        "status": session.status,
        "order": tx.get("order"),
        "customer": tx.get("customer"),
        "cart": tx.get("cart"),
    }


@api.post("/newsletter/subscribe")
def newsletter_subscribe(body: NewsletterRequest):
    _NEWSLETTER.add(body.email.lower().strip())
    return {"ok": True, "message": "Thank you — you are on the list."}


app.include_router(api)


@app.get("/")
def root():
    return {"service": "kavyn-api", "health": "/api/health", "docs": "/docs"}

"""
Kavyn Parfums backend — Stripe payment + WooCommerce orders

Flow:
  1. Catalogue & prices come from WooCommerce (required).
  2. Customer checks out on the site → backend creates a Stripe Checkout Session
     with ad-hoc amounts (no Stripe Catalog / Price IDs).
  3. Stripe collects payment + shipping address + phone (once).
  4. On payment success the backend creates a paid WooCommerce order with the
     line items, billing, and shipping from the Stripe session.

Required env:
  STRIPE_SECRET_KEY
  WC_STORE_URL          e.g. https://kavynparfums-com-145120.hostingersite.com
  WC_CONSUMER_KEY
  WC_CONSUMER_SECRET

Optional:
  STRIPE_WEBHOOK_SECRET   for POST /api/stripe/webhook (recommended in production)
  CORS_ORIGINS
  SHIPPING_FLAT_CAD       default 12.0
  TAX_RATE                default 0.13
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import stripe
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, HTTPException, Request as FastAPIRequest
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field

load_dotenv()

stripe.api_key = (
    os.environ.get("STRIPE_SECRET_KEY")
    or os.environ.get("STRIPE_API_KEY")
    or ""
)
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET") or ""

SHIPPING_FLAT_CAD = float(os.environ.get("SHIPPING_FLAT_CAD", "12.0"))
TAX_RATE = float(os.environ.get("TAX_RATE", "0.13"))
WC_STORE_URL = (os.environ.get("WC_STORE_URL") or "").rstrip("/")
WC_KEY = os.environ.get("WC_CONSUMER_KEY") or ""
WC_SECRET = os.environ.get("WC_CONSUMER_SECRET") or ""
LEADS_FILE = Path(__file__).parent / "leads.jsonl"

# Fallback local catalog used only if WC is unreachable (should not happen once configured)
PRODUCTS_FALLBACK: List[Dict[str, Any]] = [
    {"id": "ambery-bergamot", "name": "Ambery Bergamot", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 6.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 49.99},
    ]},
    {"id": "woody-ginger", "name": "Woody Ginger", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 6.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 49.99},
    ]},
    {"id": "woody-citrus", "name": "Woody Citrus", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 6.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 49.99},
    ]},
    {"id": "kavyn-signature-formula", "name": "Kavyn Signature Formula", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 6.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 49.99},
    ]},
    {"id": "floral-vanilla", "name": "Floral Vanilla", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 6.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 49.99},
    ]},
    {"id": "honeyed-tonka", "name": "Honeyed Tonka", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 6.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 49.99},
    ]},
    {"id": "tropical-floral", "name": "Tropical Floral", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 6.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 49.99},
    ]},
    {"id": "leather-oud", "name": "Leather Oud", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 6.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 49.99},
    ]},
    {"id": "amber-saffron", "name": "Amber Saffron", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 9.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 69.99},
    ]},
    {"id": "smoky-sandalwood", "name": "Smoky Sandalwood", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 9.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 69.99},
    ]},
    {"id": "suede-leather", "name": "Suede Leather", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 9.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 69.99},
    ]},
    {"id": "tobacco-vanilla", "name": "Tobacco Vanilla", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 9.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 69.99},
    ]},
    {"id": "almond-leather", "name": "Almond Leather", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 9.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 69.99},
    ]},
    {"id": "rose-ambroxan", "name": "Rose Ambroxan", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 9.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 69.99},
    ]},
    {"id": "fruity-birch", "name": "Fruity Birch", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 9.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 69.99},
    ]},
    {"id": "green-sandalwood", "name": "Green Sandalwood", "variants": [
        {"size": "5ML Tester", "size_slug": "5ml-tester", "price": 9.99},
        {"size": "50 ML", "size_slug": "50-ml", "price": 69.99},
    ]},
]

_TX_MEMORY: Dict[str, Dict] = {}
_NEWSLETTER: set = set()
_CATALOGUE: Optional[List[Dict[str, Any]]] = None
_CATALOGUE_TS: float = 0.0
# Map stable product_id + size_slug → WC variation_id / product_id
_WC_VARIANT_MAP: Dict[Tuple[str, str], Dict[str, Any]] = {}


def _cents(amount: float) -> int:
    return int(round(float(amount) * 100))


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Frontend seed IDs that differ from WC-derived names
_ID_ALIASES = {
    "kavyn-signature-formula": "kavyn-signature-blend",
    "kavyn-signature-blend": "kavyn-signature-blend",
}


def _stable_id_from_wc(name: str, slug: str) -> str:
    name_part = (name or "").split("|")[0].strip()
    n = _norm(name_part)
    for fb in PRODUCTS_FALLBACK:
        if _norm(fb["name"]) == n or fb["id"] in (slug or ""):
            return _ID_ALIASES.get(fb["id"], fb["id"])
    # special-case house blend naming
    if "signature" in n and ("blend" in n or "formula" in n):
        return "kavyn-signature-blend"
    derived = re.sub(r"[^a-z0-9]+", "-", n).strip("-") or (slug or "product")
    return _ID_ALIASES.get(derived, derived)


def _size_slug_from_label(label: str) -> str:
    l = (label or "").lower()
    if "tester" in l or ("5" in l and "50" not in l):
        return "5ml-tester"
    return "50-ml"


def _append_lead(record: Dict[str, Any]) -> None:
    try:
        record = {"captured_at": datetime.now(timezone.utc).isoformat(), **record}
        with LEADS_FILE.open("a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass


def _wc_request(method: str, path: str, body: Optional[dict] = None, timeout: int = 20) -> Any:
    if not (WC_STORE_URL and WC_KEY and WC_SECRET):
        raise HTTPException(status_code=500, detail="WooCommerce is not configured (WC_STORE_URL / keys).")
    qs = urlencode({"consumer_key": WC_KEY, "consumer_secret": WC_SECRET})
    url = f"{WC_STORE_URL}{path}{'&' if '?' in path else '?'}{qs}"
    data = None
    headers = {"User-Agent": "kavyn-api/3.1.0", "Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:500]
        raise HTTPException(status_code=400, detail=f"WooCommerce API error {e.code}: {err_body}") from e
    except (URLError, TimeoutError, OSError) as e:
        raise HTTPException(status_code=502, detail=f"WooCommerce unreachable: {e}") from e


def _fetch_wc_catalogue() -> List[Dict[str, Any]]:
    """Load products + variations from WooCommerce (parallel variation fetches)."""
    global _WC_VARIANT_MAP
    from concurrent.futures import ThreadPoolExecutor, as_completed

    parents = _wc_request("GET", "/wp-json/wc/v3/products?per_page=100&status=publish")
    if not isinstance(parents, list):
        return []

    def _load_variations(wc_product_id: int) -> list:
        try:
            return _wc_request(
                "GET",
                f"/wp-json/wc/v3/products/{wc_product_id}/variations?per_page=50",
            ) or []
        except Exception:
            return []

    variable_ids = [wp["id"] for wp in parents if wp.get("type") == "variable"]
    vars_by_parent: Dict[int, list] = {}
    if variable_ids:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = {pool.submit(_load_variations, pid): pid for pid in variable_ids}
            for fut in as_completed(futs):
                vars_by_parent[futs[fut]] = fut.result()

    out: List[Dict[str, Any]] = []
    variant_map: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for wp in parents:
        name_raw = (wp.get("name") or "").split("|")[0].strip()
        # inspired by from name after | or from short description
        inspired = ""
        if "|" in (wp.get("name") or ""):
            tail = (wp.get("name") or "").split("|", 1)[1].strip()
            m = re.search(r"Inspired by\s+(.+)", tail, re.I)
            inspired = (m.group(1).strip() if m else tail)
        product_id = _stable_id_from_wc(name_raw, wp.get("slug") or "")
        is_signature = product_id == "kavyn-signature-blend" or "signature" in _norm(name_raw)
        if is_signature:
            inspired = ""
            product_id = "kavyn-signature-blend"

        images = wp.get("images") or []
        image = images[0]["src"] if images else ""
        wc_product_id = wp.get("id")
        featured = bool(wp.get("featured"))

        # strip HTML for descriptions
        def _strip(html: str) -> str:
            t = re.sub(r"<[^>]+>", " ", html or "")
            return re.sub(r"\s+", " ", t).strip()

        description = _strip(wp.get("description") or "")
        short_description = _strip(wp.get("short_description") or "")

        variants: List[Dict[str, Any]] = []
        if wp.get("type") == "variable":
            for v in vars_by_parent.get(wc_product_id, []):
                attrs = v.get("attributes") or []
                size_label = next(
                    (a.get("option") for a in attrs if "size" in (a.get("name") or "").lower()),
                    "50 ML",
                )
                size_slug = _size_slug_from_label(size_label or "")
                try:
                    price = float(v.get("price") or 0)
                except (TypeError, ValueError):
                    price = 0.0
                try:
                    regular = float(v.get("regular_price") or 0) or None
                except (TypeError, ValueError):
                    regular = None
                try:
                    sale = float(v.get("sale_price") or 0) or None
                except (TypeError, ValueError):
                    sale = None
                # selling price = sale if set else price
                sell = float(sale or price or 0)
                if sell <= 0:
                    continue
                variants.append({
                    "size": size_label or ("5ML Tester" if size_slug == "5ml-tester" else "50 ML"),
                    "size_slug": size_slug,
                    "price": sell,
                    "regular_price": regular,
                    "sale_price": sale if sale else sell,
                    "variation_id": v.get("id"),
                    "stock_status": v.get("stock_status"),
                })
                variant_map[(product_id, size_slug)] = {
                    "wc_product_id": wc_product_id,
                    "variation_id": v.get("id"),
                    "price": sell,
                    "name": name_raw,
                    "size": size_label,
                }
        else:
            try:
                price = float(wp.get("price") or 0)
            except (TypeError, ValueError):
                price = 0.0
            try:
                regular = float(wp.get("regular_price") or 0) or None
            except (TypeError, ValueError):
                regular = None
            try:
                sale = float(wp.get("sale_price") or 0) or None
            except (TypeError, ValueError):
                sale = None
            sell = float(sale or price or 0)
            if sell > 0:
                variants.append({
                    "size": "50 ML",
                    "size_slug": "50-ml",
                    "price": sell,
                    "regular_price": regular,
                    "sale_price": sale if sale else sell,
                    "variation_id": None,
                    "stock_status": wp.get("stock_status"),
                })
                variant_map[(product_id, "50-ml")] = {
                    "wc_product_id": wc_product_id,
                    "variation_id": None,
                    "price": sell,
                    "name": name_raw,
                    "size": "50 ML",
                }

        if not variants:
            continue

        preferred = next((v for v in variants if v["size_slug"] == "50-ml"), variants[-1])
        out.append({
            "id": product_id,
            "name": name_raw or product_id,
            "price": preferred["price"],
            "regular_price": preferred.get("regular_price"),
            "sale_price": preferred.get("sale_price") or preferred["price"],
            "image": image,
            "wc_id": wc_product_id,
            "featured": featured or is_signature,
            "inspired_by": "" if is_signature else inspired,
            "description": description,
            "short_description": short_description,
            "variants": variants,
        })

    # Featured / signature first
    out.sort(key=lambda p: (0 if p.get("featured") else 1, p.get("name") or ""))
    _WC_VARIANT_MAP = variant_map
    return out



def get_catalogue(force: bool = False) -> List[Dict[str, Any]]:
    global _CATALOGUE, _CATALOGUE_TS
    now = time.time()
    if not force and _CATALOGUE is not None and (now - _CATALOGUE_TS) < 90:
        return _CATALOGUE

    if WC_STORE_URL and WC_KEY and WC_SECRET:
        try:
            cat = _fetch_wc_catalogue()
            if cat:
                _CATALOGUE = cat
                _CATALOGUE_TS = now
                return cat
        except HTTPException:
            pass

    # Fallback (should only happen if WC is down)
    out = []
    for p in PRODUCTS_FALLBACK:
        variants = [dict(v) for v in p["variants"]]
        preferred = next((v for v in variants if v["size_slug"] == "50-ml"), variants[-1])
        out.append({
            "id": p["id"],
            "name": p["name"],
            "price": preferred["price"],
            "image": "",
            "variants": variants,
        })
    _CATALOGUE = out
    _CATALOGUE_TS = now
    return out


def _resolve_variant(product: Dict, size_slug: Optional[str]) -> Dict:
    variants = product.get("variants") or []
    if size_slug:
        for v in variants:
            if v.get("size_slug") == size_slug:
                return v
    for v in variants:
        if v.get("size_slug") == "50-ml":
            return v
    return variants[-1] if variants else {"size": "50 ML", "size_slug": "50-ml", "price": 0}


def _compute_order(items: List["CartItem"]) -> Dict:
    catalogue = {p["id"]: p for p in get_catalogue()}
    # also index aliases
    for alias, real in _ID_ALIASES.items():
        if real in catalogue and alias not in catalogue:
            catalogue[alias] = catalogue[real]
    subtotal = 0.0
    line_items: List[Dict[str, Any]] = []
    stripe_lines: List[Dict[str, Any]] = []
    wc_lines: List[Dict[str, Any]] = []

    for item in items:
        pid = _ID_ALIASES.get(item.product_id, item.product_id)
        prod = catalogue.get(pid) or catalogue.get(item.product_id)
        if not prod:
            raise HTTPException(status_code=400, detail=f"Unknown product: {item.product_id}")
        variant = _resolve_variant(prod, item.size_slug)
        unit = float(variant.get("price") or 0)
        if unit <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"No price for {prod.get('name')} ({variant.get('size')}).",
            )
        line_total = round(unit * item.quantity, 2)
        subtotal += line_total
        display_name = f"{prod['name']} — {variant.get('size', '')}".strip(" —")
        line_items.append({
            "product_id": prod["id"],
            "name": prod["name"],
            "size": variant.get("size"),
            "unit_price": unit,
            "quantity": item.quantity,
            "line_total": line_total,
            "variation_id": variant.get("variation_id"),
            "wc_id": prod.get("wc_id"),
        })
        stripe_lines.append({
            "price_data": {
                "currency": "cad",
                "unit_amount": _cents(unit),
                "product_data": {
                    "name": display_name,
                    "metadata": {
                        "product_id": str(prod["id"]),
                        "size_slug": str(variant.get("size_slug") or ""),
                        "wc_variation_id": str(variant.get("variation_id") or ""),
                    },
                },
            },
            "quantity": item.quantity,
        })
        # WooCommerce line item
        wc_line: Dict[str, Any] = {"quantity": item.quantity}
        if variant.get("variation_id"):
            wc_line["product_id"] = prod.get("wc_id")
            wc_line["variation_id"] = variant["variation_id"]
        elif prod.get("wc_id"):
            wc_line["product_id"] = prod["wc_id"]
        else:
            # Last resort: name-only (WC may reject)
            wc_line["name"] = display_name
            wc_line["product_id"] = 0
            wc_line["total"] = f"{line_total:.2f}"
            wc_line["subtotal"] = f"{line_total:.2f}"
        wc_lines.append(wc_line)

    subtotal = round(subtotal, 2)
    shipping = SHIPPING_FLAT_CAD
    tax = round((subtotal + shipping) * TAX_RATE, 2)
    total = round(subtotal + shipping + tax, 2)

    stripe_lines.append({
        "price_data": {
            "currency": "cad",
            "unit_amount": _cents(shipping),
            "product_data": {"name": "Shipping (Canada)"},
        },
        "quantity": 1,
    })
    stripe_lines.append({
        "price_data": {
            "currency": "cad",
            "unit_amount": _cents(tax),
            "product_data": {"name": "HST (13%)"},
        },
        "quantity": 1,
    })

    return {
        "line_items": line_items,
        "stripe_lines": stripe_lines,
        "wc_lines": wc_lines,
        "subtotal": subtotal,
        "shipping": shipping,
        "tax": tax,
        "total": total,
    }


def _addr_from_stripe(details: Any) -> Dict[str, str]:
    if not details:
        return {}
    addr = getattr(details, "address", None) or {}
    if hasattr(addr, "to_dict"):
        addr = addr.to_dict()
    elif not isinstance(addr, dict):
        addr = {
            "line1": getattr(addr, "line1", "") or "",
            "line2": getattr(addr, "line2", "") or "",
            "city": getattr(addr, "city", "") or "",
            "state": getattr(addr, "state", "") or "",
            "postal_code": getattr(addr, "postal_code", "") or "",
            "country": getattr(addr, "country", "") or "",
        }
    name = (getattr(details, "name", None) or "").strip()
    parts = name.split(None, 1) if name else ["", ""]
    first = parts[0] if parts else ""
    last = parts[1] if len(parts) > 1 else ""
    return {
        "first_name": first,
        "last_name": last,
        "phone": getattr(details, "phone", None) or "",
        "address_1": addr.get("line1") or "",
        "address_2": addr.get("line2") or "",
        "city": addr.get("city") or "",
        "state": addr.get("state") or "",
        "postcode": addr.get("postal_code") or "",
        "country": addr.get("country") or "CA",
    }


def create_woocommerce_order_from_session(session: Any, tx: Dict) -> Dict[str, Any]:
    """Create a paid WC order from a paid Stripe Checkout Session + our tx memory."""
    # Avoid duplicate orders
    existing = (tx or {}).get("wc_order_id")
    if existing:
        return {"id": existing, "status": "already_created"}

    # Pull customer + shipping from Stripe session
    customer_details = getattr(session, "customer_details", None)
    shipping_details = getattr(session, "shipping_details", None)

    billing = _addr_from_stripe(customer_details)
    shipping = _addr_from_stripe(shipping_details) if shipping_details else dict(billing)

    email = ""
    if customer_details and getattr(customer_details, "email", None):
        email = customer_details.email
    email = email or (tx.get("email") or "")
    billing["email"] = email
    if not billing.get("phone") and getattr(customer_details, "phone", None):
        billing["phone"] = customer_details.phone

    cart = tx.get("cart") or []
    order_meta = tx.get("order") or {}

    # Rebuild WC line items from cart (preferred) or recompute
    wc_lines: List[Dict[str, Any]] = []
    for li in cart:
        pid = li.get("product_id")
        size = li.get("size") or ""
        size_slug = _size_slug_from_label(size)
        mapped = _WC_VARIANT_MAP.get((pid, size_slug))
        if not mapped and not _WC_VARIANT_MAP:
            get_catalogue(force=True)
            mapped = _WC_VARIANT_MAP.get((pid, size_slug))
        qty = int(li.get("quantity") or 1)
        if mapped and mapped.get("variation_id"):
            wc_lines.append({
                "product_id": mapped["wc_product_id"],
                "variation_id": mapped["variation_id"],
                "quantity": qty,
            })
        elif mapped:
            wc_lines.append({
                "product_id": mapped["wc_product_id"],
                "quantity": qty,
            })
        elif li.get("variation_id"):
            wc_lines.append({
                "product_id": li.get("wc_id"),
                "variation_id": li["variation_id"],
                "quantity": qty,
            })
        else:
            # Fee-style line so the order still records the sale
            wc_lines.append({
                "name": f"{li.get('name')} — {size}",
                "product_id": 0,
                "quantity": qty,
                "total": f"{float(li.get('line_total') or 0):.2f}",
                "subtotal": f"{float(li.get('line_total') or 0):.2f}",
            })

    shipping_lines = [{
        "method_id": "flat_rate",
        "method_title": "Shipping (Canada)",
        "total": f"{float(order_meta.get('shipping') or SHIPPING_FLAT_CAD):.2f}",
    }]

    payload = {
        "status": "processing",  # paid
        "set_paid": True,
        "currency": "CAD",
        "payment_method": "stripe",
        "payment_method_title": "Stripe",
        "transaction_id": session.id,
        "billing": {
            "first_name": billing.get("first_name") or "",
            "last_name": billing.get("last_name") or "",
            "address_1": billing.get("address_1") or "",
            "address_2": billing.get("address_2") or "",
            "city": billing.get("city") or "",
            "state": billing.get("state") or "",
            "postcode": billing.get("postcode") or "",
            "country": billing.get("country") or "CA",
            "email": email,
            "phone": billing.get("phone") or "",
        },
        "shipping": {
            "first_name": shipping.get("first_name") or billing.get("first_name") or "",
            "last_name": shipping.get("last_name") or billing.get("last_name") or "",
            "address_1": shipping.get("address_1") or billing.get("address_1") or "",
            "address_2": shipping.get("address_2") or billing.get("address_2") or "",
            "city": shipping.get("city") or billing.get("city") or "",
            "state": shipping.get("state") or billing.get("state") or "",
            "postcode": shipping.get("postcode") or billing.get("postcode") or "",
            "country": shipping.get("country") or billing.get("country") or "CA",
        },
        "line_items": wc_lines,
        "shipping_lines": shipping_lines,
        "meta_data": [
            {"key": "_stripe_session_id", "value": session.id},
            {"key": "_kavyn_source", "value": "stripe_checkout"},
            {"key": "_kavyn_total", "value": str(order_meta.get("total") or "")},
        ],
        "customer_note": (tx.get("customer") or {}).get("order_notes") or "",
    }

    # Let WC calculate tax from shipping address if possible; otherwise we already
    # charged tax via Stripe line item. To keep totals consistent with what was
    # paid, we set prices_include_tax false and rely on shipping_lines + line items.
    # If WC auto-tax differs slightly, the order still records the Stripe payment.

    order = _wc_request("POST", "/wp-json/wc/v3/orders", body=payload)
    wc_id = order.get("id") if isinstance(order, dict) else None
    if wc_id:
        tx["wc_order_id"] = wc_id
        tx["wc_order_number"] = order.get("number") or str(wc_id)
        tx["payment_status"] = "paid"
        _TX_MEMORY[session.id] = tx
        _append_lead({
            "type": "order_created",
            "email": email,
            "session_id": session.id,
            "wc_order_id": wc_id,
            "total": order_meta.get("total"),
        })
    return order if isinstance(order, dict) else {"raw": order}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class CartItem(BaseModel):
    product_id: str
    quantity: int = Field(ge=1, le=20)
    size_slug: Optional[str] = "50-ml"
    variation_id: Optional[int] = None


class CustomerInfo(BaseModel):
    email: EmailStr
    first_name: Optional[str] = ""
    last_name: Optional[str] = ""
    phone: Optional[str] = ""
    address_1: Optional[str] = ""
    address_2: Optional[str] = ""
    city: Optional[str] = ""
    state: Optional[str] = ""
    postcode: Optional[str] = ""
    order_notes: Optional[str] = ""


class CheckoutSessionCreateRequest(BaseModel):
    items: List[CartItem]
    origin_url: str
    customer: CustomerInfo


class NewsletterRequest(BaseModel):
    email: EmailStr


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Kavyn API", version="3.1.0")
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
    wc_ok = False
    products = 0
    priced = 0
    source = "none"
    try:
        cat = get_catalogue()
        products = len(cat)
        priced = sum(
            1 for p in cat for v in (p.get("variants") or []) if float(v.get("price") or 0) > 0
        )
        source = "woocommerce" if (WC_STORE_URL and WC_KEY and _WC_VARIANT_MAP) else "fallback"
        wc_ok = source == "woocommerce"
    except Exception as e:
        source = f"error:{e}"

    return {
        "status": "ok",
        "version": "3.1.0",
        "stripe_configured": bool(stripe.api_key),
        "woocommerce_configured": bool(WC_STORE_URL and WC_KEY and WC_SECRET),
        "woocommerce_reachable": wc_ok,
        "catalog_source": source,
        "products": products,
        "variants_priced": priced,
        "ready_for_checkout": bool(stripe.api_key) and priced > 0,
        # legacy
        "stripe_prices_mapped": priced,
        "stripe_prices_needed": priced,
    }


@api.post("/stripe/sync")
def stripe_sync():
    global _CATALOGUE
    _CATALOGUE = None
    cat = get_catalogue(force=True)
    return {
        "ok": True,
        "products": len(cat),
        "variants_mapped": len(_WC_VARIANT_MAP),
        "message": "Catalogue refreshed from WooCommerce. Stripe Catalog is not used.",
        "ready_for_checkout": health()["ready_for_checkout"],
    }


@api.get("/stripe/mapping")
def stripe_mapping():
    get_catalogue()
    return {
        f"{k[0]}|{k[1]}": {
            "wc_product_id": v["wc_product_id"],
            "variation_id": v.get("variation_id"),
            "price": v["price"],
        }
        for k, v in sorted(_WC_VARIANT_MAP.items())
    }


@api.get("/products")
def list_products():
    return get_catalogue()


@api.post("/checkout/quote")
def checkout_quote(items: List[CartItem]):
    if not items:
        return {"line_items": [], "subtotal": 0, "shipping": 0, "tax": 0, "total": 0}
    order = _compute_order(items)
    return {
        "line_items": [
            {
                "product_id": li["product_id"],
                "name": li["name"],
                "unit_price": li["unit_price"],
                "quantity": li["quantity"],
                "line_total": li["line_total"],
            }
            for li in order["line_items"]
        ],
        "subtotal": order["subtotal"],
        "shipping": order["shipping"],
        "tax": order["tax"],
        "total": order["total"],
    }


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

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            # Checkout Sessions automatically offer every payment method you've
            # enabled in the Stripe Dashboard (Settings -> Payment methods) —
            # cards, Apple Pay, Google Pay, Link, etc. Do NOT pass
            # `automatic_payment_methods` here: that parameter belongs to the
            # PaymentIntents API, not Checkout Sessions, and Stripe will reject
            # the request with "Received unknown parameter" if it's included.
            line_items=order["stripe_lines"],
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=cust.get("email"),
            shipping_address_collection={"allowed_countries": ["CA"]},
            phone_number_collection={"enabled": True},
            billing_address_collection="auto",
            metadata={
                "source": "kavyn",
                "email": cust.get("email") or "",
                "items": ",".join(
                    f"{li['product_id']}:{li['size']}x{li['quantity']}"
                    for li in order["line_items"]
                ),
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
        "wc_lines": order["wc_lines"],
        "order": {
            "subtotal": order["subtotal"],
            "shipping": order["shipping"],
            "tax": order["tax"],
            "total": order["total"],
        },
        "payment_status": "initiated",
    }
    _TX_MEMORY[session.id] = tx
    _append_lead({
        "type": "checkout_started",
        "email": cust.get("email"),
        "session_id": session.id,
        "cart": order["line_items"],
        "total": order["total"],
    })
    return {"url": session.url, "session_id": session.id}


@api.get("/checkout/status/{session_id}")
def checkout_status(session_id: str):
    """Poll after redirect from Stripe. If paid, create the WooCommerce order."""
    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    try:
        session = stripe.checkout.Session.retrieve(
            session_id,
            expand=["customer_details", "shipping_details"],
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    tx = _TX_MEMORY.get(session_id) or {
        "session_id": session_id,
        "email": (session.customer_details.email if session.customer_details else None),
        "cart": [],
        "order": {},
    }

    wc_order = None
    wc_error = None
    if session.payment_status == "paid" and not tx.get("wc_order_id"):
        try:
            # Ensure catalogue/maps loaded
            get_catalogue()
            wc_order = create_woocommerce_order_from_session(session, tx)
        except HTTPException as e:
            wc_error = e.detail
        except Exception as e:
            wc_error = str(e)

    return {
        "session_id": session_id,
        "payment_status": session.payment_status,
        "status": session.status,
        "order": tx.get("order"),
        "customer": tx.get("customer"),
        "cart": tx.get("cart"),
        "wc_order_id": tx.get("wc_order_id"),
        "wc_order_number": tx.get("wc_order_number"),
        "wc_order_error": wc_error,
    }


@api.post("/stripe/webhook")
async def stripe_webhook(request: FastAPIRequest):
    """Stripe webhook: on checkout.session.completed → create WC order."""
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    if STRIPE_WEBHOOK_SECRET:
        try:
            event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Webhook signature error: {e}") from e
    else:
        try:
            event = json.loads(payload)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    etype = event.get("type") if isinstance(event, dict) else getattr(event, "type", None)
    data_obj = event.get("data", {}).get("object") if isinstance(event, dict) else event.data.object

    if etype == "checkout.session.completed":
        session_id = data_obj.get("id") if isinstance(data_obj, dict) else data_obj.id
        try:
            session = stripe.checkout.Session.retrieve(
                session_id,
                expand=["customer_details", "shipping_details"],
            )
        except Exception as e:
            return {"ok": False, "error": str(e)}

        if session.payment_status != "paid":
            return {"ok": True, "skipped": "not_paid"}

        tx = _TX_MEMORY.get(session_id) or {
            "session_id": session_id,
            "email": session.customer_details.email if session.customer_details else "",
            "cart": [],
            "order": {"total": (session.amount_total or 0) / 100},
        }
        # Recover cart from metadata if memory was lost (e.g. after redeploy)
        if not tx.get("cart") and session.metadata:
            items_meta = (session.metadata.get("items") or "")
            # format product_id:sizexqty
            recovered = []
            for part in items_meta.split(","):
                part = part.strip()
                if not part:
                    continue
                try:
                    left, qty_s = part.rsplit("x", 1)
                    pid, size = left.split(":", 1)
                    recovered.append({
                        "product_id": pid,
                        "size": size,
                        "quantity": int(qty_s),
                        "name": pid,
                        "line_total": 0,
                    })
                except Exception:
                    continue
            tx["cart"] = recovered

        get_catalogue()
        try:
            order = create_woocommerce_order_from_session(session, tx)
            return {"ok": True, "wc_order_id": order.get("id"), "session_id": session_id}
        except Exception as e:
            return {"ok": False, "error": str(e), "session_id": session_id}

    return {"ok": True, "ignored": etype}


@api.post("/newsletter/subscribe")
def newsletter_subscribe(body: NewsletterRequest):
    email = body.email.lower().strip()
    _NEWSLETTER.add(email)
    _append_lead({"type": "newsletter_signup", "email": email})
    return {"ok": True, "message": "Thank you — you are on the list."}


@api.get("/leads")
def list_leads():
    if not LEADS_FILE.exists():
        return []
    leads = []
    for line in LEADS_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            leads.append(json.loads(line))
        except Exception:
            continue
    return leads


app.include_router(api)


@app.get("/")
def root():
    return {
        "service": "kavyn-api",
        "version": "3.1.0",
        "health": "/api/health",
        "docs": "/docs",
        "flow": "WooCommerce catalog → Stripe payment (address+phone) → WooCommerce order",
    }

from fastapi import FastAPI, HTTPException, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional, List
import httpx
import os
import json
import base64
import secrets
from datetime import datetime, timedelta
import jwt

app = FastAPI(title="RIORIX API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Config ───────────────────────────────────────────────────────────────────
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "YOUR_GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "YOUR_GOOGLE_CLIENT_SECRET")
REDIRECT_URI         = os.getenv("REDIRECT_URI", "http://localhost:8000/auth/callback")
FRONTEND_URL         = os.getenv("FRONTEND_URL", "http://localhost:3000")
JWT_SECRET           = os.getenv("JWT_SECRET", "riorix-super-secret-jwt-key-change-in-prod")
JWT_ALGO             = "HS256"

GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USER_URL  = "https://www.googleapis.com/oauth2/v2/userinfo"
GMAIL_API_BASE   = "https://gmail.googleapis.com/gmail/v1"

# ─── In-memory stores (replace with DB in production) ─────────────────────────
users_db: dict = {}        # user_id -> user info
tokens_db: dict = {}       # user_id -> tokens
sessions_db: dict = {}     # session_token -> user_id
state_store: dict = {}     # state -> timestamp (CSRF protection)
orders_db: list = []       # mock orders
cart_db: dict = {}         # user_id -> cart items

# ─── Products ─────────────────────────────────────────────────────────────────
PRODUCTS = [
    {"id": "1",  "name": "Obsidian Chronograph",     "price": 489,  "category": "watches",     "image": "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=600&q=80", "badge": "Bestseller", "rating": 4.9, "reviews": 312, "description": "Swiss movement, sapphire crystal, 100m water resistance."},
    {"id": "2",  "name": "Noir Leather Jacket",      "price": 349,  "category": "apparel",     "image": "https://images.unsplash.com/photo-1551028719-00167b16eac5?w=600&q=80", "badge": "New",        "rating": 4.8, "reviews": 187, "description": "Full-grain Italian leather, quilted lining, slim fit."},
    {"id": "3",  "name": "Carbon Messenger Bag",     "price": 229,  "category": "bags",        "image": "https://images.unsplash.com/photo-1548036328-c9fa89d128fa?w=600&q=80", "badge": None,         "rating": 4.7, "reviews": 94,  "description": "Ballistic nylon, YKK zippers, padded laptop sleeve."},
    {"id": "4",  "name": "Titanium Sunglasses",      "price": 189,  "category": "accessories", "image": "https://images.unsplash.com/photo-1572635196237-14b3f281503f?w=600&q=80", "badge": "Limited",    "rating": 4.6, "reviews": 56,  "description": "Polarized lenses, titanium frames, UV400 protection."},
    {"id": "5",  "name": "Merino Turtleneck",        "price": 129,  "category": "apparel",     "image": "https://images.unsplash.com/photo-1576566588028-4147f3842f27?w=600&q=80", "badge": None,         "rating": 4.8, "reviews": 203, "description": "100% Merino wool, anti-odor, machine washable."},
    {"id": "6",  "name": "Stealth Sneakers",         "price": 279,  "category": "footwear",    "image": "https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=600&q=80", "badge": "Hot",         "rating": 4.9, "reviews": 441, "description": "Memory foam insole, carbon rubber outsole, breathable mesh."},
    {"id": "7",  "name": "Executive Slim Wallet",    "price": 89,   "category": "accessories", "image": "https://images.unsplash.com/photo-1627123424574-724758594e93?w=600&q=80", "badge": None,         "rating": 4.5, "reviews": 128, "description": "RFID blocking, full-grain leather, holds 8 cards."},
    {"id": "8",  "name": "Phantom Hoodie",           "price": 159,  "category": "apparel",     "image": "https://images.unsplash.com/photo-1556821840-3a63f15732ce?w=600&q=80", "badge": "Sale",        "rating": 4.7, "reviews": 267, "description": "400GSM fleece, oversized fit, kangaroo pocket."},
    {"id": "9",  "name": "Matte Black Flask",        "price": 59,   "category": "accessories", "image": "https://images.unsplash.com/photo-1584568694244-14fbdf83bd30?w=600&q=80", "badge": None,         "rating": 4.6, "reviews": 89,  "description": "18oz stainless steel, keeps cold 24h, hot 12h."},
    {"id": "10", "name": "Tactical Backpack",        "price": 199,  "category": "bags",        "image": "https://images.unsplash.com/photo-1553062407-98eeb64c6a62?w=600&q=80", "badge": "Bestseller",  "rating": 4.8, "reviews": 356, "description": "40L capacity, MOLLE system, hidden anti-theft pocket."},
    {"id": "11", "name": "Ceramic Dive Watch",       "price": 699,  "category": "watches",     "image": "https://images.unsplash.com/photo-1587836374828-4dbafa94cf0e?w=600&q=80", "badge": "Luxury",     "rating": 5.0, "reviews": 78,  "description": "Ceramic bezel, 300m water resistance, automatic movement."},
    {"id": "12", "name": "Desert Chelsea Boots",     "price": 239,  "category": "footwear",    "image": "https://images.unsplash.com/photo-1638247025967-b4e38f787b76?w=600&q=80", "badge": None,         "rating": 4.7, "reviews": 145, "description": "Suede upper, crepe rubber sole, elastic side panels."},
]

# ─── Schemas ──────────────────────────────────────────────────────────────────
class CartItem(BaseModel):
    product_id: str
    quantity: int

class OrderCreate(BaseModel):
    items: List[CartItem]
    shipping_address: str
    payment_method: str = "card"

# ─── Auth helpers ─────────────────────────────────────────────────────────────
def create_session_token(user_id: str) -> str:
    payload = {"sub": user_id, "exp": datetime.utcnow() + timedelta(days=7)}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

def get_current_user(request: Request) -> Optional[dict]:
    token = request.cookies.get("riorix_session") or request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        user_id = payload.get("sub")
        return users_db.get(user_id)
    except Exception:
        return None

def require_auth(request: Request) -> dict:
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

# ─── Auth Routes ──────────────────────────────────────────────────────────────
@app.get("/auth/login")
def login():
    state = secrets.token_urlsafe(16)
    state_store[state] = datetime.utcnow()
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly",
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    url = GOOGLE_AUTH_URL + "?" + "&".join(f"{k}={v}" for k, v in params.items())
    return {"auth_url": url}

@app.get("/auth/callback")
async def callback(code: str, state: str, response: Response):
    if state not in state_store:
        raise HTTPException(status_code=400, detail="Invalid state parameter")
    del state_store[state]

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        })
        tokens = token_resp.json()

        user_resp = await client.get(GOOGLE_USER_URL, headers={
            "Authorization": f"Bearer {tokens['access_token']}"
        })
        user_info = user_resp.json()

    user_id = user_info["id"]
    users_db[user_id] = {
        "id": user_id,
        "email": user_info["email"],
        "name": user_info["name"],
        "picture": user_info.get("picture"),
        "joined": datetime.utcnow().isoformat(),
    }
    tokens_db[user_id] = tokens

    session_token = create_session_token(user_id)
    redirect = RedirectResponse(url=f"{FRONTEND_URL}?session={session_token}")
    redirect.set_cookie("riorix_session", session_token, httponly=True, samesite="lax", max_age=604800)
    return redirect

@app.post("/auth/logout")
def logout(response: Response):
    response.delete_cookie("riorix_session")
    return {"message": "Logged out"}

@app.get("/auth/me")
def me(request: Request):
    user = get_current_user(request)
    if not user:
        return {"user": None}
    return {"user": user}

# ─── Products ─────────────────────────────────────────────────────────────────
@app.get("/products")
def get_products(category: Optional[str] = None, search: Optional[str] = None):
    items = PRODUCTS
    if category and category != "all":
        items = [p for p in items if p["category"] == category]
    if search:
        s = search.lower()
        items = [p for p in items if s in p["name"].lower() or s in p["description"].lower()]
    return {"products": items, "total": len(items)}

@app.get("/products/{product_id}")
def get_product(product_id: str):
    product = next((p for p in PRODUCTS if p["id"] == product_id), None)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

# ─── Cart ─────────────────────────────────────────────────────────────────────
@app.get("/cart")
def get_cart(request: Request):
    user = require_auth(request)
    cart = cart_db.get(user["id"], [])
    enriched = []
    for item in cart:
        product = next((p for p in PRODUCTS if p["id"] == item["product_id"]), None)
        if product:
            enriched.append({**item, "product": product})
    return {"cart": enriched}

@app.post("/cart")
def add_to_cart(item: CartItem, request: Request):
    user = require_auth(request)
    uid = user["id"]
    cart = cart_db.get(uid, [])
    existing = next((i for i in cart if i["product_id"] == item.product_id), None)
    if existing:
        existing["quantity"] += item.quantity
    else:
        cart.append({"product_id": item.product_id, "quantity": item.quantity})
    cart_db[uid] = cart
    return {"message": "Added to cart", "cart_count": sum(i["quantity"] for i in cart)}

@app.delete("/cart/{product_id}")
def remove_from_cart(product_id: str, request: Request):
    user = require_auth(request)
    uid = user["id"]
    cart_db[uid] = [i for i in cart_db.get(uid, []) if i["product_id"] != product_id]
    return {"message": "Removed from cart"}

@app.delete("/cart")
def clear_cart(request: Request):
    user = require_auth(request)
    cart_db[user["id"]] = []
    return {"message": "Cart cleared"}

# ─── Orders ───────────────────────────────────────────────────────────────────
@app.post("/orders")
async def create_order(order: OrderCreate, request: Request):
    user = require_auth(request)
    uid = user["id"]

    items_detail = []
    total = 0
    for item in order.items:
        product = next((p for p in PRODUCTS if p["id"] == item.product_id), None)
        if product:
            subtotal = product["price"] * item.quantity
            total += subtotal
            items_detail.append({**item.dict(), "product": product, "subtotal": subtotal})

    order_record = {
        "id": f"RIO-{len(orders_db)+1001}",
        "user_id": uid,
        "user_email": user["email"],
        "items": items_detail,
        "total": total,
        "shipping_address": order.shipping_address,
        "payment_method": order.payment_method,
        "status": "confirmed",
        "created_at": datetime.utcnow().isoformat(),
    }
    orders_db.append(order_record)
    cart_db[uid] = []

    # Send confirmation email via Gmail API
    tokens = tokens_db.get(uid)
    if tokens and tokens.get("access_token"):
        await send_order_confirmation_email(user, order_record, tokens["access_token"])

    return {"order": order_record, "message": "Order placed successfully!"}

@app.get("/orders")
def get_orders(request: Request):
    user = require_auth(request)
    user_orders = [o for o in orders_db if o["user_id"] == user["id"]]
    return {"orders": user_orders}

# ─── Gmail ────────────────────────────────────────────────────────────────────
async def send_order_confirmation_email(user: dict, order: dict, access_token: str):
    items_html = "".join(
        f"<tr><td style='padding:8px;border-bottom:1px solid #222'>{i['product']['name']}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #222'>x{i['quantity']}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #222'>${i['subtotal']}</td></tr>"
        for i in order["items"]
    )
    email_html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#0a0a0a;font-family:'Helvetica Neue',sans-serif;color:#fff">
  <div style="max-width:600px;margin:0 auto;padding:40px 20px">
    <div style="text-align:center;margin-bottom:40px">
      <h1 style="font-size:32px;letter-spacing:0.15em;margin:0;color:#fff">RIORIX</h1>
      <p style="color:#666;margin:4px 0 0;font-size:13px;letter-spacing:0.1em">ORDER CONFIRMED</p>
    </div>
    <div style="background:#111;border:1px solid #222;border-radius:12px;padding:32px;margin-bottom:24px">
      <p style="color:#aaa;font-size:14px;margin:0 0 4px">Hello, {user['name']}</p>
      <h2 style="font-size:20px;margin:0 0 24px;color:#fff">Your order is confirmed.</h2>
      <div style="background:#0a0a0a;border-radius:8px;padding:16px;margin-bottom:20px">
        <p style="margin:0 0 8px;color:#666;font-size:12px;letter-spacing:0.1em">ORDER ID</p>
        <p style="margin:0;font-size:18px;font-weight:600;letter-spacing:0.05em;color:#fff">{order['id']}</p>
      </div>
      <table style="width:100%;border-collapse:collapse">
        <thead>
          <tr style="background:#1a1a1a">
            <th style="padding:10px 8px;text-align:left;font-size:11px;letter-spacing:0.1em;color:#666">ITEM</th>
            <th style="padding:10px 8px;text-align:left;font-size:11px;letter-spacing:0.1em;color:#666">QTY</th>
            <th style="padding:10px 8px;text-align:left;font-size:11px;letter-spacing:0.1em;color:#666">PRICE</th>
          </tr>
        </thead>
        <tbody>{items_html}</tbody>
      </table>
      <div style="text-align:right;margin-top:20px;padding-top:16px;border-top:1px solid #222">
        <span style="color:#666;font-size:13px">TOTAL  </span>
        <span style="font-size:22px;font-weight:700;color:#fff">${order['total']}</span>
      </div>
    </div>
    <p style="color:#444;font-size:12px;text-align:center;margin:0">
      RIORIX · Premium Commerce · {datetime.utcnow().strftime('%B %d, %Y')}
    </p>
  </div>
</body>
</html>"""

    raw_email = f"""From: {user['email']}
To: {user['email']}
Subject: Order {order['id']} Confirmed — RIORIX
MIME-Version: 1.0
Content-Type: text/html; charset=utf-8

{email_html}"""

    encoded = base64.urlsafe_b64encode(raw_email.encode()).decode()

    async with httpx.AsyncClient() as client:
        await client.post(
            f"{GMAIL_API_BASE}/users/me/messages/send",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json={"raw": encoded},
        )

@app.get("/gmail/inbox")
async def get_inbox(request: Request):
    user = require_auth(request)
    tokens = tokens_db.get(user["id"])
    if not tokens:
        raise HTTPException(status_code=403, detail="Gmail not connected")

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GMAIL_API_BASE}/users/me/messages?maxResults=5&labelIds=INBOX",
            headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        data = resp.json()
        messages = []
        for m in data.get("messages", []):
            msg_resp = await client.get(
                f"{GMAIL_API_BASE}/users/me/messages/{m['id']}?format=metadata&metadataHeaders=Subject,From,Date",
                headers={"Authorization": f"Bearer {tokens['access_token']}"}
            )
            msg = msg_resp.json()
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            messages.append({
                "id": m["id"],
                "subject": headers.get("Subject", "(no subject)"),
                "from": headers.get("From", ""),
                "date": headers.get("Date", ""),
            })
    return {"messages": messages}

@app.get("/")
def root():
    return {"name": "RIORIX API", "version": "1.0.0", "status": "running"}
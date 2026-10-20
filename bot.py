import os
import sqlite3
import logging
import json
import re
from datetime import datetime
from io import BytesIO

from openpyxl import load_workbook
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters
)

BOT_TOKEN = "8900969328:AAEcb6jqPiufRRkoDVK3IySbdb23CRrmJ4g"
OWNER_ID = 7504951264  # Replace with your numeric Telegram user ID
DB_FILE = "shop_bot.sqlite3"
MAIL_CODE_URL = "https://dongvanfb.net/get_code_mail/"
SUPPORT_URL = "https://t.me/shadow8368"

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger("shopbot")

def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, balance REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS products(
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
            price REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS categories(
            id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER NOT NULL,
            name TEXT NOT NULL, price REAL NOT NULL DEFAULT 0,
            stock_headers TEXT NOT NULL DEFAULT '[]',
            UNIQUE(product_id,name),
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS stock(
            id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER NOT NULL,
            item TEXT NOT NULL, sold INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS deposits(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            method TEXT NOT NULL, amount REAL NOT NULL, trx TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            product TEXT NOT NULL, category TEXT NOT NULL, qty INTEGER NOT NULL,
            total REAL NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        category_columns = [row["name"] for row in c.execute("PRAGMA table_info(categories)").fetchall()]
        if "price" not in category_columns:
            c.execute("ALTER TABLE categories ADD COLUMN price REAL NOT NULL DEFAULT 0")
        if "stock_headers" not in category_columns:
            c.execute("ALTER TABLE categories ADD COLUMN stock_headers TEXT NOT NULL DEFAULT '[]'")
        for method in ("bKash", "Nagad", "Rocket"):
            c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
                      ("pay_" + method.lower(), "01857656785"))
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('force_channel','')")
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('force_channel_url','')")
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('force_channel_name','')")
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('currency','BDT')")
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('min_deposit','10')")

def setting(key, default=""):
    with db() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

def set_setting(key, value):
    with db() as c:
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

def is_owner(update):
    u = update.effective_user
    return bool(u and u.id == OWNER_ID)

def e(name, fallback=""):
    emoji_dict = {
        "ok": '<tg-emoji emoji-id="5352694861990501856">✅</tg-emoji>',
        "no": '<tg-emoji emoji-id="5420130255174145507">❌</tg-emoji>',
        "warn": '<tg-emoji emoji-id="5336944168944047463">⚠️</tg-emoji>',
        "admin": '<tg-emoji emoji-id="5353032893096567467">📊</tg-emoji>',
        "user": '<tg-emoji emoji-id="5352861489541714456">👤</tg-emoji>',
        "file": '<tg-emoji emoji-id="5352721946054268944">📁</tg-emoji>',
        "rocket": '<tg-emoji emoji-id="5352597830089347330">🚀</tg-emoji>',
        "graph": '<tg-emoji emoji-id="5352877703043258544">📊</tg-emoji>',
        "money": '<tg-emoji emoji-id="5348469219761626211">💸</tg-emoji>',
        "gift": '<tg-emoji emoji-id="5420396762189831222">🎁</tg-emoji>',
        "msg": '<tg-emoji emoji-id="5337302974806922068">💬</tg-emoji>',
        "gear": '<tg-emoji emoji-id="5420155432272438703">⚙️</tg-emoji>',
        "link": '<tg-emoji emoji-id="5420517437885943844">🔗</tg-emoji>',
        "trash": '<tg-emoji emoji-id="5422557736330106570">🗑</tg-emoji>',
        "upload": '<tg-emoji emoji-id="5353001161878182134">📤</tg-emoji>',
        "world": '<tg-emoji emoji-id="5336972142066047577">🌐</tg-emoji>',
        "lock": '<tg-emoji emoji-id="5353022963132174959">🔐</tg-emoji>',
        "phone": '<tg-emoji emoji-id="5337132498965010628">📱</tg-emoji>',
        "num": '<tg-emoji emoji-id="5352862640592949843">🔢</tg-emoji>',
        "pin": '<tg-emoji emoji-id="5352922460897452503">📍</tg-emoji>',
        "star": '<tg-emoji emoji-id="5352552689983067014">✨</tg-emoji>',
        "hi": '<tg-emoji emoji-id="5353027129250453493">👋</tg-emoji>',
        "cart": '<tg-emoji emoji-id="5352597830089347330">🛒</tg-emoji>',
        "key": '<tg-emoji emoji-id="5197288647275071607">🔑</tg-emoji>',
        "diamond": '<tg-emoji emoji-id="6203886371363364022">💎</tg-emoji>',
        "card": '<tg-emoji emoji-id="5190899075968441286">💳</tg-emoji>',
        "support": '<tg-emoji emoji-id="5418063924933173277">🎧</tg-emoji>',
        "package": '<tg-emoji emoji-id="5352721946054268944">📦</tg-emoji>',
        "bkash": '<tg-emoji emoji-id="6084377871265041519">💵</tg-emoji>'
    }
    return emoji_dict.get(name, fallback)

def extract_emoji_id(msg):
    if isinstance(msg, dict) and "entities" in msg:
        for ent in msg["entities"]:
            if ent["type"] == "custom_emoji":
                return ent.get("custom_emoji_id")
    text = msg.get("text", "").strip() if isinstance(msg, dict) else str(msg).strip()
    match = re.search(r'emoji-id="(\d+)"', text)
    if match:
        return match.group(1)
    if text.isdigit():
        return text
    return text

def chunk_list(lst, n=2):
    return [lst[i:i + n] for i in range(0, len(lst), n)]

def ensure_user(user_id, referrer_id=None):
    with db() as c:
        user = c.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not user:
            c.execute("INSERT INTO users(user_id,created_at) VALUES(?,?)",
                      (user_id, datetime.now().isoformat(timespec="seconds")))
            if referrer_id and referrer_id != user_id:
                ref_user = c.execute("SELECT user_id FROM users WHERE user_id=?", (referrer_id,)).fetchone()
                if ref_user:
                    c.execute("UPDATE users SET balance = balance + 0.20 WHERE user_id=?", (referrer_id,))
                    return referrer_id
        return None

def main_keyboard(user_id):
    keyboard_layout = [
        [
            {
                "text": "SHOP NOW",
                "icon_custom_emoji_id": "6208478331352913380",
                "style": "success"
            },
            {
                "text": "REFER",
                "icon_custom_emoji_id": "6244678063775289843",
                "style": "success"
            }
        ],
        [
            {
                "text": "MAIL CODE",
                "icon_custom_emoji_id": "6161486965318363916",
                "style": "primary"
            }
        ],
        [
            {
                "text": "DEPOSIT",
                "icon_custom_emoji_id": "6183896704509549822",
                "style": "success"
            },
            {
                "text": "PROFILE",
                "icon_custom_emoji_id": "6230914579082253512",
                "style": "success"
            }
        ],
        [
            {
                "text": "SUPPORT",
                "icon_custom_emoji_id": "5354889508674360491",
                "style": "danger"
            }
        ]
    ]
    if user_id == OWNER_ID:
        keyboard_layout.append([
            {"text": "⚙️ ADMIN PANEL", "style": "danger"}
        ])
    return ReplyKeyboardMarkup.de_json({"keyboard": keyboard_layout, "resize_keyboard": True}, bot=None)

def admin_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add product", callback_data="adm:add_product", style="success"),
            InlineKeyboardButton("🗑 Delete product", callback_data="adm:del_product", style="danger")
        ],
        [
            InlineKeyboardButton("➕ Add category + Excel stock", callback_data="adm:add_category", style="success"),
            InlineKeyboardButton("🗑 Delete category", callback_data="adm:del_category", style="danger")
        ],
        [
            InlineKeyboardButton("💵 Category prices", callback_data="adm:price", style="primary"),
            InlineKeyboardButton("📱 Change deposit numbers", callback_data="adm:pay", style="success")
        ],
        [
            InlineKeyboardButton("📢 Force-join channel", callback_data="adm:force", style="primary"),
            InlineKeyboardButton("👥 User / balance tools", callback_data="adm:users", style="primary")
        ],
        [
            InlineKeyboardButton("📦 Stock & order stats", callback_data="adm:stats", style="primary"),
            InlineKeyboardButton("❌ Close", callback_data="adm:close", style="danger")
        ]
    ])

async def check_join(user_id, context):
    channel = setting("force_channel").strip()
    if not channel:
        return True
    try:
        member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
        return member.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR,
                                 ChatMemberStatus.OWNER)
    except Exception as e:
        log.warning("Could not verify channel membership: %s", e)
        return False

async def join_prompt(update, context):
    url = setting("force_channel_url")
    name = setting("force_channel_name") or "our channel"
    rows = []
    if url:
        rows.append([InlineKeyboardButton("📢 Join channel", url=url, style="primary")])
    rows.append([InlineKeyboardButton("✅ Verify", callback_data="join:verify", style="success")])
    text = f"Please join {name}, then press Verify."
    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(rows))
    else:
        await update.effective_message.reply_text(text, reply_markup=InlineKeyboardMarkup(rows))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    referrer_id = None
    
    if context.args:
        try:
            referrer_id = int(context.args[0])
        except ValueError:
            pass

    rewarded_referrer = ensure_user(user.id, referrer_id)
    if rewarded_referrer:
        try:
            await context.bot.send_message(
                chat_id=rewarded_referrer,
                text="🎉 Congratulations! Someone joined using your referral link, and you received **0.20 BDT** bonus!"
            )
        except Exception:
            pass

    if not await check_join(user.id, context):
        await join_prompt(update, context)
        return
    context.user_data.pop("state", None)
    await update.effective_message.reply_text(
        "Welcome! Choose an option below.", reply_markup=main_keyboard(user.id)
    )

async def on_join_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if await check_join(q.from_user.id, context):
        await q.message.reply_text("Verified! You can use the bot now.",
                                   reply_markup=main_keyboard(q.from_user.id))
    else:
        await q.message.reply_text("I couldn't verify your membership. Join the channel first, then try again.")

def products_keyboard(prefix="shop:product"):
    with db() as c:
        rows = c.execute("SELECT id,name FROM products ORDER BY id DESC").fetchall()
    
    buttons = []
    for r in rows:
        p_name = r["name"].strip().upper()
        emoji_id = None
        if "VPN" in p_name:
            emoji_id = "6037533655105016950"
        elif "MAIL" in p_name:
            emoji_id = "6194998963041476799"
        elif "PROXY" in p_name:
            emoji_id = "5796407074346767851"
        
        btn_dict = {
            "text": r["name"],
            "callback_data": f"{prefix}:{r['id']}",
            "style": "primary"
        }
        if emoji_id:
            btn_dict["icon_custom_emoji_id"] = emoji_id
        
        buttons.append([InlineKeyboardButton.de_json(btn_dict, bot=None)])

    if not buttons:
        buttons = [[InlineKeyboardButton("No products available", callback_data="noop", style="danger")]]
    return InlineKeyboardMarkup(buttons)

async def shop_now(update, context):
    if not await check_join(update.effective_user.id, context):
        await join_prompt(update, context)
        return
    await update.effective_message.reply_text("Choose a product:", reply_markup=products_keyboard())

async def show_categories(q, product_id):
    with db() as c:
        p = c.execute(
            "SELECT * FROM products WHERE id=?",
            (product_id,)
        ).fetchone()

        cats = c.execute("""
            SELECT
                categories.id,
                categories.name,
                categories.price,
                (
                    SELECT COUNT(*)
                    FROM stock
                    WHERE stock.category_id = categories.id
                    AND stock.sold = 0
                ) AS stock_count
            FROM categories
            WHERE categories.product_id = ?
            ORDER BY categories.id DESC
        """, (product_id,)).fetchall()

    if not p:
        await q.message.reply_text("Product not found.")
        return

    buttons = []

    for cat in cats:
        price = float(cat["price"])
        stock_count = int(cat["stock_count"])

        button_text = (
            f"{cat['name']} - {price:g} TK "
            f"(Stock {stock_count})"
        )

        buttons.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"shop:category:{cat['id']}",
                style="success"
            )
        ])

    if not buttons:
        await q.message.reply_text(
            "No categories available for this product."
        )
        return

    await q.message.reply_text(
        f"🛒 Product: {p['name']}\n"
        "👇 Choose your category:\n\n"
        "💰 Price and available stock are shown below.",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    uid = q.from_user.id
    ensure_user(uid)

    if data == "noop":
        return
    if data == "join:verify":
        await on_join_verify(update, context)
        return

    if data.startswith("shop:product:"):
        await show_categories(q, int(data.rsplit(":", 1)[1]))
        return
    if data.startswith("shop:category:"):
        cat_id = int(data.rsplit(":", 1)[1])
        with db() as c:
            row = c.execute("""SELECT categories.id,categories.name,categories.price,
                               products.name AS product FROM categories JOIN products
                               ON products.id=categories.product_id WHERE categories.id=?""",
                            (cat_id,)).fetchone()
            stock_count = c.execute("SELECT COUNT(*) n FROM stock WHERE category_id=? AND sold=0",
                                    (cat_id,)).fetchone()["n"]
        if not row:
            await q.message.reply_text("Category not found.")
            return
        context.user_data["state"] = "buy_quantity"
        context.user_data["buy"] = {"category_id": cat_id, "product": row["product"],
                                    "category": row["name"], "price": float(row["price"])}
        await q.message.reply_text(
            f"{row['product']} / {row['name']}\nCategory price: {row['price']:.2f} BDT each\n"
            f"Available stock: {stock_count}\nSend the quantity you want to buy:"
        )
        return

    if data.startswith("deposit:method:"):
        method = data.split(":")[-1]
        context.user_data["state"] = "deposit_amount"
        context.user_data["deposit_method"] = method
        
        num = setting("pay_" + method.lower(), "01857656785")
        p_min_dep = float(setting("min_deposit", "10"))
        
        msg_text = (
            f"{e('card')} <b>{method}</b> এর মাধ্যমে টাকা পাঠাতে নিচের নাম্বারে <b>সেন্ড মানি করুন</b>:\n\n"
            f"📌 নাম্বার/একাউন্ট: <code>{num}</code>\n"
            f"📌 <i>এই মাধ্যমের সর্বনিম্ন ডিপোজিট: ৳{p_min_dep:g}</i>\n\n"
            f"আপনি কত টাকা ডিপোজিট করেছেন? (শুধু টাকার পরিমাণ সংখ্যায় লিখুন):"
        )
        await context.bot.send_message(chat_id=uid, text=msg_text, parse_mode="HTML")
        return

    if data.startswith("deposit:accept:") or data.startswith("deposit:reject:"):
        if uid != OWNER_ID:
            await q.message.reply_text("Not authorized.")
            return
        action, dep_id = data.split(":")[1], int(data.split(":")[2])
        with db() as c:
            dep = c.execute("SELECT * FROM deposits WHERE id=?", (dep_id,)).fetchone()
            if not dep or dep["status"] != "pending":
                await q.message.reply_text("This deposit has already been processed.")
                return
            if action == "accept":
                c.execute("UPDATE users SET balance=balance+? WHERE user_id=?",
                          (dep["amount"], dep["user_id"]))
                c.execute("UPDATE deposits SET status='accepted' WHERE id=?", (dep_id,))
            else:
                c.execute("UPDATE deposits SET status='rejected' WHERE id=?", (dep_id,))
        if action == "accept":
            await context.bot.send_message(dep["user_id"],
                f"{e('ok')} Deposit successful!\nAmount: {dep['amount']:.2f} BDT\nReference: #{dep_id}")
            await q.message.reply_text(f"Accepted deposit #{dep_id}.")
        else:
            await context.bot.send_message(dep["user_id"],
                f"{e('no')} Deposit #{dep_id} was rejected. Contact support if you think this is a mistake.")
            await q.message.reply_text(f"Rejected deposit #{dep_id}.")
        return

    if data.startswith("adm:"):
        if uid != OWNER_ID:
            await q.message.reply_text("Not authorized.")
            return
        action = data.split(":")[1]
        if action == "close":
            await q.message.reply_text("Admin panel closed.")
        elif action == "add_product":
            context.user_data["state"] = "admin_add_product_name"
            await q.message.reply_text("Send the new product name:")
        elif action == "del_product":
            await q.message.reply_text("Choose a product to delete:",
                                       reply_markup=products_keyboard("admdeleteproduct"))
        elif action == "add_category":
            context.user_data["state"] = "admin_choose_product_for_category"
            await q.message.reply_text("Choose the product for this category:",
                                       reply_markup=products_keyboard("admcatproduct"))
        elif action == "del_category":
            with db() as c:
                cats = c.execute("""SELECT categories.id,categories.name,products.name AS product
                    FROM categories JOIN products ON products.id=categories.product_id
                    ORDER BY products.name,categories.name""").fetchall()
            buttons = [[InlineKeyboardButton(f"{x['product']} / {x['name']}",
                                             callback_data=f"admdeletecategory:{x['id']}", style="danger")] for x in cats]
            await q.message.reply_text("Choose a category to delete:",
                reply_markup=InlineKeyboardMarkup(buttons) if buttons else None)
        elif action == "price":
            with db() as c:
                cats = c.execute("""SELECT categories.id,categories.name,products.name AS product
                    FROM categories JOIN products ON products.id=categories.product_id
                    ORDER BY products.name,categories.name""").fetchall()
            buttons = [[InlineKeyboardButton(f"{x['product']} / {x['name']}",
                                             callback_data=f"admcatprice:{x['id']}", style="primary")] for x in cats]
            await q.message.reply_text("Choose a category to change its price:",
                reply_markup=InlineKeyboardMarkup(buttons) if buttons else None)
        elif action == "pay":
            await q.message.reply_text("Choose a payment method:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("bKash", callback_data="admpay:bKash", style="success"),
                     InlineKeyboardButton("Nagad", callback_data="admpay:Nagad", style="success"),
                     InlineKeyboardButton("Rocket", callback_data="admpay:Rocket", style="success")]
                ]))
        elif action == "force":
            context.user_data["state"] = "admin_force_channel"
            await q.message.reply_text(
                "Send channel @username (the bot must be an admin there).\n"
                "Example: @mychannel\nSend /cancel to cancel."
            )
        elif action == "users":
            context.user_data["state"] = "admin_balance_user"
            await q.message.reply_text("Send the user's numeric Telegram ID to add/remove balance, or /cancel.")
        elif action == "stats":
            with db() as c:
                users = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
                products = c.execute("SELECT COUNT(*) n FROM products").fetchone()["n"]
                cats = c.execute("SELECT COUNT(*) n FROM categories").fetchone()["n"]
                stock = c.execute("SELECT COUNT(*) n FROM stock WHERE sold=0").fetchone()["n"]
                orders = c.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"]
                pending = c.execute("SELECT COUNT(*) n FROM deposits WHERE status='pending'").fetchone()["n"]
            await q.message.reply_text(
                f"Users: {users}\nProducts: {products}\nCategories: {cats}\n"
                f"Available stock items: {stock}\nOrders: {orders}\nPending deposits: {pending}",
                reply_markup=admin_keyboard()
            )
        return

    if data.startswith("admdeleteproduct:"):
        if uid != OWNER_ID: return
        pid = int(data.rsplit(":", 1)[1])
        with db() as c:
            c.execute("DELETE FROM stock WHERE category_id IN (SELECT id FROM categories WHERE product_id=?)", (pid,))
            c.execute("DELETE FROM categories WHERE product_id=?", (pid,))
            c.execute("DELETE FROM products WHERE id=?", (pid,))
        await q.message.reply_text("Product and its categories/stock deleted.", reply_markup=admin_keyboard())
        return

    if data.startswith("admcatproduct:"):
        if uid != OWNER_ID: return
        context.user_data["category_product_id"] = int(data.rsplit(":", 1)[1])
        context.user_data["state"] = "admin_add_category_name"
        await q.message.reply_text("Send the category name:")
        return

    if data.startswith("admdeletecategory:"):
        if uid != OWNER_ID: return
        cat_id = int(data.rsplit(":", 1)[1])
        with db() as c:
            c.execute("DELETE FROM stock WHERE category_id=?", (cat_id,))
            c.execute("DELETE FROM categories WHERE id=?", (cat_id,))
        await q.message.reply_text("Category and its stock deleted.", reply_markup=admin_keyboard())
        return

    if data.startswith("admcatprice:"):
        if uid != OWNER_ID: return
        context.user_data["price_category_id"] = int(data.rsplit(":", 1)[1])
        context.user_data["state"] = "admin_set_category_price"
        await q.message.reply_text("Send the new price for this category per item (numbers only):")
        return

    if data.startswith("admpay:"):
        if uid != OWNER_ID: return
        method = data.split(":")[1]
        context.user_data["payment_method_to_change"] = method
        context.user_data["state"] = "admin_set_pay_number"
        await q.message.reply_text(f"Send the new {method} number:")
        return

async def deposit_start(update, context):
    bkash_btn = InlineKeyboardButton.de_json({
        "text": "বিকাশ",
        "callback_data": "deposit:method:bKash",
        "style": "success",
        "icon_custom_emoji_id": "6318916225594295727"
    }, bot=None)
    
    nagad_btn = InlineKeyboardButton.de_json({
        "text": "নগদ",
        "callback_data": "deposit:method:Nagad",
        "style": "success",
        "icon_custom_emoji_id": "6172505618016900525"
    }, bot=None)
    
    rocket_btn = InlineKeyboardButton.de_json({
        "text": "রকেট",
        "callback_data": "deposit:method:Rocket",
        "style": "success",
        "icon_custom_emoji_id": "6084843995475742197"
    }, bot=None)

    await update.effective_message.reply_text(
        "Choose a deposit method:",
        reply_markup=InlineKeyboardMarkup([
            [bkash_btn, nagad_btn],
            [rocket_btn]
        ])
    )

async def profile(update, context):
    uid = update.effective_user.id
    ensure_user(uid)
    with db() as c:
        u = c.execute("SELECT balance,created_at FROM users WHERE user_id=?", (uid,)).fetchone()
        orders = c.execute("SELECT COUNT(*) n FROM orders WHERE user_id=?", (uid,)).fetchone()["n"]
        deposits = c.execute("SELECT COUNT(*) n FROM deposits WHERE user_id=?", (uid,)).fetchone()["n"]
    await update.effective_message.reply_text(
        f"👤 PROFILE\nID: {uid}\nBalance: {u['balance']:.2f} BDT\n"
        f"Orders: {orders}\nDeposit requests: {deposits}\nJoined: {u['created_at'][:10]}"
    )

async def refer_handler(update, context):
    uid = update.effective_user.id
    ensure_user(uid)
    bot_info = await context.bot.get_me()
    referral_link = f"https://t.me/{bot_info.username}?start={uid}"
    await update.effective_message.reply_text(
        f"🔗 **Your Referral Link:**\n\n`{referral_link}`\n\n"
        f"Share this link with your friends! When someone joins the bot using your link, you will get **0.20 BDT** bonus added to your balance.",
        parse_mode="Markdown"
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    uid = update.effective_user.id
    text = (msg.text or "").strip()
    ensure_user(uid)

    if text == "SHOP NOW":
        await shop_now(update, context); return
    if text == "MAIL CODE":
        await msg.reply_text("Open the link below:", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("MAIL CODE", url=MAIL_CODE_URL, style="primary")]
        ])); return
    if text == "SUPPORT":
        await msg.reply_text("Contact support:", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Contact Support", url=SUPPORT_URL, style="danger")]
        ])); return
    if text == "DEPOSIT":
        await deposit_start(update, context); return
    if text == "PROFILE":
        await profile(update, context); return
    if text == "REFER":
        await refer_handler(update, context); return
    if text == "⚙️ ADMIN PANEL":
        if uid == OWNER_ID:
            await msg.reply_text("Owner Admin Panel:", reply_markup=admin_keyboard())
        else:
            await msg.reply_text("Not authorized.")
        return
    if text == "/cancel":
        context.user_data.pop("state", None)
        await msg.reply_text("Cancelled.")
        return

    state = context.user_data.get("state")
    if not state:
        await msg.reply_text("Please choose an option from the menu.", reply_markup=main_keyboard(uid))
        return

    # Customer purchase quantity
    if state == "buy_quantity":
        try:
            qty = int(text)
            if qty < 1 or qty > 100:
                raise ValueError
        except ValueError:
            await msg.reply_text("Enter a whole number from 1 to 100.")
            return
        buy = context.user_data.get("buy")
        if not buy:
            context.user_data.pop("state", None)
            await msg.reply_text("Session expired. Please start again.")
            return
        total = qty * buy["price"]
        with db() as c:
            user = c.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
            available = c.execute("SELECT COUNT(*) n FROM stock WHERE category_id=? AND sold=0",
                                  (buy["category_id"],)).fetchone()["n"]
            if available < qty:
                await msg.reply_text(f"Not enough stock. Available: {available}")
                return
            if not user or user["balance"] < total:
                await msg.reply_text(
                    f"Insufficient balance.\nTotal: {total:.2f} BDT\n"
                    f"Your balance: {user['balance'] if user else 0:.2f} BDT\nPlease deposit first."
                )
                context.user_data.pop("state", None)
                return
            items = c.execute("SELECT id,item FROM stock WHERE category_id=? AND sold=0 ORDER BY id LIMIT ?",
                              (buy["category_id"], qty)).fetchall()
            c.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (total, uid))
            ids = [x["id"] for x in items]
            c.executemany("UPDATE stock SET sold=1 WHERE id=?", [(x,) for x in ids])
            c.execute("""INSERT INTO orders(user_id,product,category,qty,total,created_at)
                         VALUES(?,?,?,?,?,?)""",
                      (uid, buy["product"], buy["category"], qty, total,
                       datetime.now().isoformat(timespec="seconds")))
        context.user_data.pop("state", None)
        context.user_data.pop("buy", None)
        from openpyxl import Workbook
        excel_buffer = BytesIO()
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Order"
        worksheet.append(["Order ID", "Product", "Category", "Quantity", "Total (BDT)"])
        with db() as c:
            order_row = c.execute(
                "SELECT id FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,)
            ).fetchone()
        order_id = order_row["id"] if order_row else 0
        worksheet.append([order_id, buy["product"], buy["category"], qty, total])
        worksheet.append([])
        with db() as c:
            category_row = c.execute(
                "SELECT stock_headers FROM categories WHERE id=?", (buy["category_id"],)
            ).fetchone()
        try:
            stock_headers = json.loads(category_row["stock_headers"] or "[]") if category_row else []
        except (TypeError, json.JSONDecodeError):
            stock_headers = []
        parsed_items = []
        max_columns = 1
        for row in items:
            try:
                values = json.loads(row["item"])
                if not isinstance(values, list):
                    values = [row["item"]]
            except (TypeError, json.JSONDecodeError):
                values = [row["item"]]
            values = [("" if v is None else str(v)) for v in values]
            parsed_items.append(values)
            max_columns = max(max_columns, len(values))
        if len(stock_headers) < max_columns:
            stock_headers.extend([f"Option {chr(65+i)}" for i in range(len(stock_headers), max_columns)])
        worksheet.append(["No."] + stock_headers[:max_columns])
        for i, values in enumerate(parsed_items, start=1):
            worksheet.append([i] + values + [""] * (max_columns - len(values)))
        workbook.save(excel_buffer)
        excel_buffer.seek(0)
        filename = f"order_{order_id}.xlsx"
        await msg.reply_text(
            f"{e('ok')} Order completed!\nOrder ID: #{order_id}\n"
            f"Quantity: {qty}\nPaid: {total:.2f} BDT\n"
            "Your purchased items are attached in the Excel file.",
            reply_markup=main_keyboard(uid)
        )
        await context.bot.send_document(
            chat_id=uid,
            document=excel_buffer,
            filename=filename,
            caption=f"{e('package')} Order #{order_id} — {buy['product']} / {buy['category']}"
        )
        return

    # Deposit amount validation & prompt
    if state == "deposit_amount":
        try:
            amount = float(text)
            p_min_dep = float(setting("min_deposit", "10"))
            if amount < p_min_dep or amount > 1000000:
                await msg.reply_text(f"{e('no')} এই মাধ্যমে সর্বনিম্ন ডিপোজিট পরিমাণ ৳{p_min_dep:g} হতে হবে!\nদয়া করে সঠিক পরিমাণ দিন:")
                return
            
            context.user_data["deposit_amount"] = amount
            context.user_data["state"] = "deposit_trx"
            
            msg_text = f"{e('ok')} আপনি ৳ {amount:g} পাঠিয়েছেন। এখন ট্রানজেকশন আইডি (TrxID) দিন: {e('money')}"
            await msg.reply_text(msg_text, parse_mode="HTML")
        except ValueError:
            await msg.reply_text("সঠিক সংখ্যা লিখুন।")
        return

    if state == "deposit_trx":
        trx_id = text
        if len(trx_id) < 4 or len(trx_id) > 100:
            await msg.reply_text("Please send a valid transaction ID.")
            return
        
        method = context.user_data.get("deposit_method")
        amount = context.user_data.get("deposit_amount")
        
        user_name = msg.from_user.full_name or "User"
        user_uname = msg.from_user.username or "No Username"

        admin_text = (
            f"<tg-emoji emoji-id=\"6206185428702206246\">♻️</tg-emoji> <b>NEW DEPOSIT REQUEST!</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<tg-emoji emoji-id=\"5352861489541714456\">👤</tg-emoji> <b>Name:</b> {user_name}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<tg-emoji emoji-id=\"5354968347094046619\">🆔</tg-emoji> <b>User ID:</b> <code>{uid}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<tg-emoji emoji-id=\"6068995531793765349\">🙂</tg-emoji> <b>Username:</b> @{user_uname}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<tg-emoji emoji-id=\"6222156848707935750\">💳</tg-emoji> <b>Method:</b> {method}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<tg-emoji emoji-id=\"6190336264940559752\">💵</tg-emoji> <b>Amount:</b> ৳{amount:g}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<tg-emoji emoji-id=\"6221855350593691363\">🥷</tg-emoji> <b>TrxID:</b> <code>{trx_id}</code>"
        )
        
        with db() as c:
            cur = c.execute("""INSERT INTO deposits(user_id,method,amount,trx,status,created_at)
                VALUES(?,?,?,?, 'pending', ?)""",
                (uid, method, amount, trx_id, datetime.now().isoformat(timespec="seconds")))
            dep_id = cur.lastrowid

        context.user_data.pop("state", None)
        context.user_data.pop("deposit_method", None)
        context.user_data.pop("deposit_amount", None)
        
        await msg.reply_text(f"{e('ok')} ডিপোজিট রিকোয়েস্ট এডমিনদের কাছে পাঠানো হয়েছে।",
                             reply_markup=main_keyboard(uid))
        try:
            await context.bot.send_message(
                OWNER_ID,
                admin_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Approve", callback_data=f"deposit:accept:{dep_id}", style="success"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"deposit:reject:{dep_id}", style="danger")
                ]])
            )
        except Exception as e_log:
            log.error("Could not notify owner: %s", e_log)
        return

    # Owner-only admin text states
    if uid != OWNER_ID:
        context.user_data.pop("state", None)
        await msg.reply_text("Not authorized.")
        return

    if state == "admin_add_product_name":
        name = text.strip()
        if not name:
            await msg.reply_text("Product name cannot be empty. Send the product name:")
            return
        with db() as c:
            c.execute("INSERT INTO products(name,price) VALUES(?,?)", (name, 0))
        context.user_data.pop("state", None)
        await msg.reply_text(
            f"{e('ok')} Product added: {name}\nNow use “Add category + Excel stock” to add categories and set each category's price.",
            reply_markup=admin_keyboard()
        )
        return

    if state == "admin_add_category_name":
        context.user_data["new_category_name"] = text
        context.user_data["state"] = "admin_add_category_price"
        await msg.reply_text("Send the price for this category per item in BDT (e.g. 15):")
        return

    if state == "admin_add_category_price":
        try:
            category_price = float(text)
            if category_price < 0 or category_price > 1000000:
                raise ValueError
        except ValueError:
            await msg.reply_text("Enter a valid category price, e.g. 15 or 25.50.")
            return
        context.user_data["new_category_price"] = category_price
        context.user_data["state"] = "admin_upload_excel"
        await msg.reply_text(
            "Now upload the Excel (.xlsx) file as a document.\n"
            "Each stock item must be in column A, one item per row. "
            "A first-row header such as 'item' or 'stock' will be skipped."
        )
        return

    if state == "admin_set_category_price":
        try:
            price = float(text)
            if price < 0 or price > 1000000: raise ValueError
        except ValueError:
            await msg.reply_text("Enter a valid category price."); return
        cat_id = context.user_data["price_category_id"]
        with db() as c:
            c.execute("UPDATE categories SET price=? WHERE id=?", (price, cat_id))
        context.user_data.pop("state", None); context.user_data.pop("price_category_id", None)
        await msg.reply_text("Category price updated.", reply_markup=admin_keyboard())
        return

    if state == "admin_set_pay_number":
        if len(text) < 5 or len(text) > 30:
            await msg.reply_text("Please enter a valid payment number."); return
        method = context.user_data["payment_method_to_change"]
        set_setting("pay_" + method.lower(), text)
        context.user_data.pop("state", None); context.user_data.pop("payment_method_to_change", None)
        await msg.reply_text(f"{method} number updated to {text}.", reply_markup=admin_keyboard())
        return

    if state == "admin_force_channel":
        if not text.startswith("@") and not text.startswith("-100"):
            await msg.reply_text("Send @channelusername or a numeric channel ID."); return
        context.user_data["force_channel_id"] = text
        context.user_data["state"] = "admin_force_url"
        await msg.reply_text("Send the public channel URL (https://t.me/...) or '-' for none:")
        return

    if state == "admin_force_url":
        url = "" if text == "-" else text
        if url and not url.startswith("https://t.me/"):
            await msg.reply_text("URL must start with https://t.me/ or send '-'."); return
        context.user_data["force_channel_url_tmp"] = url
        context.user_data["state"] = "admin_force_name"
        await msg.reply_text("Send a display name for the channel:")
        return

    if state == "admin_force_name":
        channel = context.user_data["force_channel_id"]
        url = context.user_data["force_channel_url_tmp"]
        try:
            await context.bot.get_chat(channel)
        except Exception:
            await msg.reply_text("I cannot access that channel. Make the bot an admin and try again.")
            return
        set_setting("force_channel", channel)
        set_setting("force_channel_url", url)
        set_setting("force_channel_name", text[:80])
        for k in ("state", "force_channel_id", "force_channel_url_tmp"):
            context.user_data.pop(k, None)
        await msg.reply_text("Force-join channel saved.", reply_markup=admin_keyboard())
        return

    if state == "admin_balance_user":
        try: target = int(text)
        except ValueError:
            await msg.reply_text("Send a numeric Telegram ID."); return
        context.user_data["balance_target"] = target
        context.user_data["state"] = "admin_balance_amount"
        await msg.reply_text("Send amount: positive to add, negative to subtract (e.g. 50 or -20):")
        return

    if state == "admin_balance_amount":
        try: amount = float(text)
        except ValueError:
            await msg.reply_text("Enter a number, e.g. 50 or -20."); return
        target = context.user_data["balance_target"]
        ensure_user(target)
        with db() as c:
            current = c.execute("SELECT balance FROM users WHERE user_id=?", (target,)).fetchone()["balance"]
            if current + amount < 0:
                await msg.reply_text("Cannot make the balance negative."); return
            c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, target))
        context.user_data.pop("state", None); context.user_data.pop("balance_target", None)
        await msg.reply_text(f"Updated user {target} balance by {amount:+.2f} BDT.",
                             reply_markup=admin_keyboard())
        try:
            await context.bot.send_message(target, f"Your balance was adjusted by {amount:+.2f} BDT.")
        except Exception: pass
        return

    await msg.reply_text("Unknown step. Send /cancel to cancel.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != OWNER_ID:
        await update.effective_message.reply_text("Only the owner can upload stock.")
        return
    if context.user_data.get("state") != "admin_upload_excel":
        await update.effective_message.reply_text("To upload stock, use Admin Panel → Add category first.")
        return
    doc = update.effective_message.document
    if not doc.file_name.lower().endswith(".xlsx"):
        await update.effective_message.reply_text("Please upload an .xlsx Excel file.")
        return
    try:
        tg_file = await context.bot.get_file(doc.file_id)
        raw = BytesIO()
        await tg_file.download_to_memory(out=raw)
        raw.seek(0)
        wb = load_workbook(raw, read_only=True, data_only=True)
        ws = wb.active
        rows = []
        for row in ws.iter_rows(values_only=True):
            values = [("" if v is None else str(v).strip()) for v in row]
            while values and values[-1] == "":
                values.pop()
            if not values or not any(values):
                continue
            rows.append(values)
        wb.close()
        if not rows:
            await update.effective_message.reply_text("No stock items found in the Excel file.")
            return

        header_words = {"item", "stock", "product", "value", "content", "option a", "option b",
                        "option c", "option d", "option e", "option f", "option g", "option h"}
        first = [v.strip().lower() for v in rows[0]]
        has_header = any(v in header_words or v.startswith("option ") for v in first if v)
        if has_header:
            stock_headers = rows.pop(0)
        else:
            stock_headers = [f"Option {chr(65+i)}" for i in range(max(len(r) for r in rows))]
        if not rows:
            await update.effective_message.reply_text("The Excel file contains headers but no stock rows.")
            return
        product_id = context.user_data.get("category_product_id")
        cat_name = context.user_data.get("new_category_name")
        cat_price = float(context.user_data.get("new_category_price", 0))
        with db() as c:
            cur = c.execute("INSERT INTO categories(product_id,name,price,stock_headers) VALUES(?,?,?,?)",
                            (product_id, cat_name, cat_price, json.dumps(stock_headers, ensure_ascii=False)))
            cat_id = cur.lastrowid
            c.executemany("INSERT INTO stock(category_id,item) VALUES(?,?)",
                          [(cat_id, json.dumps(row, ensure_ascii=False)) for row in rows])
        for k in ("state", "category_product_id", "new_category_name", "new_category_price"):
            context.user_data.pop(k, None)
        await update.effective_message.reply_text(
            f"Category added: {cat_name}\nPrice: {cat_price:.2f} BDT per item\n"
            f"Stock imported: {len(rows)} items.",
            reply_markup=admin_keyboard()
        )
    except sqlite3.IntegrityError:
        await update.effective_message.reply_text("That category already exists for this product.")
    except Exception as e_excel:
        log.exception("Excel import failed")
        await update.effective_message.reply_text(f"Could not import the Excel file: {e_excel}")

async def admin_command(update, context):
    if not is_owner(update):
        await update.effective_message.reply_text("Not authorized.")
        return
    await update.effective_message.reply_text("Owner Admin Panel:", reply_markup=admin_keyboard())

async def cancel(update, context):
    context.user_data.pop("state", None)
    await update.effective_message.reply_text("Cancelled.", reply_markup=main_keyboard(update.effective_user.id))

async def error_handler(update, context):
    log.error("Unhandled exception", exc_info=context.error)

def main():
    if BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        raise SystemExit("Set BOT_TOKEN in bot.py before running.")
    if OWNER_ID == 123456789:
        raise SystemExit("Set OWNER_ID to your numeric Telegram user ID before running.")
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    print("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

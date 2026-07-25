#!/usr/bin/env python3
import os
import re
import sys
import time
import socket
import sqlite3
import logging
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.error import NetworkError
from telegram.request import HTTPXRequest

logging.basicConfig(level=logging.INFO)

# ===== DNS AUTO‑FIX =====
def ensure_dns():
    nameservers = ["1.1.1.1", "8.8.8.8", "9.9.9.9", "1.0.0.1"]
    test_host = "api.telegram.org"
    resolv_conf = "/etc/resolv.conf"
    try:
        with open(resolv_conf, 'r') as f:
            original = f.read()
    except:
        original = ""
    for ns in nameservers:
        try:
            with open(resolv_conf, 'w') as f:
                f.write(f"nameserver {ns}\n")
            socket.gethostbyname(test_host)
            logging.info(f"✅ DNS working with {ns}")
            return True
        except Exception as e:
            logging.warning(f"❌ DNS failed with {ns}: {e}")
            time.sleep(1)
    if original:
        with open(resolv_conf, 'w') as f:
            f.write(original)
    logging.error("❌ All DNS servers failed. Bot may not connect.")
    return False

# ===== CONFIGURATION =====
TOKEN = "8909209448:AAF17orXMaYuFX5aEic9uixBbGE3lhvMUl4"
ADMIN_ID = 5790547716
DB_FILE = "user_usage.db"
MAX_FREE_USES = 3
PRO_TIER_PRICE = 10000

# ===== DATABASE =====
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS user_usage (
        user_id INTEGER PRIMARY KEY,
        uses INTEGER DEFAULT 0,
        last_use TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_pro BOOLEAN DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS config (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    c.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('offer_count', '0')")
    conn.commit()
    conn.close()

def get_user_uses(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT uses, is_pro FROM user_usage WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    return result if result else (0, 0)

def increment_user_use(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''INSERT INTO user_usage (user_id, uses, last_use)
                 VALUES (?, 1, CURRENT_TIMESTAMP)
                 ON CONFLICT(user_id) DO UPDATE SET
                 uses = uses + 1,
                 last_use = CURRENT_TIMESTAMP''', (user_id,))
    conn.commit()
    conn.close()

def set_pro_status(user_id, is_pro):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('UPDATE user_usage SET is_pro = ? WHERE user_id = ?', (is_pro, user_id))
    conn.commit()
    conn.close()

# ===== OFFER COUNTER =====
def get_offer_count():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT value FROM config WHERE key = "offer_count"')
    result = c.fetchone()
    conn.close()
    return int(result[0]) if result else 0

def increment_offer_count():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('UPDATE config SET value = value + 1 WHERE key = "offer_count"')
    conn.commit()
    conn.close()

# ===== RETRY HELPER =====
async def download_with_retry(file, file_path, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await file.download_to_drive(file_path, read_timeout=180)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)

# ===== SERVICE CONFIGURATION =====
SERVICE_CONFIG = {
    'whatsapp': {
        'pattern': r'([A-Za-z\s]+):\s*(\+?\d{10,15})',
        'headers': ["Name", "Phone Number"],
        'prefix': 'whatsapp_numbers',
        'help': 'Extract names and phone numbers from WhatsApp chat exports.'
    },
    'email': {
        'pattern': r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
        'headers': ["Email"],
        'prefix': 'extracted_emails',
        'help': 'Extract all email addresses from text.'
    },
    'social': {
        'pattern': r'(?:@|instagram\.com/|twitter\.com/|linkedin\.com/in/|facebook\.com/|tiktok\.com/@|youtube\.com/@)([a-zA-Z0-9_.-]+)',
        'headers': ["Social Handle"],
        'prefix': 'social_handles',
        'help': 'Extract social media handles.'
    },
    'nin': {
        'pattern': r'\b\d{11}\b',
        'headers': ["NIN"],
        'prefix': 'nin_numbers',
        'help': 'Extract 11-digit NIN numbers.'
    },
    'bvn': {
        'pattern': r'\b\d{11}\b',
        'headers': ["BVN"],
        'prefix': 'bvn_numbers',
        'help': 'Extract 11-digit BVN numbers.'
    },
    'urls': {
        'pattern': r'https?://[^\s]+',
        'headers': ["URL"],
        'prefix': 'extracted_urls',
        'help': 'Extract all URLs from text.'
    }
}

# ===== AI SCORING (placeholder) =====
def ai_score_contacts(numbers, chat_content=""):
    scores = {}
    for num in numbers:
        if num.startswith('080') or num.startswith('090'):
            scores[num] = {'score': 'Active', 'confidence': 0.80}
        elif num.startswith('070'):
            scores[num] = {'score': 'Inactive', 'confidence': 0.60}
        else:
            scores[num] = {'score': 'Unknown', 'confidence': 0.50}
    return scores

# ===== FILE HANDLER =====
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    uses, is_pro = get_user_uses(user_id)

    if user_id != ADMIN_ID and not is_pro:
        if uses >= MAX_FREE_USES:
            keyboard = [[InlineKeyboardButton("💳 Upgrade to Pro", callback_data="pay_now")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "⛔ You've used all free tries.\n"
                f"💳 Upgrade to Pro for ₦{PRO_TIER_PRICE}/month.\n"
                "🔗 Click the button below to pay.",
                reply_markup=reply_markup
            )
            return

    document = update.message.document
    if not document or not document.file_name.endswith('.txt'):
        await update.message.reply_text("❌ Please send a .txt file.")
        return

    service = context.user_data.get('service', 'whatsapp')
    config = SERVICE_CONFIG.get(service)
    if not config:
        service = 'whatsapp'
        config = SERVICE_CONFIG['whatsapp']

    pattern = config['pattern']
    headers = config['headers']
    prefix = config['prefix']

    try:
        file = await context.bot.get_file(document.file_id)
        file_path = f"/tmp/{document.file_name}"
        await download_with_retry(file, file_path)

        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        if service == 'whatsapp':
            matches = re.findall(pattern, content)
            data = []
            for name, num in matches:
                clean_num = re.sub(r'[\s\-\(\)]', '', num)
                if len(clean_num) >= 10:
                    data.append((name.strip(), clean_num))
            seen = set()
            unique_data = []
            for name, num in data:
                if num not in seen:
                    seen.add(num)
                    unique_data.append((name, num))
        else:
            raw_matches = re.findall(pattern, content)
            if service in ('nin', 'bvn'):
                unique_data = list(set(raw_matches))
            else:
                unique_data = list(set([m.strip() for m in raw_matches]))

        if not unique_data:
            await update.message.reply_text("❌ No matches found for the selected service.")
            os.remove(file_path)
            return

        import csv
        csv_path = file_path.replace('.txt', '.csv')
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            if service == 'whatsapp':
                for name, num in unique_data:
                    writer.writerow([name, num])
            else:
                for item in unique_data:
                    writer.writerow([item])

        with open(csv_path, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            )

        if user_id != ADMIN_ID and not is_pro:
            increment_user_use(user_id)
            remaining = MAX_FREE_USES - (get_user_uses(user_id)[0])
            await update.message.reply_text(f"✅ Done! {remaining} free uses left.")
        else:
            await update.message.reply_text("✅ Done! (Unlimited access)")

        os.remove(file_path)
        os.remove(csv_path)

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        logging.error(f"File processing error: {e}")

# ===== COMMANDS =====
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📞 WhatsApp Numbers", callback_data="service_whatsapp")],
        [InlineKeyboardButton("📧 Emails", callback_data="service_email")],
        [InlineKeyboardButton("📱 Social Handles", callback_data="service_social")],
        [InlineKeyboardButton("🆔 NIN", callback_data="service_nin")],
        [InlineKeyboardButton("🏦 BVN", callback_data="service_bvn")],
        [InlineKeyboardButton("🔗 URLs", callback_data="service_urls")],
        [InlineKeyboardButton("💳 Upgrade to Pro", callback_data="pay_now")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🚀 **WhatsApp Helper Bot**\n\n"
        "Select a service below, then send a `.txt` file to extract data.\n\n"
        "💡 Free trial: 3 uses total (across all services).\n"
        "⭐ Pro: Unlimited extractions + AI scoring.\n\n"
        "📋 Type `/commands` to see all available commands.",
        reply_markup=reply_markup
    )

async def commands_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    commands_table = (
        "📋 **Available Commands**\n\n"
        "| Command | Description |\n"
        "|---------|-------------|\n"
        "| /start  | Show main menu and select a service |\n"
        "| /whatsapp | Extract WhatsApp numbers (names + numbers) |\n"
        "| /email  | Extract email addresses |\n"
        "| /social | Extract social media handles |\n"
        "| /nin    | Extract 11‑digit NIN numbers |\n"
        "| /bvn    | Extract 11‑digit BVN numbers |\n"
        "| /urls   | Extract URLs from text |\n"
        "| /help   | Show help information |\n"
        "| /guide  | How to export WhatsApp chat |\n"
        "| /roadmap | Project roadmap |\n"
        "| /community | Join our community group |\n"
        "| /pay    | Upgrade to Pro (₦10,000/month) |\n"
        "| /health | Bot health check (admin only) |\n"
        "| /offer_status | Limited offer status (admin only) |\n"
    )
    await update.message.reply_text(commands_table, parse_mode="Markdown")

async def service_command(update: Update, context: ContextTypes.DEFAULT_TYPE, service_name=None):
    if service_name and service_name in SERVICE_CONFIG:
        context.user_data['service'] = service_name
        await update.message.reply_text(
            f"✅ Service selected: **{service_name.upper()}**.\n"
            f"📄 Send a `.txt` file now.\n\n"
            f"ℹ️ {SERVICE_CONFIG[service_name]['help']}"
        )
    else:
        await update.message.reply_text("❌ Unknown service. Use /start to choose.")

async def whatsapp_command(update, context): await service_command(update, context, 'whatsapp')
async def email_command(update, context): await service_command(update, context, 'email')
async def social_command(update, context): await service_command(update, context, 'social')
async def nin_command(update, context): await service_command(update, context, 'nin')
async def bvn_command(update, context): await service_command(update, context, 'bvn')
async def urls_command(update, context): await service_command(update, context, 'urls')

async def service_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    service_map = {
        "service_whatsapp": "whatsapp",
        "service_email": "email",
        "service_social": "social",
        "service_nin": "nin",
        "service_bvn": "bvn",
        "service_urls": "urls",
    }
    service = service_map.get(query.data)
    if service:
        context.user_data['service'] = service
        await query.edit_message_text(
            f"✅ Service selected: **{service.upper()}**.\n"
            f"📄 Send a `.txt` file now.\n\n"
            f"ℹ️ {SERVICE_CONFIG[service]['help']}"
        )
    else:
        await query.edit_message_text("❌ Unknown service. Please use /start.")

async def roadmap_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🗺️ **KOSFintech Roadmap**\n\n"
        "✅ Phase 1 – Launch\n"
        "🚀 Phase 2 – Premium\n"
        "🌐 Phase 3 – Scale"
    )

async def community_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💬 **Join the Community**\n\n"
        "🤖 @WhatsappHelperBot\n"
        "👥 https://t.me/+vLcmNuOi3OZjYmFk\n"
        "📧 support@yourbot.com"
    )

async def guide_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 **How to Export WhatsApp Chat**\n\n"
        "1. Open WhatsApp group → 3 dots → Export Chat\n"
        "2. Choose Without Media\n"
        "3. Save .txt and send here"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 **How to use this bot:**\n"
        "1. Use /start to select a service.\n"
        "2. Export the relevant data as .txt and send it.\n"
        "3. Receive a CSV with extracted information.\n\n"
        "🔒 Free: 3 uses total\n"
        "⭐ Pro: Unlimited uses + premium features\n"
        "💳 Payment: /pay"
    )

async def pay_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payment_link = f"https://selar.com/427x919914?user_id={user_id}"
    keyboard = [[InlineKeyboardButton("💳 Pay Now", url=payment_link)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"⭐ **Upgrade to Pro – ₦{PRO_TIER_PRICE}/month**\n\n"
        "✅ Unlimited extractions for all services\n"
        "✅ AI Contact Scoring\n"
        "✅ Priority support\n\n"
        "🔗 Click below to pay.",
        reply_markup=reply_markup
    )

async def pay_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    payment_link = f"https://selar.com/427x919914?user_id={user_id}"
    keyboard = [[InlineKeyboardButton("💳 Pay Now", url=payment_link)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"💳 **Upgrade to Pro – ₦{PRO_TIER_PRICE}/month**\n\n"
        "✅ Unlimited extractions for all services\n"
        "✅ AI Contact Scoring\n"
        "✅ Priority support\n\n"
        "🔗 Click the button below to complete your payment.",
        reply_markup=reply_markup
    )

async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM user_usage')
        count = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM user_usage WHERE is_pro = 1')
        pro_count = c.fetchone()[0]
        conn.close()
        db_status = "✅ Database OK"
    except Exception as e:
        db_status = f"❌ Database ERROR: {e}"
        pro_count = 0
    try:
        result = os.popen('screen -list | grep "\\.bot"').read()
        screen_status = "✅ Bot screen active" if result else "⚠️ Bot screen NOT active"
    except:
        screen_status = "❌ Screen check failed"
    await update.message.reply_text(f"""
📊 Health Dashboard
━━━━━━━━━━━━━━━━━━━
{db_status}
{screen_status}
📱 Total users: {count}
⭐ Pro users: {pro_count}
🕐 Last check: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """)

async def offer_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Unauthorized.")
        return
    count = get_offer_count()
    remaining = max(0, 50 - count)
    await update.message.reply_text(f"📊 **Offer Counter**\nUsed: {count}\nRemaining: {remaining}")

# ===== ERROR HANDLER =====
async def error_handler(update, context):
    if isinstance(context.error, NetworkError):
        logging.warning(f"Network error: {context.error}. Continuing...")
    else:
        logging.error(f"Unhandled error: {context.error}")

# ===== MAIN =====
def main():
    ensure_dns()
    init_db()

    request = HTTPXRequest(
        read_timeout=300,
        write_timeout=300,
        connect_timeout=60,
        pool_timeout=300
    )

    app = Application.builder().token(TOKEN).request(request).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("commands", commands_command))
    app.add_handler(CommandHandler("whatsapp", whatsapp_command))
    app.add_handler(CommandHandler("email", email_command))
    app.add_handler(CommandHandler("social", social_command))
    app.add_handler(CommandHandler("nin", nin_command))
    app.add_handler(CommandHandler("bvn", bvn_command))
    app.add_handler(CommandHandler("urls", urls_command))
    app.add_handler(CommandHandler("roadmap", roadmap_command))
    app.add_handler(CommandHandler("community", community_command))
    app.add_handler(CommandHandler("guide", guide_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("pay", pay_command))
    app.add_handler(CommandHandler("health", health_command))
    app.add_handler(CommandHandler("offer_status", offer_status))

    app.add_handler(CallbackQueryHandler(service_callback, pattern="service_"))
    app.add_handler(CallbackQueryHandler(pay_callback, pattern="pay_now"))

    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_error_handler(error_handler)

    print("🤖 WhatsApp Helper Bot (Multi‑Service Edition) started...")
    app.run_polling(timeout=20, drop_pending_updates=True)
app.add_handler(CommandHandler("commands", commands_command))
if __name__ == "__main__":
    main()

# ===== COMMANDS TABLE =====
async def commands_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    commands_table = (
        "📋 **Available Commands**\n\n"
        "| Command | Description |\n"
        "|---------|-------------|\n"
        "| /start  | Show main menu and select a service |\n"
        "| /whatsapp | Extract WhatsApp numbers (names + numbers) |\n"
        "| /email  | Extract email addresses |\n"
        "| /social | Extract social media handles |\n"
        "| /nin    | Extract 11‑digit NIN numbers |\n"
        "| /bvn    | Extract 11‑digit BVN numbers |\n"
        "| /urls   | Extract URLs from text |\n"
        "| /help   | Show help information |\n"
        "| /guide  | How to export WhatsApp chat |\n"
        "| /roadmap | Project roadmap |\n"
        "| /community | Join our community group |\n"
        "| /pay    | Upgrade to Pro (₦10,000/month) |\n"
        "| /health | Bot health check (admin only) |\n"
        "| /offer_status | Limited offer status (admin only) |\n"
    )
    await update.message.reply_text(commands_table, parse_mode="Markdown")

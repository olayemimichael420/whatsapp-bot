#!/usr/bin/env python3
import os
import re
import sqlite3
import logging
import asyncio
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)

# ===== CONFIGURATION =====
TOKEN = "8954828190:AAEMpcOifcCq2qg1xttEg0HmO7rzq3Snpuk"
ADMIN_ID = 5790547716
DB_FILE = "user_usage.db"
MAX_FREE_USES = 3

# ===== DATABASE =====
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS user_usage (
        user_id INTEGER PRIMARY KEY,
        uses INTEGER DEFAULT 0,
        last_use TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()

def get_user_uses(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT uses FROM user_usage WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

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

async def download_with_retry(file, file_path, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await file.download_to_drive(file_path, read_timeout=120)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id == ADMIN_ID:
        remaining = "♾️ Unlimited"
    else:
        uses = get_user_uses(user_id)
        remaining = MAX_FREE_USES - uses
    await update.message.reply_text(
        f"👋 Welcome! Send me a WhatsApp chat .txt file.\n\n"
        f"📊 Free uses remaining: {remaining}\n"
        f"🔒 After {MAX_FREE_USES} uses, payment required."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 **How to use this bot:**\n"
        "1. Export a WhatsApp chat as .txt\n"
        "2. Send the file to this bot\n"
        "3. Get back a CSV of extracted numbers\n\n"
        "🔒 Free: 3 uses\n"
        "💳 Payment: Coming soon"
    )

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id != ADMIN_ID:
        uses = get_user_uses(user_id)
        if uses >= MAX_FREE_USES:
            await update.message.reply_text(
                "⛔ You've used all free tries.\n"
                "💳 Payment link: Coming soon"
            )
            return

    document = update.message.document
    if not document or not document.file_name.endswith('.txt'):
        await update.message.reply_text("❌ Please send a .txt file.")
        return

    try:
        file = await context.bot.get_file(document.file_id)
        file_path = f"/tmp/{document.file_name}"
        await download_with_retry(file, file_path)

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        numbers = re.findall(r'\+?\d{10,15}', content.replace(' ', '').replace('-', ''))

        if not numbers:
            await update.message.reply_text("❌ No phone numbers found.")
            os.remove(file_path)
            return

        csv_path = file_path.replace('.txt', '.csv')
        with open(csv_path, 'w') as f:
            f.write("Phone Number\n")
            for num in set(numbers):
                f.write(f"{num}\n")

        with open(csv_path, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=f"{document.file_name.replace('.txt', '')}_numbers.csv"
            )

        if user_id != ADMIN_ID:
            increment_user_use(user_id)
            remaining = MAX_FREE_USES - (get_user_uses(user_id))
            await update.message.reply_text(f"✅ Done! {remaining} free uses left.")
        else:
            await update.message.reply_text("✅ Done! (Admin – unlimited)")

        os.remove(file_path)
        os.remove(csv_path)

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

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
        conn.close()
        db_status = "✅ Database OK"
    except Exception as e:
        db_status = f"❌ Database ERROR: {e}"

    try:
        result = os.popen('screen -list | grep "\.bot"').read()
        screen_status = "✅ Bot screen active" if result else "⚠️ Bot screen NOT active"
    except:
        screen_status = "❌ Screen check failed"

    await update.message.reply_text(f"""
📊 Health Dashboard
━━━━━━━━━━━━━━━━━━━
{db_status}
{screen_status}
📱 Total users: {count}
🕐 Last check: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """)

def main():
    init_db()

    app = Application.builder() \
        .token(TOKEN) \
        .read_timeout(120) \
        .write_timeout(120) \
        .connect_timeout(60) \
        .pool_timeout(120) \
        .build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("health", health_command))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))

    print("🤖 Webhook bot started...")
    # Run with webhook – you need to set the webhook URL externally
    # For ngrok, set it with: curl -F "url=https://xxxx.ngrok.io/webhook" ...
    app.run_webhook(
        listen="0.0.0.0",
        port=8080,
        url_path="webhook",
        webhook_url="https://YOUR_NGROK_URL.ngrok.io/webhook"  # <-- CHANGE THIS
    )

if __name__ == "__main__":
    main()

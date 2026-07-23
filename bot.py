#!/usr/bin/env python3
import os
import re
import sqlite3
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)

# ===== CONFIGURATION =====
TOKEN = "8909209448:AAF17orXMaYuFX5aEic9uixBbGE3lhvMUl4"
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

# ===== COMMANDS =====
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
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
        await file.download_to_drive(file_path)

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        numbers = re.findall(r'\+?\d{10,15}', content)

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

        increment_user_use(user_id)
        remaining = MAX_FREE_USES - (uses + 1)
        await update.message.reply_text(f"✅ Done! {remaining} free uses left.")

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
        .read_timeout(60) \
        .write_timeout(60) \
        .connect_timeout(30) \
        .build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("health", health_command))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))

    print("🤖 Bot started...")
    app.run_polling(timeout=60, drop_pending_updates=True)

if __name__ == "__main__":
    main()

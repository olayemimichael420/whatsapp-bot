import os
import sqlite3
from datetime import datetime

async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ADMIN_ID = 123456789  # Replace with your Telegram user ID

    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Unauthorized.")
        return

    # Database check
    try:
        conn = sqlite3.connect('user_usage.db')
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM user_usage')
        count = c.fetchone()[0]
        conn.close()
        db_status = "✅ Database OK"
    except Exception as e:
        db_status = f"❌ Database ERROR: {e}"

    # Screen session check
    try:
        result = os.popen('screen -list | grep "\.bot"').read()
        screen_status = "✅ Bot screen active" if result else "⚠️ Bot screen NOT active"
    except:
        screen_status = "❌ Screen check failed"

    await update.message.reply_text(f"""
📊 **Health Dashboard**
━━━━━━━━━━━━━━━━━━━
{db_status}
{screen_status}
📱 Total users: {count}
🕐 Last check: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """)

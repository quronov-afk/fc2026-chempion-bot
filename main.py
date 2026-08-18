import os
import sqlite3
import re
import html
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ==========================================
# 1. SERVER VA BAZA SOZLAMALARI
# ==========================================

# Render/Heroku uchun Dummy HTTP Server (Bot to'xtab qolmasligi uchun)
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bot is alive and running!")

def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    print(f"HTTP Server {port}-portda ishga tushdi...")
    server.serve_forever()

# Ma'lumotlar bazasini sozlash (Faqat matches va settings jadvallari)
conn = sqlite3.connect("pes_stats.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''
    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        p1 TEXT,
        p2 TEXT,
        p1_score INTEGER,
        p2_score INTEGER,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')
# Guruh chat_id sini saqlash uchun (avto-xabar yuborishga kerak)
cursor.execute('''
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
''')
conn.commit()

# ==========================================
# 2. STATISTIKANI HISOBLASH (ALGORITMLAR)
# ==========================================

def get_all_stats():
    cursor.execute("SELECT p1, p2, p1_score, p2_score FROM matches")
    matches = cursor.fetchall()
    stats = {}
    
    for p1, p2, s1, s2 in matches:
        for p in (p1, p2):
            if p not in stats:
                stats[p] = {'games': 0, 'w': 0, 'd': 0, 'l': 0, 'gf': 0, 'ga': 0, 'pts': 0}
        
        stats[p1]['games'] += 1
        stats[p2]['games'] += 1
        stats[p1]['gf'] += s1
        stats[p2]['gf'] += s2
        stats[p1]['ga'] += s2
        stats[p2]['ga'] += s1
        
        if s1 > s2:
            stats[p1]['w'] += 1
            stats[p1]['pts'] += 3
            stats[p2]['l'] += 1
        elif s1 < s2:
            stats[p2]['w'] += 1
            stats[p2]['pts'] += 3
            stats[p1]['l'] += 1
        else:
            stats[p1]['d'] += 1
            stats[p2]['d'] += 1
            stats[p1]['pts'] += 1
            stats[p2]['pts'] += 1
            
    return stats

# ==========================================
# 3. BUYRUQLAR VA FUNKSIYALAR
# ==========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "⚽ <b>PES/FC LIGASI BOTI ISHGA TUSHDI!</b>\n\n"
        "<b>Natija kiritish formati:</b>\n"
        "👉 <code>@username yutdim 4-1</code>\n"
        "👉 <code>@username yutqazdim 2-3</code>\n"
        "👉 <code>@username durang 1-1</code>\n\n"
        "<b>Buyruqlar:</b>\n"
        "📊 /jadval - Umumiy reyting va Koeffitsiyent\n"
        "📜 /tarix - Oxirgi 7 kunlik o'yinlar\n"
        "👤 <code>/stat @user</code> - Shaxsiy statistika\n"
        "⚔️ <code>/h2h @user1 @user2</code> - O'zaro tarix\n"
        "📺 <code>/del ID</code> - Xatoni o'chirish (Faqat Adminlar)"
    )
    await update.message.reply_text(text, parse_mode='HTML')

# Natijani qabul qilish
async def handle_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text:
        return

    # Guruh chat_id sini saqlab qo'yamiz (Avto-xabar uchun)
    chat_id = update.message.chat_id
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('group_chat_id', ?)", (str(chat_id),))
    conn.commit()

    # Regex: @username (yutdim|yutqazdim|durang) 4-1
    pattern = r'@(\w+)\s+(yutdim|yutqazdim|durang)\s+(\d+)\s*[-:]\s*(\d+)'
    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        opp_raw = f"@{match.group(1)}"
        action = match.group(2).lower()
        s1 = int(match.group(3))
        s2 = int(match.group(4))

        sender = update.message.from_user
        my_raw = f"@{sender.username or sender.first_name}"

        if my_raw.lower() == opp_raw.lower():
            await update.message.reply_text("O'zingiz bilan o'zingiz o'ynab jinni bo'ldingizmi? 🤦‍♂️")
            return

        # Yutdim/Yutqazdim mantiqini to'g'rilash (katta raqam kimga tegishli)
        if action == "yutdim":
            my_goals, opp_goals = max(s1, s2), min(s1, s2)
        elif action == "yutqazdim":
            my_goals, opp_goals = min(s1, s2), max(s1, s2)
        else:
            my_goals, opp_goals = s1, s2 # Durang

        # Bazaga yozish
        cursor.execute("INSERT INTO matches (p1, p2, p1_score, p2_score) VALUES (?, ?, ?, ?)",
                       (my_raw, opp_raw, my_goals, opp_goals))
        conn.commit()

        # HTML escape (xatolikni oldini olish)
        my_esc = html.escape(my_raw)
        opp_esc = html.escape(opp_raw)

        # Emotsional javob
        if my_goals > opp_goals:
            farq = my_goals - opp_goals
            if farq >= 3:
                msg = f"🔥 <b>Daxshat!</b> {my_esc} {opp_esc} ni yanchib tashladi ({my_goals}:{opp_goals})! Joystikni devorga otib yubormadingmi? 🎮💥"
            else:
                msg = f"✅ <b>G'alaba!</b> {my_esc} {opp_esc} ustidan ishonchli g'alabaga erishdi ({my_goals}:{opp_goals})."
        elif my_goals < opp_goals:
            msg = f"👏 <b>Mardona e'tirof!</b> {my_esc} mag'lubiyatni tan oldi. {opp_esc} g'alaba qozondi ({opp_goals}:{my_goals})!"
        else:
            msg = f"🤝 <b>Murosasiz jang!</b> {my_esc} va {opp_esc} durang o'ynadi ({my_goals}:{opp_goals})."

        await update.message.reply_text(msg, parse_mode='HTML')

# Jadvalni ko'rsatish
async def show_table(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = get_all_stats()
    if not stats:
        await update.message.reply_text("Hali maydonga hech kim tushmadi. Qani, kim boshlab beradi? ⚽️")
        return

    # 1. Umumiy ochkolar bo'yicha saralash
    sorted_pts = sorted(stats.items(), key=lambda x: (x[1]['pts'], x[1]['gf'] - x[1]['ga']), reverse=True)
    
    # 2. Koeffitsiyent bo'yicha saralash (Kamida 3 ta o'yin)
    valid_ppg = {k: v for k, v in stats.items() if v['games'] >= 3}
    sorted_ppg = sorted(valid_ppg.items(), key=lambda x: (x[1]['pts'] / x[1]['games']), reverse=True)

    text = "🏆 <b>FC DO'STLAR LIGASI (Umumiy Tarix)</b> 🏆\n\n"
    text += "📊 <b>1. UMUMIY OCHKOLAR (Faollik)</b>\n<pre>"
    
    for idx, (player, s) in enumerate(sorted_pts, 1):
        gd = s['gf'] - s['ga']
        gd_str = f"+{gd}" if gd > 0 else str(gd)
        p_esc = html.escape(player).ljust(12)[:12]
        pts = str(s['pts']).rjust(2)
        text += f"{idx}. {p_esc} | {pts} o | ⚽️ {gd_str}\n"
    text += "</pre>\n"

    if sorted_ppg:
        text += "📈 <b>2. KOEFFITSIYENT (Sifat - Min 3 o'yin)</b>\n<pre>"
        for idx, (player, s) in enumerate(sorted_ppg, 1):
            ppg = s['pts'] / s['games']
            p_esc = html.escape(player).ljust(12)[:12]
            text += f"{idx}. {p_esc} | {ppg:.2f} PPG | ({s['games']} o'yin)\n"
        text += "</pre>"

    await update.message.reply_text(text, parse_mode='HTML')

# Oxirgi 7 kunlik tarix
async def match_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    seven_days_ago = datetime.now() - timedelta(days=7)
    cursor.execute("SELECT id, p1, p2, p1_score, p2_score, date FROM matches WHERE date >= ? ORDER BY id DESC", (seven_days_ago,))
    rows = cursor.fetchall()

    if not rows:
        await update.message.reply_text("Oxirgi 1 haftada hech qanday o'yin bo'lmadi. 😴")
        return

    text = "📜 <b>OXIRGI 7 KUNLIK QONLI JANGLAR:</b>\n\n<pre>"
    for r in rows:
        p1_esc = html.escape(r[1])
        p2_esc = html.escape(r[2])
        text += f"[ID: {r[0]}] {p1_esc} {r[3]}:{r[4]} {p2_esc}\n"
    text += "</pre>"

    await update.message.reply_text(text, parse_mode='HTML')

# Xatoni o'chirish (Faqat Admin)
async def delete_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Iltimos, o'yin ID sini kiriting. Masalan: <code>/del 45</code>", parse_mode='HTML')
        return

    # Admin tekshiruvi
    if update.message.chat.type in ['group', 'supergroup']:
        user_status = await context.bot.get_chat_member(update.message.chat_id, update.message.from_user.id)
        if user_status.status not in ['administrator', 'creator']:
            await update.message.reply_text("❌ <b>Qo'lingni tort!</b> Natijalarni faqat guruh adminlari o'zgartirishi mumkin.", parse_mode='HTML')
            return

    match_id = context.args[0]
    cursor.execute("SELECT p1, p2, p1_score, p2_score FROM matches WHERE id = ?", (match_id,))
    row = cursor.fetchone()

    if not row:
        await update.message.reply_text("Bunday ID raqamli o'yin topilmadi.")
        return

    cursor.execute("DELETE FROM matches WHERE id = ?", (match_id,))
    conn.commit()

    msg = (
        f"📺 <b>VAR QARORI: Admin aralashdi!</b>\n"
        f"ID: {match_id} bo'lgan o'yin ({html.escape(row[0])} {row[2]}:{row[3]} {html.escape(row[1])}) bazadan o'chirib tashlandi. Reytinglar qayta hisoblandi!"
    )
    await update.message.reply_text(msg, parse_mode='HTML')

# Shaxsiy statistika
async def player_stat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Foydalanuvchini kiriting: <code>/stat @ali</code>", parse_mode='HTML')
        return
    
    player = context.args[0]
    stats = get_all_stats()
    
    # Katta-kichik harf farqini yo'qotish uchun qidiramiz
    player_key = next((k for k in stats.keys() if k.lower() == player.lower()), None)
    
    if not player_key:
        await update.message.reply_text(f"{html.escape(player)} hali maydonga tushmagan.")
        return

    s = stats[player_key]
    gd = s['gf'] - s['ga']
    ppg = s['pts'] / s['games']
    
    text = (
        f"👤 <b>FUTBOLCHI DOSYESI: {html.escape(player_key)}</b>\n\n"
        f"🏟 Jami o'yinlar: <b>{s['games']} ta</b>\n"
        f"✅ G'alaba: <b>{s['w']}</b> | 🤝 Durang: <b>{s['d']}</b> | ❌ Mag'lubiyat: <b>{s['l']}</b>\n\n"
        f"⚽️ To'plar nisbati: <b>{s['gf']} - {s['ga']}</b> (Farq: {gd})\n"
        f"📊 Koeffitsiyent: <b>{ppg:.2f}</b>"
    )
    await update.message.reply_text(text, parse_mode='HTML')

# O'zaro tarix (H2H)
async def h2h_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Ikkita o'yinchini kiriting: <code>/h2h @men @ali</code>", parse_mode='HTML')
        return

    p1, p2 = context.args[0], context.args[1]
    cursor.execute('''
        SELECT p1, p2, p1_score, p2_score FROM matches 
        WHERE (LOWER(p1) = LOWER(?) AND LOWER(p2) = LOWER(?)) 
           OR (LOWER(p1) = LOWER(?) AND LOWER(p2) = LOWER(?))
    ''', (p1, p2, p2, p1))
    
    games = cursor.fetchall()
    if not games:
        await update.message.reply_text(f"{html.escape(p1)} va {html.escape(p2)} o'rtasida hali o'yin bo'lmagan.")
        return

    p1_wins = p2_wins = draws = 0
    for g_p1, g_p2, s1, s2 in games:
        if g_p1.lower() == p1.lower():
            score1, score2 = s1, s2
        else:
            score1, score2 = s2, s1

        if score1 > score2: p1_wins += 1
        elif score2 > score1: p2_wins += 1
        else: draws += 1

    text = (
        f"⚔️ <b>EL-CLASICO: {html.escape(p1)} 🆚 {html.escape(p2)}</b>\n\n"
        f"📊 Jami to'qnashuvlar: <b>{len(games)} ta</b>\n"
        f"👑 {html.escape(p1)} g'alabasi: <b>{p1_wins} ta</b>\n"
        f"😭 {html.escape(p2)} g'alabasi: <b>{p2_wins} ta</b>\n"
        f"🤝 Durang: <b>{draws} ta</b>"
    )
    await update.message.reply_text(text, parse_mode='HTML')

# ==========================================
# 4. AVTOMATIK XABAR YUBORISH (HAR 3 KUNDA)
# ==========================================
async def auto_announce(context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("SELECT value FROM settings WHERE key='group_chat_id'")
    row = cursor.fetchone()
    if not row:
        return # Hali guruh ID si saqlanmagan
    
    chat_id = int(row[0])
    stats = get_all_stats()
    if not stats:
        return

    sorted_pts = sorted(stats.items(), key=lambda x: (x[1]['pts'], x[1]['gf'] - x[1]['ga']), reverse=True)
    
    text = (
        "🚨 <b>Uyg'oning, kiber-atletlar! 3 kunlik sarhisob vaqti keldi!</b> 🚨\n\n"
        "Kim formaga kirdi, kim pastga sho'ng'idi? Qani, reytinglarga qaraymiz...\n\n"
        "🏆 <b>TOP-3 (Ochkolar):</b>\n<pre>"
    )
    
    for idx, (player, s) in enumerate(sorted_pts[:3], 1):
        p_esc = html.escape(player).ljust(12)[:12]
        text += f"{idx}. {p_esc} | {s['pts']} o\n"
    
    text += "</pre>\n🎮 Joystiklarni qizdiring, bugun kim kimni yanchib tashlaydi? To'liq jadvalni ko'rish uchun /jadval ni bosing."
    
    try:
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode='HTML')
    except Exception as e:
        print(f"Avto-xabar yuborishda xatolik: {e}")

# ==========================================
# 5. ASOSIY ISHGA TUSHIRISH QISMI
# ==========================================
def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        print("BOT_TOKEN topilmadi!")
        return

    # HTTP serverni alohida oqimda (thread) ishga tushirish (Render uchun)
    threading.Thread(target=run_dummy_server, daemon=True).start()

    app = Application.builder().token(token).build()
    
    # Buyruqlar
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("jadval", show_table))
    app.add_handler(CommandHandler("tarix", match_history))
    app.add_handler(CommandHandler("stat", player_stat))
    app.add_handler(CommandHandler("h2h", h2h_stats))
    app.add_handler(CommandHandler("del", delete_match))
    
    # Matnli xabarlarni ushlash
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_match))

    # Avto-xabarni har 3 kunda (259200 soniya) ishga tushirish
    app.job_queue.run_repeating(auto_announce, interval=259200, first=10)

    print("Bot ishga tushdi...")
    app.run_polling()

if __name__ == "__main__":
    main()

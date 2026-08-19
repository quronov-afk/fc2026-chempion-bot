import os
import sqlite3
import re
import html
import threading
import random
import asyncio
from datetime import datetime, timedelta, time, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ==========================================
# 1. SERVER VA BAZA SOZLAMALARI
# ==========================================

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

db_path = "/var/data/pes_stats.db" if os.path.exists("/var/data") else "pes_stats.db"
conn = sqlite3.connect(db_path, check_same_thread=False)
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
cursor.execute('''
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
''')
conn.commit()

# ==========================================
# 2. RANDOM MEMLAR VA GIFLAR BAZASI
# ==========================================

# 1. HAFTA G'OLIBI UCHUN
WEEKLY_WINNER_MEMES = [
    {"text": "👑 <b>HAFTA QIROLI!</b>\nUshbu haftaning mutlaq qiroli - {player}!\n<i>({reason})</i>\nQolganlar, tiz cho'king!", "gif": "CgACAgQAAxkBAAOAaoWEcnZZgVgOsrVxd_PX4seubZoAAkEHAAKu7FVSPErBb2CcrM09BA"},
    {"text": "🏆 <b>DARS BERILDI!</b>\n{player} bu hafta hammangizga darsingizni berdi.\n<i>({reason})</i>\nJoystikni qanday ishlashni o'rganib olinglar!", "gif": "CgACAgQAAxkBAAOCaoWEqtoeWFu1xnKnsWzjP12DlX8AAiwDAAKW0RVTG3af1IcEHpk9BA"},
    {"text": "🥇 <b>CHEMPION!</b>\nHafta chempioni - {player}!\n<i>({reason})</i>\nBoshqalar esa faqat tomoshabin bo'lishdi.", "gif": "CgACAgQAAxkBAAOEaoWFKvYSr0Budf44-r-Jhcora_0AAkEDAAJblj1T4ui_iIOX0Us9BA"}
]

# 2. KUN G'OLIBI UCHUN
DAILY_WINNER_MEMES = [
    {"text": "🌟 <b>KUN YULDUZI!</b>\nBugunning mutlaq yulduzi - {player}!\n<i>({reason})</i>\nBugun uni to'xtatib bo'lmadi.", "gif": "CgACAgQAAxkBAAOGaoWFTw4iObMjVnmuAzwxqW-IzOcAAr0DAAJZsARRN2mFveUh-i49BA"},
    {"text": "🔥 <b>YONDIRDI!</b>\n{player} bugun maydonni yondirdi!\n<i>({reason})</i>\nQolganlar esa faqat changini yutdi.", "gif": "CgACAgQAAxkBAAOIaoWF4XQivBqH-hQaIRvsrFZeifkAAnYHAALa_JxRZmjf0mnyLTA9BA"},
    {"text": "😎 <b>DAM OLINGLAR!</b>\nBugun {player} ning kuni bo'ldi.\n<i>({reason})</i>\nRaqiblar, yaxshilab dam oling, ertaga ham yutqazasizlar.", "gif": "CgACAgQAAxkBAAOKaoWGdvrDSdfiKGLrI7PzUzw7GgQAAt8JAAI6Lo1T-A0fC6Cam9o9BA"}
]

# 3. KUN MAG'LUBI UCHUN
DAILY_LOSER_MEMES = [
    {"text": "🗑 <b>KUN O'LJASI!</b>\nBugunning eng omadsiz o'yinchisi - {player}. Yettim deganimda... Afsus((", "gif": "CgACAgIAAxkBAAN-aoWD8jQwSS1dMwr1_cXYVwHmsHcAAo6kAAL2CDBIyh6sGt4yOw49BA"},
    {"text": "😭 <b>YIG'LAMA!</b>\n{player} bugun hamma o'yinda kaltak yedi. Yig'lama, ertaga ham shunday bo'ladi!", "gif": "CgACAgIAAxkBAAOMaoWG9VMdJvHvsq_dmrPAWrAF5zcAAsJKAAJTXNhKfOXYbF63mSo9BA"},
    {"text": "🐢 <b>TOSHBAQA!</b>\nBugunning eng sekin va omadsiz toshbaqasi - {player}. Joystikni devorga otish vaqti keldi!", "gif": "CgACAgQAAxkBAAOOaoWHEvYRQ4XAwpN6X6uDiobngTsAAtgGAAIf89xR-7P8SkDt3Eo9BA"}
]

# ==========================================
# 3. STATISTIKANI HISOBLASH (ALGORITMLAR)
# ==========================================

def get_stats_by_period(days=None):
    if days:
        time_limit = datetime.now() - timedelta(days=days)
        cursor.execute("SELECT p1, p2, p1_score, p2_score FROM matches WHERE date >= ?", (time_limit,))
    else:
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
# 4. BUYRUQLAR VA FUNKSIYALAR
# ==========================================

async def get_gif_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private':
        file_id = update.effective_message.animation.file_id
        await update.effective_message.reply_text(f"Bu GIF ning ID raqami:\n\n<code>{file_id}</code>\n\n(Shu kodni ustiga bosib nusxalab oling)", parse_mode='HTML')

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
    await update.effective_message.reply_text(text, parse_mode='HTML')

async def handle_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.effective_message.text
    if not text:
        return

    chat_id = update.effective_chat.id
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('group_chat_id', ?)", (str(chat_id),))
    conn.commit()

    pattern = r'@(\w+)\s+(yutdim|yutqazdim|durang)\s+(\d+)\s*[-:]\s*(\d+)'
    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        opp_raw = f"@{match.group(1)}"
        action = match.group(2).lower()
        s1 = int(match.group(3))
        s2 = int(match.group(4))

        sender = update.effective_user
        my_raw = f"@{sender.username or sender.first_name}"

        if my_raw.lower() == opp_raw.lower():
            await update.effective_message.reply_text("O'zingiz bilan o'zingiz o'ynab jinni bo'ldingizmi? 🤦‍♂️")
            return

        if action == "yutdim":
            my_goals, opp_goals = max(s1, s2), min(s1, s2)
        elif action == "yutqazdim":
            my_goals, opp_goals = min(s1, s2), max(s1, s2)
        else:
            my_goals, opp_goals = s1, s2 

        cursor.execute("INSERT INTO matches (p1, p2, p1_score, p2_score) VALUES (?, ?, ?, ?)",
                       (my_raw, opp_raw, my_goals, opp_goals))
        conn.commit()

        my_esc = html.escape(my_raw)
        opp_esc = html.escape(opp_raw)

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

        await update.effective_message.reply_text(msg, parse_mode='HTML')

async def show_table(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = get_stats_by_period()
    if not stats:
        await update.effective_message.reply_text("Hali maydonga hech kim tushmadi. Qani, kim boshlab beradi? ⚽️")
        return

    sorted_pts = sorted(stats.items(), key=lambda x: (x[1]['pts'], x[1]['gf'] - x[1]['ga']), reverse=True)
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

    await update.effective_message.reply_text(text, parse_mode='HTML')

async def match_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    seven_days_ago = datetime.now() - timedelta(days=7)
    cursor.execute("SELECT id, p1, p2, p1_score, p2_score, date FROM matches WHERE date >= ? ORDER BY id DESC", (seven_days_ago,))
    rows = cursor.fetchall()

    if not rows:
        await update.effective_message.reply_text("Oxirgi 1 haftada hech qanday o'yin bo'lmadi. 😴")
        return

    text = "📜 <b>OXIRGI 7 KUNLIK QONLI JANGLAR:</b>\n\n<pre>"
    for r in rows:
        p1_esc = html.escape(r[1])
        p2_esc = html.escape(r[2])
        text += f"[ID: {r[0]}] {p1_esc} {r[3]}:{r[4]} {p2_esc}\n"
    text += "</pre>"

    await update.effective_message.reply_text(text, parse_mode='HTML')

async def delete_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text("Iltimos, o'yin ID sini kiriting. Masalan: <code>/del 45</code>", parse_mode='HTML')
        return

    if update.effective_chat.type in ['group', 'supergroup']:
        user_status = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        if user_status.status not in ['administrator', 'creator']:
            await update.effective_message.reply_text("❌ <b>Qo'lingni tort!</b> Natijalarni faqat guruh adminlari o'zgartirishi mumkin.", parse_mode='HTML')
            return

    match_id = context.args[0]
    cursor.execute("SELECT p1, p2, p1_score, p2_score FROM matches WHERE id = ?", (match_id,))
    row = cursor.fetchone()

    if not row:
        await update.effective_message.reply_text("Bunday ID raqamli o'yin topilmadi.")
        return

    cursor.execute("DELETE FROM matches WHERE id = ?", (match_id,))
    conn.commit()

    msg = (
        f"📺 <b>VAR QARORI: Admin aralashdi!</b>\n"
        f"ID: {match_id} bo'lgan o'yin ({html.escape(row[0])} {row[2]}:{row[3]} {html.escape(row[1])}) bazadan o'chirib tashlandi. Reytinglar qayta hisoblandi!"
    )
    await update.effective_message.reply_text(msg, parse_mode='HTML')

async def player_stat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text("Foydalanuvchini kiriting: <code>/stat @ali</code>", parse_mode='HTML')
        return
    
    player = context.args[0]
    stats = get_stats_by_period()
    
    player_key = next((k for k in stats.keys() if k.lower() == player.lower()), None)
    
    if not player_key:
        await update.effective_message.reply_text(f"{html.escape(player)} hali maydonga tushmagan.")
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
    await update.effective_message.reply_text(text, parse_mode='HTML')

async def h2h_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.effective_message.reply_text("Ikkita o'yinchini kiriting: <code>/h2h @men @ali</code>", parse_mode='HTML')
        return

    p1, p2 = context.args[0], context.args[1]
    cursor.execute('''
        SELECT p1, p2, p1_score, p2_score FROM matches 
        WHERE (LOWER(p1) = LOWER(?) AND LOWER(p2) = LOWER(?)) 
           OR (LOWER(p1) = LOWER(?) AND LOWER(p2) = LOWER(?))
    ''', (p1, p2, p2, p1))
    
    games = cursor.fetchall()
    if not games:
        await update.effective_message.reply_text(f"{html.escape(p1)} va {html.escape(p2)} o'rtasida hali o'yin bo'lmagan.")
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
    await update.effective_message.reply_text(text, parse_mode='HTML')

# ==========================================
# 5. AVTOMATIK XABARLAR (KUNLIK, HAFTALIK, 3 KUNLIK)
# ==========================================

async def send_meme(context, chat_id, meme_list, **kwargs):
    meme = random.choice(meme_list)
    text = meme["text"].format(**kwargs)
    gif_id = meme["gif"]
    
    try:
        if gif_id.startswith("GIF_KODI_"):
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode='HTML')
        else:
            await context.bot.send_animation(chat_id=chat_id, animation=gif_id, caption=text, parse_mode='HTML')
    except Exception as e:
        print(f"Meme yuborishda xato: {e}")

# Har 24 soatda (Kun g'olibi va mag'lubi)
async def daily_summary(context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("SELECT value FROM settings WHERE key='group_chat_id'")
    row = cursor.fetchone()
    if not row: return 
    chat_id = int(row[0])
    
    stats = get_stats_by_period(days=1)
    if not stats: return # Bugun o'yin bo'lmagan
    
    sorted_pts = sorted(stats.items(), key=lambda x: (x[1]['pts'], x[1]['gf'] - x[1]['ga']), reverse=True)
    winner = html.escape(sorted_pts[0][0])
    w_pts = sorted_pts[0][1]['pts']
    w_gd = sorted_pts[0][1]['gf'] - sorted_pts[0][1]['ga']
    
    loser = html.escape(sorted_pts[-1][0])
    
    # Izoh (Reason)
    if len(sorted_pts) > 1 and sorted_pts[0][1]['pts'] == sorted_pts[1][1]['pts']:
        reason = f"Ochkolar teng bo'lsa-da, to'plar nisbati yaxshiroq: {w_pts} ochko, ⚽️ {w_gd:+d}"
    else:
        reason = f"Eng ko'p ochko yig'gan holda: {w_pts} ochko"
    
    await send_meme(context, chat_id, DAILY_WINNER_MEMES, player=winner, reason=reason)
    
    if len(sorted_pts) > 1:
        await asyncio.sleep(60) # 1 DAQIQALIK INTERVAL
        await send_meme(context, chat_id, DAILY_LOSER_MEMES, player=loser)

# Har 7 kunda (Hafta g'olibi)
async def weekly_summary(context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("SELECT value FROM settings WHERE key='group_chat_id'")
    row = cursor.fetchone()
    if not row: return 
    chat_id = int(row[0])
    
    stats = get_stats_by_period(days=7)
    if not stats: return
    
    sorted_pts = sorted(stats.items(), key=lambda x: (x[1]['pts'], x[1]['gf'] - x[1]['ga']), reverse=True)
    winner = html.escape(sorted_pts[0][0])
    w_pts = sorted_pts[0][1]['pts']
    w_gd = sorted_pts[0][1]['gf'] - sorted_pts[0][1]['ga']
    
    if len(sorted_pts) > 1 and sorted_pts[0][1]['pts'] == sorted_pts[1][1]['pts']:
        reason = f"Ochkolar teng bo'lsa-da, to'plar nisbati yaxshiroq: {w_pts} ochko, ⚽️ {w_gd:+d}"
    else:
        reason = f"Eng ko'p ochko yig'gan holda: {w_pts} ochko"
    
    await send_meme(context, chat_id, WEEKLY_WINNER_MEMES, player=winner, reason=reason)

# Har 3 kunda (Favqulodda e'lon va jadvallar)
async def auto_announce(context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("SELECT value FROM settings WHERE key='group_chat_id'")
    row = cursor.fetchone()
    if not row: return 
    chat_id = int(row[0])
    
    stats = get_stats_by_period()
    if not stats or len(stats) < 2: return

    # 1. Ochkolar bo'yicha saralash
    sorted_pts = sorted(stats.items(), key=lambda x: (x[1]['pts'], x[1]['gf'] - x[1]['ga']), reverse=True)
    top_pts_player = html.escape(sorted_pts[0][0])
    top_pts = sorted_pts[0][1]['pts']
    top_wins = sorted_pts[0][1]['w']
    
    bottom_player = html.escape(sorted_pts[-1][0])
    bottom_pts = sorted_pts[-1][1]['pts']

    # 2. Koeffitsiyent bo'yicha saralash (Min 3 o'yin o'ynaganlar)
    valid_ppg = {k: v for k, v in stats.items() if v['games'] >= 3}
    if valid_ppg:
        sorted_ppg = sorted(valid_ppg.items(), key=lambda x: (x[1]['pts'] / x[1]['games']), reverse=True)
        top_ppg_player = html.escape(sorted_ppg[0][0])
        top_ppg = sorted_ppg[0][1]['pts'] / sorted_ppg[0][1]['games']
    else:
        top_ppg_player = None

    # ==========================================
    # GIF KODLARINI SHU YERGA JOYLAYSIZ:
    # ==========================================
    gif_kazo = "CgACAgIAAxkBAAO-aoXaujWOQPXd6AvAX3MWb-uAgUUAAqiuAAJtRTBIAAH6foMHrf0NPQQ"
    gif_qishloq = "CgACAgIAAxkBAAO8aoXamtCs_ekIJh7Dj7X1N7r0Z9UAAqeuAAJtRTBI4RGqc2Mp8Mk9BA"
    gif_otib_tashla = "CgACAgIAAxkBAAPAaoXa4BGj3cO2B5AwUDDJgOCSvOkAAqquAAJtRTBIcHwysyjc8y89BA"

    # Matnlar
    msg1 = f"👑 <b>\"Meni o'zingga tenglashtirma, kazo-kazolardanman men!\"</b>\n\n📊 {top_pts_player} {top_pts} ochko ({top_wins} ta g'alaba) bilan hammadan tepada, qolganlar, ta'zim qiling!"
    
    if top_ppg_player:
        msg2 = f"🚜 <b>\"Yo'ldan qoch, qishloqilar!\"</b>\n\n📈 {top_ppg_player} {top_ppg:.2f} koeffitsiyent bilan eng sifatli o'yin ko'rsatmoqda!"
    
    msg3 = f"🔫 <b>\"Otib tashlanglar buni!!!\"</b>\n\n📉 {bottom_player} atigi {bottom_pts} ochko bilan reyting tubida yotibdi... Otib tashlanglar, uni :)"

    # Xabarlarni guruhga yuborish
    try:
        # 1-xabar (Kazo-kazo)
        if gif_kazo.startswith("KAZO"): await context.bot.send_message(chat_id=chat_id, text=msg1, parse_mode='HTML')
        else: await context.bot.send_animation(chat_id=chat_id, animation=gif_kazo, caption=msg1, parse_mode='HTML')
        
        # 2-xabar (Qishloqilar)
        if top_ppg_player:
            await asyncio.sleep(60) # 1 DAQIQALIK INTERVAL
            if gif_qishloq.startswith("QISHLOQ"): await context.bot.send_message(chat_id=chat_id, text=msg2, parse_mode='HTML')
            else: await context.bot.send_animation(chat_id=chat_id, animation=gif_qishloq, caption=msg2, parse_mode='HTML')
        
        # 3-xabar (Otib tashlanglar)
        await asyncio.sleep(60) # 1 DAQIQALIK INTERVAL
        if gif_otib_tashla.startswith("OTIB"): await context.bot.send_message(chat_id=chat_id, text=msg3, parse_mode='HTML')
        else: await context.bot.send_animation(chat_id=chat_id, animation=gif_otib_tashla, caption=msg3, parse_mode='HTML')
        
    except Exception as e:
        print(f"3 kunlik xabar yuborishda xato: {e}")

# Har kuni 16:00 da (Jangga chorlov)
async def daily_provocation(context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("SELECT value FROM settings WHERE key='group_chat_id'")
    row = cursor.fetchone()
    if not row: return 
    chat_id = int(row[0])

    stats = get_stats_by_period()
    if not stats or len(stats) < 2:
        return # Agar o'yinchilar yetarli bo'lmasa, indamaydi

    sorted_pts = sorted(stats.items(), key=lambda x: (x[1]['pts'], x[1]['gf'] - x[1]['ga']), reverse=True)
    top1 = html.escape(sorted_pts[0][0])
    bottom = html.escape(sorted_pts[-1][0])
    
    # Matnni shakllantirish
    msg = f"{top1} bugun seni kuning emas, alvasti!\n"
    
    if len(sorted_pts) >= 3:
        top2 = html.escape(sorted_pts[1][0])
        msg += f"{top2} lallayma, {top1} ni yutishga duxing yetmaydimi?\n"
        
    msg += f"{bottom} odam bo'maysan, san. San odam bo'maysan!"

    # ==========================================
    # 5 TA GIF KODINI SHU YERGA JOYLAYSIZ:
    # ==========================================
    PROVOCATION_GIFS = [
        "CgACAgIAAxkBAAPSaoXtV4ObWISdS22M5bnctKMhMp8AAu8uAALJZdhLxChEqBW77G49BA",
        "CgACAgIAAxkBAAPQaoXtECWaUNM94OLb5JgofX5kBK4AAlpDAAIBqoFJnwedkRUYrPw9BA",
        "CgACAgIAAxkBAAPMaoXszpxA2B4nwpAlUF5vyFxHoSMAAuaNAAJVUjhKnmpsH2xmho09BA",
        "CgACAgQAAxkBAAPKaoXsdFqMNM4xLwlBtZk8U7EEc84AAtkLAAJE7UlQ0YObLgABdEplPQQ",
        "CgACAgIAAxkBAAPXaoXwI3rSOzFAE4qks7wYU6W5GP0AAvggAAKNo_hIrUSBpx_YY809BA"
    ]
    
    gif_chaqiruv = random.choice(PROVOCATION_GIFS)

    try:
        if gif_chaqiruv.startswith("GIF_KODI"):
            await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='HTML')
        else:
            await context.bot.send_animation(chat_id=chat_id, animation=gif_chaqiruv, caption=msg, parse_mode='HTML')
    except Exception as e:
        print(f"16:00 chaqiruv yuborishda xato: {e}")

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        print("BOT_TOKEN topilmadi!")
        return

    threading.Thread(target=run_dummy_server, daemon=True).start()

    app = Application.builder().token(token).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("jadval", show_table))
    app.add_handler(CommandHandler("tarix", match_history))
    app.add_handler(CommandHandler("stat", player_stat))
    app.add_handler(CommandHandler("h2h", h2h_stats))
    app.add_handler(CommandHandler("del", delete_match))
    
    # GIF ID aniqlash (Faqat lichkada ishlaydi)
    app.add_handler(MessageHandler(filters.ANIMATION, get_gif_id))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_match))

   # O'zbekiston vaqti (UTC+5)
    tz_uz = timezone(timedelta(hours=5))
    
    # Soatlar: 23:00 va 16:00 ni belgilash
    time_23 = time(hour=23, minute=0, tzinfo=tz_uz)
    time_16 = time(hour=16, minute=0, tzinfo=tz_uz)
    
    # 1. Kunlik sarhisob (Har kuni 23:00 da)
    app.job_queue.run_daily(daily_summary, time=time_23)
    
    # 2. Haftalik sarhisob (Yakshanba kuni 23:00 da) -> 6 = Yakshanba
    app.job_queue.run_daily(weekly_summary, time=time_23, days=(6,))

    # 3. Har kuni 16:00 da (Jangga chorlov)
    app.job_queue.run_daily(daily_provocation, time=time_16)
    
    # 4. 3 kunlik kutilmagan mem (Har 3 kunda 17:00 da)
    now = datetime.now(tz_uz)
    first_17 = now.replace(hour=17, minute=0, second=0, microsecond=0)
    if now > first_17:
        first_17 += timedelta(days=1)
        
    app.job_queue.run_repeating(auto_announce, interval=timedelta(days=3), first=first_17)

    print("Bot ishga tushdi...")
    app.run_polling()

if __name__ == "__main__":
    main()

import os
import sqlite3
import re
import html
import threading
import random
import asyncio
import io
import itertools
from datetime import datetime, timedelta, time, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont

# ==========================================
# 1. SERVER VA BAZA SOZLAMALARI
# ==========================================

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bot is alive and running!")

class ReusableTCPServer(HTTPServer):
    allow_reuse_address = True

def run_dummy_server():
    try:
        port = int(os.environ.get("PORT", 8080))
        server = ReusableTCPServer(('0.0.0.0', port), HealthCheckHandler)
        print(f"HTTP Server {port}-portda ishga tushdi...")
        server.serve_forever()
    except Exception as e:
        print(f"Web server xatosi: {e}")

db_path = "/var/data/pes_stats.db" if os.path.exists("/var/data") else "pes_stats.db"
conn = sqlite3.connect(db_path, check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, p1 TEXT, p2 TEXT, p1_score INTEGER, p2_score INTEGER, date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)''')
cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
cursor.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, user_id INTEGER)")
cursor.execute("CREATE TABLE IF NOT EXISTS groups (chat_id INTEGER PRIMARY KEY)")

cursor.execute('''CREATE TABLE IF NOT EXISTS cups (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, name TEXT, status TEXT
)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS cup_participants (
    cup_id INTEGER, username TEXT
)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS cup_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT, cup_id INTEGER, p1 TEXT, p2 TEXT, p1_score INTEGER, p2_score INTEGER, status TEXT, date_played TIMESTAMP
)''')

try:
    cursor.execute("ALTER TABLE matches ADD COLUMN chat_id INTEGER")
    cursor.execute("SELECT value FROM settings WHERE key='group_chat_id'")
    old_chat = cursor.fetchone()
    if old_chat:
        cursor.execute("UPDATE matches SET chat_id = ? WHERE chat_id IS NULL", (int(old_chat[0]),))
        cursor.execute("INSERT OR IGNORE INTO groups (chat_id) VALUES (?)", (int(old_chat[0]),))
except: pass
conn.commit()

# ==========================================
# 2. MEMLAR BAZASI
# ==========================================

GIF_WIN_1 = "CgACAgQAAxkBAAIBIGqInhqnXgL3lO_XQBY6ovgLxj-8AALrCQACXiTkUqOL8Djg85SsPQQ" 
GIF_WIN_2 = "CgACAgIAAxkBAAIBImqInxDQjVfHKiGY2q0gXH8okpY6AALeBgACyTthSrIe1TGtXuzbPQQ" 
GIF_WIN_3 = "CgACAgIAAxkBAAIBPmqIowbF2Nqs6JmyZcPFOs3PlvfQAAL5EAACPr1ISLAYW28QSZsaPQQ" 
GIF_LOSE_1 = "CgACAgIAAxkBAAIBHmqInWIBZpGjbGSchBUlGUPTJr-kAALYCgACfTIpSH4-y3c88xEPPQQ" 
GIF_LOSE_4 = "CgACAgIAAxkBAAIBNGqIoqg_h9A-9Q1n8o_MBoGsypBnAAKPFwACrupASIRE7lFwpooSPQQ" 
GIF_LOSE_8 = "CgACAgIAAxkBAAIBRmqIo2z9GjcGYOCWf8nA7c6nNfN_AAK3EwACrt9ISEQ7CsptOpq4PQQ" 

DAILY_WINNER_MEMES = [
    {"text": "👑 <b>Tajriba va mahorat!</b>\n{player} bugun ajoyib o'yin ko'rsatdi! <i>({reason})</i>", "gif": GIF_WIN_1},
    {"text": "🥇 <b>Haqiqiy chempioncha o'yin!</b>\n{player} bugun maydonda o'z so'zini aytdi! <i>({reason})</i>", "gif": GIF_WIN_2},
    {"text": "😎 <b>Ishonchli g'alaba!</b>\n{player} bugun raqiblarga hech qanday imkoniyat qoldirmadi. <i>({reason})</i>", "gif": GIF_WIN_3}
]
DAILY_LOSER_MEMES = [
    {"text": "🤝 <b>Asosiysi do'stlik!</b>\n{player}, bugun biroz omad yetishmadi. Keyingi o'yinlarda zafar yor bo'lsin!", "gif": GIF_LOSE_1},
    {"text": "📉 <b>Taslim bo'lmaymiz!</b>\n{player} uchun bugun qiyin kun bo'ldi, lekin g'alabalar hali oldinda.", "gif": GIF_LOSE_4},
    {"text": "🎮 <b>Mashg'ulotni ko'paytiramiz!</b>\n{player}, keyingi safar albatta o'xshaydi, omad!", "gif": GIF_LOSE_8}
]

# ==========================================
# 3. STATISTIKA VA GRAFIKLAR
# ==========================================

def get_stats_by_date_range(chat_id, start_dt, end_dt):
    start_utc = start_dt.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    end_utc = end_dt.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("SELECT p1, p2, p1_score, p2_score FROM matches WHERE chat_id = ? AND date >= ? AND date < ?", (chat_id, start_utc, end_utc))
    matches = cursor.fetchall()
    stats = {}
    for p1, p2, s1, s2 in matches:
        for p in (p1, p2):
            if p not in stats: stats[p] = {'games': 0, 'w': 0, 'd': 0, 'l': 0, 'gf': 0, 'ga': 0, 'pts': 0, 'h2h': {}}
        if p2 not in stats[p1]['h2h']: stats[p1]['h2h'][p2] = {'games': 0, 'pts': 0}
        if p1 not in stats[p2]['h2h']: stats[p2]['h2h'][p1] = {'games': 0, 'pts': 0}

        stats[p1]['games'] += 1; stats[p2]['games'] += 1
        stats[p1]['gf'] += s1; stats[p2]['gf'] += s2
        stats[p1]['ga'] += s2; stats[p2]['ga'] += s1
        stats[p1]['h2h'][p2]['games'] += 1; stats[p2]['h2h'][p1]['games'] += 1
        
        if s1 > s2: stats[p1]['w'] += 1; stats[p1]['pts'] += 3; stats[p2]['l'] += 1; stats[p1]['h2h'][p2]['pts'] += 3
        elif s1 < s2: stats[p2]['w'] += 1; stats[p2]['pts'] += 3; stats[p1]['l'] += 1; stats[p2]['h2h'][p1]['pts'] += 3
        else: stats[p1]['d'] += 1; stats[p2]['d'] += 1; stats[p1]['pts'] += 1; stats[p2]['pts'] += 1; stats[p1]['h2h'][p2]['pts'] += 1; stats[p2]['h2h'][p1]['pts'] += 1

    for p, data in stats.items():
        total_h2h_ppg = 0
        unique_opponents = len(data['h2h'])
        for opp, h2h_data in data['h2h'].items(): total_h2h_ppg += h2h_data['pts'] / h2h_data['games']
        data['true_ppg'] = total_h2h_ppg / unique_opponents if unique_opponents > 0 else 0.0
        data['unique_opponents'] = unique_opponents
    return stats

def get_stats_by_period(chat_id, days=None, today_only=False):
    tz_uz = timezone(timedelta(hours=5))
    now_uz = datetime.now(tz_uz)
    if today_only: start_dt = now_uz.replace(hour=0, minute=0, second=0, microsecond=0)
    elif days: start_dt = now_uz - timedelta(days=days)
    else: start_dt = now_uz - timedelta(days=3650)
    return get_stats_by_date_range(chat_id, start_dt, now_uz)

def create_comparison_chart(curr_stats, prev_stats, title_text):
    players, pts_list, colors, labels = [], [], [], []
    sorted_curr = sorted(curr_stats.items(), key=lambda x: x[1]['pts'], reverse=False)
    for p, data in sorted_curr:
        c_pts = data['pts']
        p_pts = prev_stats.get(p, {}).get('pts', 0)
        diff = c_pts - p_pts
        players.append(p)
        pts_list.append(c_pts)
        if diff > 0: colors.append('#4CAF50'); labels.append(f"{c_pts} (+{diff} 📈)")
        elif diff < 0: colors.append('#F44336'); labels.append(f"{c_pts} ({diff} 📉)")
        else: colors.append('#2196F3'); labels.append(f"{c_pts} (➖)")

    plt.figure(figsize=(8, max(len(players) * 0.6 + 2, 4)))
    bars = plt.barh(players, pts_list, color=colors, height=0.6)
    plt.title(title_text, fontsize=14, fontweight='bold', pad=15)
    plt.xlabel("To'plangan Ochkolar", fontsize=11)
    plt.gca().spines['top'].set_visible(False)
    plt.gca().spines['right'].set_visible(False)
    plt.grid(axis='x', linestyle='--', alpha=0.7)
    for bar, label in zip(bars, labels):
        plt.text(bar.get_width() + 0.2, bar.get_y() + bar.get_height()/2, label, va='center', ha='left', fontsize=11, fontweight='bold')
    plt.xlim(0, max(pts_list + [1]) * 1.25)
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    buf.seek(0)
    plt.close()
    return buf

async def generate_certificate(context, user_id, username, pts, wins, ppg, title="O Y   Q I R O L I", subtitle="FC Do'stlar Ligasi Chempioni"):
    try:
        img = Image.open("cert_bg.jpg").convert("RGBA")
        img = img.resize((800, 1200)) 
    except:
        img = Image.new('RGBA', (800, 1200), color='#0B0C10')
    draw = ImageDraw.Draw(img)
    
    def load_font(size, bold=True):
        font_names = ["DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", "arial.ttf"]
        for fn in font_names:
            try: return ImageFont.truetype(fn, size)
            except: pass
        return ImageFont.load_default()

    font_title = load_font(40, bold=True)
    font_name = load_font(45, bold=True)
    font_stats = load_font(24, bold=False) 
    font_sub = load_font(20, bold=False)

    def draw_centered(y, text, font, fill):
        try:
            bbox = draw.textbbox((0,0), text, font=font)
            w = bbox[2] - bbox[0]
        except: w = len(text) * 15
        draw.text(((800-w)/2, y), text, font=font, fill=fill)

    avatar_pasted = False
    if user_id:
        try:
            photos = await context.bot.get_user_profile_photos(user_id, limit=1)
            if photos.photos:
                file = await context.bot.get_file(photos.photos[0][-1].file_id)
                avatar_bytes = await file.download_as_bytearray()
                avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
                avatar = avatar.resize((230, 230))
                mask = Image.new('L', (230, 230), 0)
                ImageDraw.Draw(mask).ellipse((0, 0, 230, 230), fill=255)
                img.paste(avatar, (285, 135), mask)
                avatar_pasted = True
        except: pass

    draw_centered(470, title, font_title, '#F3E37C') 
    draw_centered(550, f"{username}", font_name, '#66FCF1') 
    draw_centered(650, f"Ochkolar: {pts}   |   G'alabalar: {wins}   |   PPG: {ppg:.2f}", font_stats, '#FFFFFF') 
    draw_centered(720, subtitle, font_sub, '#C5C6C7') 

    buf = io.BytesIO()
    img.convert('RGB').save(buf, format='JPEG', quality=95)
    buf.seek(0)
    return buf

# ==========================================
# 4. CHEMPIONAT (CUP) FUNKSIYALARI
# ==========================================

async def new_cup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    cursor.execute("INSERT OR IGNORE INTO groups (chat_id) VALUES (?)", (chat_id,))
    if not context.args:
        await update.effective_message.reply_text("Turnir nomini yozing: `/new_cup YozgiKubok`", parse_mode='HTML')
        return
    cup_name = context.args[0]
    cursor.execute("SELECT id FROM cups WHERE chat_id=? AND name=? AND status != 'finished'", (chat_id, cup_name))
    if cursor.fetchone():
        await update.effective_message.reply_text("❌ Bunday nomli faol turnir allaqachon bor!")
        return
    cursor.execute("INSERT INTO cups (chat_id, name, status) VALUES (?, ?, 'pending')", (chat_id, cup_name))
    conn.commit()
    await update.effective_message.reply_text(f"🏆 <b>{html.escape(cup_name)}</b> turniriga ro'yxatdan o'tish boshlandi!\nQatnashish uchun `/join {html.escape(cup_name)}` deb yozing.", parse_mode='HTML')

async def join_cup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.effective_message.reply_text("Turnir nomini yozing: `/join YozgiKubok`", parse_mode='HTML')
        return
    cup_name = context.args[0]
    username = f"@{update.effective_user.username}" if update.effective_user.username else f"@{update.effective_user.first_name}"
    cursor.execute("INSERT OR REPLACE INTO users (username, user_id) VALUES (?, ?)", (username, update.effective_user.id))
    cursor.execute("SELECT id, status FROM cups WHERE chat_id=? AND name=?", (chat_id, cup_name))
    cup = cursor.fetchone()
    if not cup:
        await update.effective_message.reply_text("❌ Bunday turnir topilmadi.")
        return
    if cup[1] != 'pending':
        await update.effective_message.reply_text("❌ Bu turnir allaqachon boshlangan yoki tugagan!")
        return
    cursor.execute("SELECT * FROM cup_participants WHERE cup_id=? AND LOWER(username)=LOWER(?)", (cup[0], username))
    if cursor.fetchone():
        await update.effective_message.reply_text("Siz allaqachon ro'yxatdan o'tgansiz!")
        return
    cursor.execute("INSERT INTO cup_participants (cup_id, username) VALUES (?, ?)", (cup[0], username))
    conn.commit()
    await update.effective_message.reply_text(f"✅ {html.escape(username)} <b>{html.escape(cup_name)}</b> ga qo'shildi!", parse_mode='HTML')

async def start_cup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.effective_message.reply_text("Turnir nomini yozing: `/start_cup YozgiKubok`", parse_mode='HTML')
        return
    cup_name = context.args[0]
    cursor.execute("SELECT id, status FROM cups WHERE chat_id=? AND name=?", (chat_id, cup_name))
    cup = cursor.fetchone()
    if not cup or cup[1] != 'pending':
        await update.effective_message.reply_text("❌ Boshlash uchun 'pending' holatidagi turnir topilmadi.")
        return
    cursor.execute("SELECT username FROM cup_participants WHERE cup_id=?", (cup[0],))
    participants = [r[0] for r in cursor.fetchall()]
    if len(participants) < 2:
        await update.effective_message.reply_text("❌ Turnirni boshlash uchun kamida 2 kishi kerak!")
        return
    for p1, p2 in itertools.combinations(participants, 2):
        cursor.execute("INSERT INTO cup_matches (cup_id, p1, p2, status) VALUES (?, ?, ?, 'pending')", (cup[0], p1, p2)) 
        cursor.execute("INSERT INTO cup_matches (cup_id, p1, p2, status) VALUES (?, ?, ?, 'pending')", (cup[0], p2, p1)) 
    cursor.execute("UPDATE cups SET status='active' WHERE id=?", (cup[0],))
    conn.commit()
    await update.effective_message.reply_text(f"🔥 <b>{html.escape(cup_name)}</b> RASMAN BOSHLANDI!\n\nFormat: Uy va Safar.\nNatijani odatdagidek kiritavering: `@Raqib yutdim 3-1`\n<i>(Bot o'zi avtomat shu turnirga yozib qo'yadi!)</i>", parse_mode='HTML')

async def cup_table(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        cursor.execute("SELECT name FROM cups WHERE chat_id=? AND status='active'", (chat_id,))
        active_cups = cursor.fetchall()
        if len(active_cups) == 1: cup_name = active_cups[0][0]
        elif len(active_cups) > 1:
            await update.effective_message.reply_text("Guruhda bir nechta faol turnir bor! Iltimos, nomini yozing: `/cup_table YozgiKubok`", parse_mode='HTML')
            return
        else:
            await update.effective_message.reply_text("Hozircha faol turnir yo'q.", parse_mode='HTML')
            return
    else: cup_name = context.args[0].replace("#", "")
        
    cursor.execute("SELECT id FROM cups WHERE chat_id=? AND name=?", (chat_id, cup_name))
    cup = cursor.fetchone()
    if not cup:
        await update.effective_message.reply_text("❌ Bunday turnir topilmadi.")
        return
    cursor.execute("SELECT p1, p2, p1_score, p2_score FROM cup_matches WHERE cup_id=? AND status='played'", (cup[0],))
    matches = cursor.fetchall()
    stats = {}
    cursor.execute("SELECT username FROM cup_participants WHERE cup_id=?", (cup[0],))
    for r in cursor.fetchall(): stats[r[0]] = {'games': 0, 'w': 0, 'd': 0, 'l': 0, 'gf': 0, 'ga': 0, 'pts': 0}
    for p1, p2, s1, s2 in matches:
        stats[p1]['games'] += 1; stats[p2]['games'] += 1
        stats[p1]['gf'] += s1; stats[p2]['gf'] += s2
        stats[p1]['ga'] += s2; stats[p2]['ga'] += s1
        if s1 > s2: stats[p1]['w'] += 1; stats[p1]['pts'] += 3; stats[p2]['l'] += 1
        elif s1 < s2: stats[p2]['w'] += 1; stats[p2]['pts'] += 3; stats[p1]['l'] += 1
        else: stats[p1]['d'] += 1; stats[p2]['d'] += 1; stats[p1]['pts'] += 1; stats[p2]['pts'] += 1
    sorted_pts = sorted(stats.items(), key=lambda x: (x[1]['pts'], x[1]['gf'] - x[1]['ga']), reverse=True)
    text = f"🏆 <b>{html.escape(cup_name)} JADVALI</b> 🏆\n<pre>"
    for idx, (player, s) in enumerate(sorted_pts, 1):
        gd_str = f"+{s['gf']-s['ga']}" if s['gf']-s['ga'] > 0 else str(s['gf']-s['ga'])
        text += f"{idx}. {html.escape(player).ljust(12)[:12]} | {str(s['pts']).rjust(2)} o | ⚽️ {gd_str} | O':{s['games']}\n"
    text += "</pre>"
    await update.effective_message.reply_text(text, parse_mode='HTML')

async def cup_fixtures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        cursor.execute("SELECT id, name FROM cups WHERE chat_id=? AND status='active'", (chat_id,))
        active_cups = cursor.fetchall()
        if len(active_cups) == 1: cup_id, cup_name = active_cups[0]
        elif len(active_cups) > 1:
            await update.effective_message.reply_text("Guruhda bir nechta faol turnir bor! `/taqvim YozgiKubok` deb yozing.", parse_mode='HTML')
            return
        else:
            await update.effective_message.reply_text("Hozircha faol turnir yo'q.", parse_mode='HTML')
            return
    else:
        cup_name = context.args[0].replace("#", "")
        cursor.execute("SELECT id, name FROM cups WHERE chat_id=? AND name=?", (chat_id, cup_name))
        cup = cursor.fetchone()
        if not cup:
            await update.effective_message.reply_text("❌ Bunday turnir topilmadi.")
            return
        cup_id, cup_name = cup

    cursor.execute("SELECT p1, p2 FROM cup_matches WHERE cup_id=? AND status='pending'", (cup_id,))
    pending = cursor.fetchall()
    if not pending:
        await update.effective_message.reply_text(f"✅ <b>{html.escape(cup_name)}</b> doirasida hamma o'yinlar o'ynab bo'lingan!", parse_mode='HTML')
        return

    pairs = {}
    for p1, p2 in pending:
        pair = tuple(sorted([p1, p2], key=lambda x: x.lower()))
        pairs[pair] = pairs.get(pair, 0) + 1

    text = f"📅 <b>{html.escape(cup_name)} - QOLGAN O'YINLAR:</b>\n\n"
    for (p1, p2), count in sorted(pairs.items()):
        text += f"⚔️ {html.escape(p1)} 🆚 {html.escape(p2)} (<b>{count} ta o'yin</b>)\n"
    
    text += "\n<i>Bo'sh vaqt topib o'ynab qo'yamiz!</i> 🎮"
    await update.effective_message.reply_text(text, parse_mode='HTML')

async def end_cup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        cursor.execute("SELECT name FROM cups WHERE chat_id=? AND status='active'", (chat_id,))
        active_cups = cursor.fetchall()
        if len(active_cups) == 1: cup_name = active_cups[0][0]
        else:
            await update.effective_message.reply_text("Turnir nomini yozing: `/end_cup YozgiKubok`", parse_mode='HTML')
            return
    else: cup_name = context.args[0].replace("#", "")
        
    cursor.execute("SELECT id, status FROM cups WHERE chat_id=? AND name=?", (chat_id, cup_name))
    cup = cursor.fetchone()
    if not cup or cup[1] != 'active':
        await update.effective_message.reply_text("❌ Yopish uchun faol turnir topilmadi.")
        return
    cursor.execute("SELECT p1, p2, p1_score, p2_score FROM cup_matches WHERE cup_id=? AND status='played'", (cup[0],))
    matches = cursor.fetchall()
    stats = {}
    cursor.execute("SELECT username FROM cup_participants WHERE cup_id=?", (cup[0],))
    for r in cursor.fetchall(): stats[r[0]] = {'games': 0, 'w': 0, 'gf': 0, 'ga': 0, 'pts': 0}
    for p1, p2, s1, s2 in matches:
        stats[p1]['games'] += 1; stats[p2]['games'] += 1
        stats[p1]['gf'] += s1; stats[p2]['gf'] += s2
        stats[p1]['ga'] += s2; stats[p2]['ga'] += s1
        if s1 > s2: stats[p1]['w'] += 1; stats[p1]['pts'] += 3
        elif s1 < s2: stats[p2]['w'] += 1; stats[p2]['pts'] += 3
        else: stats[p1]['pts'] += 1; stats[p2]['pts'] += 1
    sorted_pts = sorted(stats.items(), key=lambda x: (x[1]['pts'], x[1]['gf'] - x[1]['ga']), reverse=True)
    winner_username = sorted_pts[0][0]
    winner_data = sorted_pts[0][1]
    cursor.execute("UPDATE cups SET status='finished' WHERE id=?", (cup[0],))
    conn.commit()
    cursor.execute("SELECT user_id FROM users WHERE LOWER(username) = LOWER(?)", (winner_username,))
    user_row = cursor.fetchone()
    winner_id = user_row[0] if user_row else None

    await update.effective_message.reply_text(f"🏁 <b>{html.escape(cup_name)}</b> RASMAN YAKUNLANDI!\nMutlaq chempion: {html.escape(winner_username)} 🎉", parse_mode='HTML')
    try:
        cert_buf = await generate_certificate(
            context, winner_id, winner_username, 
            winner_data['pts'], winner_data['w'], winner_data['pts']/winner_data['games'] if winner_data['games']>0 else 0,
            title="🏆 K U B O K   S O H I B I 🏆", subtitle=f"{cup_name} Mutlaq Chempioni"
        )
        await context.bot.send_photo(chat_id=chat_id, photo=cert_buf, caption="🏆 Chempionlik Sertifikati!")
    except Exception as e: print(f"Sertifikat xato: {e}")

# ==========================================
# 5. ASOSIY BUYRUQLAR
# ==========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    cursor.execute("INSERT OR IGNORE INTO groups (chat_id) VALUES (?)", (chat_id,))
    conn.commit()
    text = (
        "⚽ <b>PES/FC LIGASI BOTI!</b>\n\n"
        "<b>Natija kiritish:</b> `@ali yutdim 3-1`\n"
        "<i>(Agar guruhda turnir ketyotgan bo'lsa, bot o'zi avtomat o'sha turnirga yozib qo'yadi!)</i>\n\n"
        "<b>Asosiy:</b> /jadval, /tarix, /stat, /h2h\n"
        "<b>Turnir:</b> /new_cup, /join, /start_cup, /cup_table, /taqvim, /end_cup"
    )
    await update.effective_message.reply_text(text, parse_mode='HTML')

async def handle_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.effective_message.text
    if not text: return
    chat_id = update.effective_chat.id
    cursor.execute("INSERT OR IGNORE INTO groups (chat_id) VALUES (?)", (chat_id,))

    pattern = r'@(\w+)\s+(yutdim|yutqazdim|durang)\s+(\d+)\s*[-:]\s*(\d+)(?:\s+#(\w+))?'
    match = re.search(pattern, text, re.IGNORECASE)

    if match:
        opp_raw = f"@{match.group(1)}"
        action = match.group(2).lower()
        s1 = int(match.group(3))
        s2 = int(match.group(4))
        cup_hashtag = match.group(5)

        sender = update.effective_user
        my_raw = f"@{sender.username or sender.first_name}"
        cursor.execute("INSERT OR REPLACE INTO users (username, user_id) VALUES (?, ?)", (my_raw, sender.id))
        conn.commit()

        if my_raw.lower() == opp_raw.lower():
            await update.effective_message.reply_text("O'zingiz bilan o'zingiz o'ynay olmaysiz! 😊")
            return

        if action == "yutdim": my_goals, opp_goals = max(s1, s2), min(s1, s2)
        elif action == "yutqazdim": my_goals, opp_goals = min(s1, s2), max(s1, s2)
        else: my_goals, opp_goals = s1, s2 

        my_esc = html.escape(my_raw)
        opp_esc = html.escape(opp_raw)

        if not cup_hashtag:
            cursor.execute("SELECT name FROM cups WHERE chat_id=? AND status='active'", (chat_id,))
            active_cups = cursor.fetchall()
            if len(active_cups) == 1:
                cup_hashtag = active_cups[0][0] 

        msg_prefix = ""

        if cup_hashtag:
            cursor.execute("SELECT id FROM cups WHERE chat_id=? AND LOWER(name)=LOWER(?) AND status='active'", (chat_id, cup_hashtag))
            cup = cursor.fetchone()
            if cup:
                cursor.execute('''SELECT id FROM cup_matches WHERE cup_id=? AND status='pending' 
                                  AND ((LOWER(p1)=LOWER(?) AND LOWER(p2)=LOWER(?)) OR (LOWER(p1)=LOWER(?) AND LOWER(p2)=LOWER(?))) LIMIT 1''', 
                               (cup[0], my_raw, opp_raw, opp_raw, my_raw))
                cup_match = cursor.fetchone()
                if cup_match:
                    cursor.execute("UPDATE cup_matches SET p1=?, p2=?, p1_score=?, p2_score=?, status='played', date_played=CURRENT_TIMESTAMP WHERE id=?", 
                                   (my_raw, opp_raw, my_goals, opp_goals, cup_match[0]))
                    conn.commit()
                    msg_prefix = f"🏆 <b>#{html.escape(cup_hashtag)}:</b>\n"

        cursor.execute("INSERT INTO matches (chat_id, p1, p2, p1_score, p2_score) VALUES (?, ?, ?, ?, ?)",
                       (chat_id, my_raw, opp_raw, my_goals, opp_goals))
        conn.commit()

        if my_goals > opp_goals: 
            farq = my_goals - opp_goals
            if farq >= 3: msg = f"{msg_prefix}🔥 <b>Ajoyib o'yin!</b> {my_esc} {opp_esc} ustidan yirik hisobda g'alaba qozondi ({my_goals}:{opp_goals})!"
            else: msg = f"{msg_prefix}✅ <b>G'alaba!</b> {my_esc} {opp_esc} ustidan ishonchli g'alabaga erishdi ({my_goals}:{opp_goals})."
        elif my_goals < opp_goals: 
            msg = f"{msg_prefix}👏 <b>Chiroyli o'yin!</b> {my_esc} mag'lubiyatni mardona tan oldi. {opp_esc} g'alaba qozondi ({opp_goals}:{my_goals})!"
        else: 
            msg = f"{msg_prefix}🤝 <b>Murosasiz va do'stona jang!</b> {my_esc} va {opp_esc} durang o'ynadi ({my_goals}:{opp_goals})."
        await update.effective_message.reply_text(msg, parse_mode='HTML')

async def show_table(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = get_stats_by_period(update.effective_chat.id)
    if not stats:
        await update.effective_message.reply_text("Hali maydonga hech kim tushmadi. Qani, kim boshlab beradi? ⚽️")
        return
    sorted_pts = sorted(stats.items(), key=lambda x: (x[1]['pts'], x[1]['gf'] - x[1]['ga']), reverse=True)
    valid_ppg = {k: v for k, v in stats.items() if v['games'] >= 3 and v['unique_opponents'] >= 2}
    sorted_ppg = sorted(valid_ppg.items(), key=lambda x: x[1]['true_ppg'], reverse=True)

    text = "🏆 <b>FC DO'STLAR LIGASI (Umumiy Tarix)</b> 🏆\n\n📊 <b>1. UMUMIY OCHKOLAR</b>\n<pre>"
    for idx, (player, s) in enumerate(sorted_pts, 1):
        gd_str = f"+{s['gf']-s['ga']}" if s['gf']-s['ga'] > 0 else str(s['gf']-s['ga'])
        text += f"{idx}. {html.escape(player).ljust(12)[:12]} | {str(s['pts']).rjust(2)} o | ⚽️ {gd_str}\n"
    text += "</pre>\n"
    if sorted_ppg:
        text += "📈 <b>2. HAQIQIY KOEFFITSIYENT (Sifat)</b>\n<pre>"
        for idx, (player, s) in enumerate(sorted_ppg, 1):
            text += f"{idx}. {html.escape(player).ljust(12)[:12]} | {s['true_ppg']:.2f} PPG\n"
        text += "</pre>"
    await update.effective_message.reply_text(text, parse_mode='HTML')

async def match_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    seven_days_ago = datetime.now() - timedelta(days=7)
    cursor.execute("SELECT id, p1, p2, p1_score, p2_score FROM matches WHERE chat_id=? AND date >= ? ORDER BY id DESC", (update.effective_chat.id, seven_days_ago))
    rows = cursor.fetchall()
    if not rows:
        await update.effective_message.reply_text("Oxirgi 1 haftada hech qanday o'yin bo'lmadi. 😴")
        return
    text = "📜 <b>OXIRGI 7 KUNLIK QONLI JANGLAR:</b>\n\n<pre>"
    for r in rows: text += f"[ID: {r[0]}] {html.escape(r[1])} {r[3]}:{r[4]} {html.escape(r[2])}\n"
    text += "</pre>"
    await update.effective_message.reply_text(text, parse_mode='HTML')

async def delete_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text("Iltimos, o'yin ID sini kiriting. Masalan: <code>/del 45</code>", parse_mode='HTML')
        return
    if update.effective_chat.type in ['group', 'supergroup']:
        user_status = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        if user_status.status not in ['administrator', 'creator']:
            await update.effective_message.reply_text("❌ Natijalarni faqat guruh adminlari o'zgartirishi mumkin.", parse_mode='HTML')
            return
    match_id = context.args[0]
    cursor.execute("SELECT p1, p2, p1_score, p2_score FROM matches WHERE id = ? AND chat_id=?", (match_id, update.effective_chat.id))
    row = cursor.fetchone()
    if not row:
        await update.effective_message.reply_text("Bunday ID raqamli o'yin topilmadi.")
        return
    cursor.execute("DELETE FROM matches WHERE id = ?", (match_id,))
    conn.commit()
    await update.effective_message.reply_text(f"📺 <b>VAR QARORI:</b> ID {match_id} o'chirildi!", parse_mode='HTML')

async def player_stat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text("Foydalanuvchini kiriting: <code>/stat @ali</code>", parse_mode='HTML')
        return
    player = context.args[0]
    stats = get_stats_by_period(update.effective_chat.id)
    player_key = next((k for k in stats.keys() if k.lower() == player.lower()), None)
    if not player_key:
        await update.effective_message.reply_text(f"{html.escape(player)} hali maydonga tushmagan.")
        return
    s = stats[player_key]
    text = (f"👤 <b>FUTBOLCHI DOSYESI: {html.escape(player_key)}</b>\n\n🏟 Jami o'yinlar: <b>{s['games']} ta</b>\n"
            f"✅ G'alaba: <b>{s['w']}</b> | 🤝 Durang: <b>{s['d']}</b> | ❌ Mag'lubiyat: <b>{s['l']}</b>\n"
            f"⚽️ To'plar nisbati: <b>{s['gf']} - {s['ga']}</b> (Farq: {s['gf'] - s['ga']})\n📊 Haqiqiy Koeffitsiyent: <b>{s['true_ppg']:.2f}</b>")
    await update.effective_message.reply_text(text, parse_mode='HTML')

async def h2h_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.effective_message.reply_text("Ikkita o'yinchini kiriting: <code>/h2h @men @ali</code>", parse_mode='HTML')
        return
    p1, p2 = context.args[0], context.args[1]
    cursor.execute('''SELECT p1, p2, p1_score, p2_score FROM matches WHERE chat_id=? AND ((LOWER(p1) = LOWER(?) AND LOWER(p2) = LOWER(?)) OR (LOWER(p1) = LOWER(?) AND LOWER(p2) = LOWER(?)))''', (update.effective_chat.id, p1, p2, p2, p1))
    games = cursor.fetchall()
    if not games:
        await update.effective_message.reply_text(f"{html.escape(p1)} va {html.escape(p2)} o'rtasida hali o'yin bo'lmagan.")
        return
    p1_wins = p2_wins = draws = 0
    for g_p1, g_p2, s1, s2 in games:
        score1, score2 = (s1, s2) if g_p1.lower() == p1.lower() else (s2, s1)
        if score1 > score2: p1_wins += 1
        elif score2 > score1: p2_wins += 1
        else: draws += 1
    text = (f"⚔️ <b>EL-CLASICO: {html.escape(p1)} 🆚 {html.escape(p2)}</b>\n\n📊 Jami to'qnashuvlar: <b>{len(games)} ta</b>\n"
            f"👑 {html.escape(p1)} g'alabasi: <b>{p1_wins} ta</b>\n😭 {html.escape(p2)} g'alabasi: <b>{p2_wins} ta</b>\n🤝 Durang: <b>{draws} ta</b>")
    await update.effective_message.reply_text(text, parse_mode='HTML')

async def test_cert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private':
        await update.effective_message.reply_text("🤫 Syurpriz buzilmasligi uchun bu buyruqni faqat botning shaxsiy yozishmasida (lichkada) ishlating!")
        return
    user_id = update.effective_user.id
    username = f"@{update.effective_user.username}" if update.effective_user.username else update.effective_user.first_name
    try:
        cert_buf = await generate_certificate(context, user_id, username, 45, 15, 2.50)
        await update.effective_message.reply_photo(photo=cert_buf, caption="🏆 Mana, Haqiqiy Oltin Sertifikat! 😎")
    except Exception as e:
        await update.effective_message.reply_text(f"Xatolik chiqdi: {e}")

# ==========================================
# 7. AVTOMATIK XABARLAR (SUKUNAT REJIMI BILAN)
# ==========================================

async def run_for_all_groups(context, func, *args, **kwargs):
    cursor.execute("SELECT chat_id FROM groups")
    for row in cursor.fetchall():
        try: await func(context, row[0], *args, **kwargs)
        except Exception as e: print(f"Group {row[0]} xato: {e}")

async def job_daily_summary(context: ContextTypes.DEFAULT_TYPE):
    async def _task(ctx, chat_id):
        # FAOL TURNIR BOR GURUHDA MEMLAR O'CHIRILADI!
        cursor.execute("SELECT id FROM cups WHERE chat_id=? AND status='active'", (chat_id,))
        if cursor.fetchone(): return 

        stats = get_stats_by_period(chat_id, today_only=True)
        if not stats: return 
        sorted_pts = sorted(stats.items(), key=lambda x: (x[1]['pts'], x[1]['gf'] - x[1]['ga']), reverse=True)
        winner = html.escape(sorted_pts[0][0])
        loser = html.escape(sorted_pts[-1][0])
        await ctx.bot.send_animation(chat_id=chat_id, animation=random.choice(DAILY_WINNER_MEMES)["gif"], caption=f"👑 Bugun {winner} hammadan ustun!", parse_mode='HTML')
        if len(sorted_pts) > 1:
            await asyncio.sleep(60)
            await ctx.bot.send_animation(chat_id=chat_id, animation=random.choice(DAILY_LOSER_MEMES)["gif"], caption=f"🤝 {loser}, keyingi safar albatta o'xshaydi!", parse_mode='HTML')
    await run_for_all_groups(context, _task)

async def job_weekly_chart(context: ContextTypes.DEFAULT_TYPE):
    async def _task(ctx, chat_id):
        tz_uz = timezone(timedelta(hours=5))
        now = datetime.now(tz_uz)
        curr_start = now - timedelta(days=7)
        prev_start = curr_start - timedelta(days=7)
        curr_stats = get_stats_by_date_range(chat_id, curr_start, now)
        prev_stats = get_stats_by_date_range(chat_id, prev_start, curr_start)
        if not curr_stats: return
        chart_buf = create_comparison_chart(curr_stats, prev_stats, "📊 HAFTALIK ANALITIKA")
        await ctx.bot.send_photo(chat_id=chat_id, photo=chart_buf, caption="📈 <b>Haftalik Analitika Markazi!</b>", parse_mode='HTML')
    await run_for_all_groups(context, _task)

async def job_monthly_cert(context: ContextTypes.DEFAULT_TYPE):
    tz_uz = timezone(timedelta(hours=5))
    now = datetime.now(tz_uz)
    if now.day != 1: return 
    async def _task(ctx, chat_id):
        curr_end = now.replace(hour=0, minute=0, second=0, microsecond=0)
        curr_start = (curr_end - timedelta(days=1)).replace(day=1)
        curr_stats = get_stats_by_date_range(chat_id, curr_start, curr_end)
        if not curr_stats: return
        sorted_pts = sorted(curr_stats.items(), key=lambda x: (x[1]['pts'], x[1]['gf'] - x[1]['ga']), reverse=True)
        winner_username = sorted_pts[0][0]
        winner_data = sorted_pts[0][1]
        cursor.execute("SELECT user_id FROM users WHERE LOWER(username) = LOWER(?)", (winner_username,))
        user_row = cursor.fetchone()
        winner_id = user_row[0] if user_row else None
        try:
            cert_buf = await generate_certificate(ctx, winner_id, winner_username, winner_data['pts'], winner_data['w'], winner_data['true_ppg'])
            await ctx.bot.send_photo(chat_id=chat_id, photo=cert_buf, caption=f"🎉 <b>OY QIROLI ANIQLANDI!</b>\n\n{html.escape(winner_username)}, bu maxsus Oltin Sertifikat sizga ataldi! Tabriklaymiz! 🏆", parse_mode='HTML')
        except: pass
    await run_for_all_groups(context, _task)

async def job_cup_reminders(context: ContextTypes.DEFAULT_TYPE):
    async def _task(ctx, chat_id):
        cursor.execute("SELECT id, name FROM cups WHERE chat_id=? AND status='active'", (chat_id,))
        cups = cursor.fetchall()
        for cup_id, cup_name in cups:
            cursor.execute("SELECT p1, p2 FROM cup_matches WHERE cup_id=? AND status='pending'", (cup_id,))
            pending = cursor.fetchall()
            if not pending: continue
            counts = {}
            for p1, p2 in pending:
                counts[p1] = counts.get(p1, 0) + 1
                counts[p2] = counts.get(p2, 0) + 1
            msg = f"🔔 <b>#{html.escape(cup_name)} doirasida o'ynalmagan o'yinlar:</b>\n\n"
            for p, c in sorted(counts.items(), key=lambda x: x[1], reverse=True): msg += f"👉 {html.escape(p)}: <b>{c} ta o'yin</b> qoldi.\n"
            msg += "\nBo'sh vaqt topib, o'yinlarni davom ettirib qo'yamiz! 🎮"
            await ctx.bot.send_message(chat_id=chat_id, text=msg, parse_mode='HTML')
    await run_for_all_groups(context, _task)

async def job_daily_provocation(context: ContextTypes.DEFAULT_TYPE):
    async def _task(ctx, chat_id):
        # FAOL TURNIR BOR GURUHDA CHORLOV MEMLARI O'CHIRILADI!
        cursor.execute("SELECT id FROM cups WHERE chat_id=? AND status='active'", (chat_id,))
        if cursor.fetchone(): return 

        stats = get_stats_by_period(chat_id, days=3)
        if stats and len(stats) >= 2:
            sorted_pts = sorted(stats.items(), key=lambda x: (x[1]['pts'], x[1]['gf'] - x[1]['ga']), reverse=True)
            top1, bottom = html.escape(sorted_pts[0][0]), html.escape(sorted_pts[-1][0])
            
            TEXT_TEMPLATES = [
                f"🔥 Oxirgi 3 kunda {top1} ajoyib o'yin ko'rsatmoqda! Kimdir uning g'alabali seriyasiga chek qo'yadimi?\n{bottom}, imkoniyatni qo'ldan boy bermang!",
                f"🗣 {top1} hozircha reyting peshqadami. {bottom}, bugun sizning kuningiz bo'lishi mumkin, jangga marhamat!",
                f"🏆 Chempionlik uchun kurash qizg'in pallada! {top1} peshqadam, lekin vaziyat har an o'zgarishi mumkin.",
                f"🎮 Barchaga yaxshi kayfiyat! {top1} o'z o'rnini mustahkamlamoqda. Qani, bugun kim maydonga tushadi?",
                f"⚔️ Do'stona raqobat davom etadi! {top1} ni to'xtatadigan munosib raqib bormi?"
            ]
            msg = random.choice(TEXT_TEMPLATES)
            await ctx.bot.send_animation(chat_id=chat_id, animation=GIF_WIN_1, caption=msg, parse_mode='HTML')
    await run_for_all_groups(context, _task)

async def check_inactive_players(context: ContextTypes.DEFAULT_TYPE):
    async def _task(ctx, chat_id):
        # FAOL TURNIR BOR GURUHDA MEMLAR O'CHIRILADI!
        cursor.execute("SELECT id FROM cups WHERE chat_id=? AND status='active'", (chat_id,))
        if cursor.fetchone(): return 

        cursor.execute("SELECT p1, p2 FROM matches WHERE chat_id=?", (chat_id,))
        all_players = set([p for match in cursor.fetchall() for p in match])
        start_utc = (datetime.utcnow() - timedelta(days=5)).strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute("SELECT p1, p2 FROM matches WHERE chat_id=? AND date >= ?", (chat_id, start_utc))
        active_players = set([p for match in cursor.fetchall() for p in match])
        inactive_players = all_players - active_players
        if inactive_players:
            mentions = ", ".join([html.escape(p) for p in inactive_players])
            msg = f"🔔 <b>Hurmatli ishtirokchilar!</b>\n\n{mentions} — 5 kundan beri maydonda ko'rinmaysizlar. Bo'sh vaqt topib, o'yinlarni davom ettirib qo'yamiz! 🎮"
            try:
                await ctx.bot.send_animation(chat_id=chat_id, animation="CgACAgIAAxkBAAO8aoXamtCs_ekIJh7Dj7X1N7r0Z9UAAqeuAAJtRTBI4RGqc2Mp8Mk9BA", caption=msg, parse_mode='HTML')
            except Exception as e: print(f"Inactive xato: {e}")
    await run_for_all_groups(context, _task)

def main():
    token = os.getenv("BOT_TOKEN")
    if not token: return

    threading.Thread(target=run_dummy_server, daemon=True).start()
    app = Application.builder().token(token).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("jadval", show_table))
    app.add_handler(CommandHandler("tarix", match_history))
    app.add_handler(CommandHandler("stat", player_stat))
    app.add_handler(CommandHandler("h2h", h2h_stats))
    app.add_handler(CommandHandler("del", delete_match))
    app.add_handler(CommandHandler("testcert", test_cert))
    app.add_handler(CommandHandler("new_cup", new_cup))
    app.add_handler(CommandHandler("join", join_cup))
    app.add_handler(CommandHandler("start_cup", start_cup))
    app.add_handler(CommandHandler("cup_table", cup_table))
    app.add_handler(CommandHandler("taqvim", cup_fixtures))
    app.add_handler(CommandHandler("end_cup", end_cup))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_match))

    tz_uz = timezone(timedelta(hours=5))
    
    app.job_queue.run_daily(job_daily_summary, time=time(hour=23, minute=0, tzinfo=tz_uz))
    app.job_queue.run_daily(job_weekly_chart, time=time(hour=20, minute=1, tzinfo=tz_uz), days=(6,))
    app.job_queue.run_daily(job_monthly_cert, time=time(hour=12, minute=0, tzinfo=tz_uz))
    app.job_queue.run_daily(check_inactive_players, time=time(hour=15, minute=0, tzinfo=tz_uz))
    
    now = datetime.now(tz_uz)
    first_19 = now.replace(hour=19, minute=0, second=0, microsecond=0)
    if now > first_19: first_19 += timedelta(days=1)
    app.job_queue.run_repeating(job_cup_reminders, interval=timedelta(days=2), first=first_19)
    
    first_16 = now.replace(hour=16, minute=0, second=0, microsecond=0)
    if now > first_16: first_16 += timedelta(days=1)
    app.job_queue.run_repeating(job_daily_provocation, interval=timedelta(days=2), first=first_16)

    print("Bot ishga tushdi...")
    app.run_polling()

if __name__ == "__main__":
    main()

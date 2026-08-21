import os
import sqlite3
import re
import html
import threading
import random
import asyncio
import io
from datetime import datetime, timedelta, time, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Grafik va Rasmlar uchun kutubxonalar
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
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        user_id INTEGER
    )
''')
conn.commit()

# ==========================================
# 2. RANDOM MEMLAR VA GIFLAR BAZASI
# ==========================================

GIF_WIN_1 = "CgACAgQAAxkBAAIBIGqInhqnXgL3lO_XQBY6ovgLxj-8AALrCQACXiTkUqOL8Djg85SsPQQ" 
GIF_WIN_2 = "CgACAgIAAxkBAAIBImqInxDQjVfHKiGY2q0gXH8okpY6AALeBgACyTthSrIe1TGtXuzbPQQ" 
GIF_WIN_3 = "CgACAgIAAxkBAAIBPmqIowbF2Nqs6JmyZcPFOs3PlvfQAAL5EAACPr1ISLAYW28QSZsaPQQ" 

GIF_LOSE_1 = "CgACAgIAAxkBAAIBHmqInWIBZpGjbGSchBUlGUPTJr-kAALYCgACfTIpSH4-y3c88xEPPQQ" 
GIF_LOSE_2 = "CgACAgQAAxkBAAIBJGqIn-0bWWoaOUTxlBdHjB4AAWK-tQACBgcAArKW9VGE-n38Dog1wT0E" 
GIF_LOSE_3 = "CgACAgIAAxkBAAIBMmqIoo3kfjIzyjhnFY3J0F0g8izTAAKqEAACPr1ISFbgiO_nZbs6PQQ" 
GIF_LOSE_4 = "CgACAgIAAxkBAAIBNGqIoqg_h9A-9Q1n8o_MBoGsypBnAAKPFwACrupASIRE7lFwpooSPQQ" 
GIF_LOSE_5 = "CgACAgIAAxkBAAIBNmqIorzBYLJKcOkjqWycif7zkC4fAALPDwAC2CNBSFaQOKk6kUgwPQQ" 
GIF_LOSE_6 = "CgACAgQAAxkBAAIBPGqIotzyG4QFneP2CXemyuKU_96uAAKQDgACmRFJUFlZpxugsTPJPQQ" 
GIF_LOSE_7 = "CgACAgQAAxkBAAIBRGqIo0x9SSwIt7fAv6LLrV2dEAMAAwcNAAJOskhQ2YVnzlj04gABPQQ" 
GIF_LOSE_8 = "CgACAgIAAxkBAAIBRmqIo2z9GjcGYOCWf8nA7c6nNfN_AAK3EwACrt9ISEQ7CsptOpq4PQQ" 
GIF_LOSE_9 = "CgACAgIAAxkBAAIBTmqIpEEEg04q8x9FfXmyRCx3-x1CAAJWEgACXjhISHwqidLUrqzoPQQ" 
GIF_LOSE_10 = "CgACAgUAAxkBAAIBVGqIpHMXXCSGqQHtAt3bPIAhYqSYAAIsBAACY-RRVMaGR-SJtGCrPQQ" 
GIF_LOSE_11 = "CgACAgIAAxkBAAIBVmqIpJU38JgdxhPmUVDb3UE_e1RzAAKkFgACHklASGUIw6SKEOHnPQQ" 

WEEKLY_WINNER_MEMES = [
    {"text": "👑 <b>\"Meni o'zingga tenglashtirma, kazo-kazolardanman men!\"</b>\n{player} bu hafta hammadan ustun! <i>({reason})</i>", "gif": GIF_WIN_1},
    {"text": "🥇 <b>\"To'y bolani o'zini o'yinga chorlaymiz!\"</b>\n{player} butun hafta maydonda yallo qilib raqsga tushdi! <i>({reason})</i>", "gif": GIF_WIN_2},
    {"text": "😎 <b>\"Normalniy bollar bilan normalniy o'ynaymiz!\"</b>\n{player} bu hafta raqiblarni hurmatini joyiga qo'yib, darsini berdi. <i>({reason})</i>", "gif": GIF_WIN_3}
]

DAILY_WINNER_MEMES = [
    {"text": "👑 <b>\"Meni o'zingga tenglashtirma, kazo-kazolardanman men!\"</b>\n{player} bugun hammadan ustun! <i>({reason})</i>", "gif": GIF_WIN_1},
    {"text": "🥇 <b>\"To'y bolani o'zini o'yinga chorlaymiz!\"</b>\n{player} bugun maydonda yallo qilib raqsga tushyapti! <i>({reason})</i>", "gif": GIF_WIN_2},
    {"text": "😎 <b>\"Normalniy bollar bilan normalniy o'ynaymiz!\"</b>\n{player} bugun raqiblarni hurmatini joyiga qo'yib, darsini berib qo'ydi. <i>({reason})</i>", "gif": GIF_WIN_3}
]

DAILY_LOSER_MEMES = [
    {"text": "🤦‍♂️ <b>\"E, yashamargur, shuyam o'yin bo'ldimi?!\"</b>\n{player}, senga joystik ushlashga kim ruxsat berdi o'zi? Sharmanda!", "gif": GIF_LOSE_1},
    {"text": "🐢 <b>\"Kim edigu, kim bo'ldik!\"</b>\n{player} ning ahvoliga maymunlar yig'layapti.", "gif": GIF_LOSE_4},
    {"text": "😭 <b>\"Dada, man o'ynamayman!\"</b>\n{player} yig'lab yuborishiga oz qoldi.", "gif": GIF_LOSE_6},
    {"text": "🪦 <b>\"Taqdir ekan-da, peshonada bor ekan!\"</b>\n{player} mag'lubiyatga shunchalik ko'nikib ketdiki, yutqazsa ham xursand.", "gif": GIF_LOSE_7},
    {"text": "🤕 <b>\"Yurak qon bo'lib ketdi-ku!\"</b>\n{player} ni qiynamanglar endi, u ham odam.", "gif": GIF_LOSE_8},
    {"text": "👶 <b>\"Sen hali yoshsan, g'o'rsan!\"</b>\n{player}, borib mashg'ulot rejimida botlar bilan o'yna!", "gif": GIF_LOSE_9},
    {"text": "🎮 <b>\"Joystik yaxshi ishlamay qoldi-da, boʻlmasa koʻrardik...\"</b>\n{player} ning navbatdagi bahonasi tayyor!", "gif": "CgACAgQAAxkBAAPsaobmYGR_YQGgczhjgkPGTxUBclMAAgEMAALi4kFQkP6QlJAC7TY9BA"},
    {"text": "♟ <b>\"Aka, bu oʻyin sizniki emas ekan, shaxmatga oʻting...\"</b>\n{player}, futbolni yig'ishtiring, asabga ziyon!", "gif": GIF_LOSE_11},
    {"text": "📉 <b>\"Uka, bu sening darajang emas...\"</b>\n{player} kattalar o'yiniga adashib kirib qolibdi.", "gif": GIF_LOSE_2},
    {"text": "🧠 <b>\"Muammo nimadaligini bilasanmi? Senda reja yoʻq!\"</b>\n{player} maydonda nima qilayotganini o'zi ham bilmaydi.", "gif": GIF_LOSE_10},
    {"text": "⛰ <b>\"Aytudim-a shu tepalikka chiqmaylik deb\"</b>\n{player} kuchli raqiblarga duch kelib, qattiq pushaymon bo'lyapti!", "gif": GIF_LOSE_3}
]

# ==========================================
# 3. STATISTIKA VA GRAFIKLAR
# ==========================================

def get_stats_by_date_range(start_dt, end_dt):
    start_utc = start_dt.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    end_utc = end_dt.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    
    cursor.execute("SELECT p1, p2, p1_score, p2_score FROM matches WHERE date >= ? AND date < ?", (start_utc, end_utc))
    matches = cursor.fetchall()
    stats = {}
    
    for p1, p2, s1, s2 in matches:
        for p in (p1, p2):
            if p not in stats:
                stats[p] = {'games': 0, 'w': 0, 'd': 0, 'l': 0, 'gf': 0, 'ga': 0, 'pts': 0, 'h2h': {}}
        
        if p2 not in stats[p1]['h2h']: stats[p1]['h2h'][p2] = {'games': 0, 'pts': 0}
        if p1 not in stats[p2]['h2h']: stats[p2]['h2h'][p1] = {'games': 0, 'pts': 0}

        stats[p1]['games'] += 1
        stats[p2]['games'] += 1
        stats[p1]['gf'] += s1
        stats[p2]['gf'] += s2
        stats[p1]['ga'] += s2
        stats[p2]['ga'] += s1
        stats[p1]['h2h'][p2]['games'] += 1
        stats[p2]['h2h'][p1]['games'] += 1
        
        if s1 > s2:
            stats[p1]['w'] += 1
            stats[p1]['pts'] += 3
            stats[p2]['l'] += 1
            stats[p1]['h2h'][p2]['pts'] += 3
        elif s1 < s2:
            stats[p2]['w'] += 1
            stats[p2]['pts'] += 3
            stats[p1]['l'] += 1
            stats[p2]['h2h'][p1]['pts'] += 3
        else:
            stats[p1]['d'] += 1
            stats[p2]['d'] += 1
            stats[p1]['pts'] += 1
            stats[p2]['pts'] += 1
            stats[p1]['h2h'][p2]['pts'] += 1
            stats[p2]['h2h'][p1]['pts'] += 1

    for p, data in stats.items():
        total_h2h_ppg = 0
        unique_opponents = len(data['h2h'])
        for opp, h2h_data in data['h2h'].items():
            total_h2h_ppg += h2h_data['pts'] / h2h_data['games']
        data['true_ppg'] = total_h2h_ppg / unique_opponents if unique_opponents > 0 else 0.0
        data['unique_opponents'] = unique_opponents
            
    return stats

def get_stats_by_period(days=None, today_only=False):
    tz_uz = timezone(timedelta(hours=5))
    now_uz = datetime.now(tz_uz)
    if today_only: start_dt = now_uz.replace(hour=0, minute=0, second=0, microsecond=0)
    elif days: start_dt = now_uz - timedelta(days=days)
    else: start_dt = now_uz - timedelta(days=3650)
    return get_stats_by_date_range(start_dt, now_uz)

def create_comparison_chart(curr_stats, prev_stats, title_text):
    players, pts_list, colors, labels = [], [], [], []
    sorted_curr = sorted(curr_stats.items(), key=lambda x: x[1]['pts'], reverse=False)

    for p, data in sorted_curr:
        c_pts = data['pts']
        p_pts = prev_stats.get(p, {}).get('pts', 0)
        diff = c_pts - p_pts
        players.append(p)
        pts_list.append(c_pts)
        if diff > 0:
            colors.append('#4CAF50')
            labels.append(f"{c_pts} (+{diff} 📈)")
        elif diff < 0:
            colors.append('#F44336')
            labels.append(f"{c_pts} ({diff} 📉)")
        else:
            colors.append('#2196F3')
            labels.append(f"{c_pts} (➖)")

    plt.figure(figsize=(8, len(players) * 0.6 + 2))
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

# ==========================================
# 4. SERTIFIKAT YASASH (MUKAMMAL DIZAYN)
# ==========================================

async def generate_certificate(context, user_id, username, pts, wins, ppg):
    try:
        img = Image.open("cert_bg.jpg").convert("RGBA")
        img = img.resize((800, 1200)) 
    except Exception as e:
        print(f"Fon rasm topilmadi: {e}")
        img = Image.new('RGBA', (800, 1200), color='#0B0C10')

    draw = ImageDraw.Draw(img)
    
    # Shriftlarni xavfsiz yuklash (Render serveri uchun standart shriftlar)
    def load_font(size, bold=True):
        font_names = [
            "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
            "LiberationSans-Bold.ttf" if bold else "LiberationSans.ttf",
            "FreeSansBold.ttf" if bold else "FreeSans.ttf",
            "arial.ttf"
        ]
        for fn in font_names:
            try:
                return ImageFont.truetype(fn, size)
            except:
                pass
        return ImageFont.load_default()

    font_title = load_font(45, bold=True)
    font_name = load_font(55, bold=True)
    font_stats = load_font(28, bold=True) # Kichraytirildi, sig'ishi uchun
    font_sub = load_font(22, bold=False)

    # Aniq markazlashtirish funksiyasi
    def draw_centered(y, text, font, fill):
        try:
            bbox = draw.textbbox((0,0), text, font=font)
            w = bbox[2] - bbox[0]
        except:
            w = len(text) * (font.size * 0.6 if hasattr(font, 'size') else 15)
        draw.text(((800-w)/2, y), text, font=font, fill=fill)

    # 1. AVATARNI TILLA DOIRAGA JOYLASHTIRISH
    avatar_pasted = False
    if user_id:
        try:
            photos = await context.bot.get_user_profile_photos(user_id, limit=1)
            if photos.photos:
                file = await context.bot.get_file(photos.photos[0][-1].file_id)
                avatar_bytes = await file.download_as_bytearray()
                avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
                
                # O'lchamni tilla doiraga moslash (230x230)
                avatar_size = 230
                avatar = avatar.resize((avatar_size, avatar_size))
                
                mask = Image.new('L', (avatar_size, avatar_size), 0)
                draw_mask = ImageDraw.Draw(mask)
                draw_mask.ellipse((0, 0, avatar_size, avatar_size), fill=255)
                
                # X = (800 - 230) / 2 = 285. Y = 135 (Doira markaziga moslab)
                img.paste(avatar, (285, 135), mask)
                avatar_pasted = True
        except Exception as e:
            print(f"Avatar yuklashda xato: {e}")

    # 2. MATNLARNI JOYLASHTIRISH (Emojilarsiz, toza shriftda)
    # Y koordinatalari (500 dan 750 gacha bo'lgan bo'shliqda)
    
    draw_centered(480, "O Y   Q I R O L I", font_title, '#F3E37C') 
    
    # Ismni toza qilib yozamiz
    draw_centered(560, f"{username}", font_name, '#66FCF1') 
    
    stats_text = f"OCHKOLAR: {pts}   |   G'ALABALAR: {wins}   |   PPG: {ppg:.2f}"
    draw_centered(660, stats_text, font_stats, '#FFFFFF') 
    
    month_name = datetime.now().strftime('%m-%Y')
    draw_centered(730, f"FC Do'stlar Ligasi Yengilmas Chempioni • {month_name}", font_sub, '#C5C6C7') 

    # Rasmni xotiraga saqlash va yuborishga tayyorlash
    buf = io.BytesIO()
    img.convert('RGB').save(buf, format='JPEG', quality=95)
    buf.seek(0)
    return buf

# ==========================================
# 5. BUYRUQLAR VA FUNKSIYALAR
# ==========================================

async def get_gif_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == 'private':
        file_id = update.effective_message.animation.file_id
        await update.effective_message.reply_text(f"Bu GIF ning ID raqami:\n\n<code>{file_id}</code>", parse_mode='HTML')

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
        "📺 <code>/del ID</code> - Xatoni o'chirish\n"
        "🖼 <code>/testcert</code> - Sertifikat dizaynini ko'rish"
    )
    await update.effective_message.reply_text(text, parse_mode='HTML')

async def handle_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.effective_message.text
    if not text: return

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

        cursor.execute("INSERT OR REPLACE INTO users (username, user_id) VALUES (?, ?)", (my_raw, sender.id))
        conn.commit()

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
    valid_ppg = {k: v for k, v in stats.items() if v['games'] >= 3 and v['unique_opponents'] >= 2}
    sorted_ppg = sorted(valid_ppg.items(), key=lambda x: x[1]['true_ppg'], reverse=True)

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
        text += "📈 <b>2. HAQIQIY KOEFFITSIYENT (Sifat)</b>\n<i>(Kamida 2 xil raqibga qarshi)</i>\n<pre>"
        for idx, (player, s) in enumerate(sorted_ppg, 1):
            ppg = s['true_ppg']
            p_esc = html.escape(player).ljust(12)[:12]
            text += f"{idx}. {p_esc} | {ppg:.2f} PPG | ({s['unique_opponents']} raqib)\n"
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
    msg = f"📺 <b>VAR QARORI: Admin aralashdi!</b>\nID: {match_id} bo'lgan o'yin ({html.escape(row[0])} {row[2]}:{row[3]} {html.escape(row[1])}) o'chirildi!"
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
    text = (f"👤 <b>FUTBOLCHI DOSYESI: {html.escape(player_key)}</b>\n\n🏟 Jami o'yinlar: <b>{s['games']} ta</b>\n"
            f"✅ G'alaba: <b>{s['w']}</b> | 🤝 Durang: <b>{s['d']}</b> | ❌ Mag'lubiyat: <b>{s['l']}</b>\n"
            f"⚽️ To'plar nisbati: <b>{s['gf']} - {s['ga']}</b> (Farq: {gd})\n📊 Haqiqiy Koeffitsiyent: <b>{s['true_ppg']:.2f}</b>")
    await update.effective_message.reply_text(text, parse_mode='HTML')

async def h2h_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.effective_message.reply_text("Ikkita o'yinchini kiriting: <code>/h2h @men @ali</code>", parse_mode='HTML')
        return
    p1, p2 = context.args[0], context.args[1]
    cursor.execute('''SELECT p1, p2, p1_score, p2_score FROM matches WHERE (LOWER(p1) = LOWER(?) AND LOWER(p2) = LOWER(?)) OR (LOWER(p1) = LOWER(?) AND LOWER(p2) = LOWER(?))''', (p1, p2, p2, p1))
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

# TEST UCHUN MAXSUS BUYRUQ
async def test_cert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = f"@{update.effective_user.username}" if update.effective_user.username else update.effective_user.first_name
    
    pts = 45
    wins = 15
    ppg = 2.50

    try:
        cert_buf = await generate_certificate(context, user_id, username, pts, wins, ppg)
        await update.effective_message.reply_photo(photo=cert_buf, caption="🏆 Mana, Haqiqiy Oltin Sertifikat! 😎")
    except Exception as e:
        await update.effective_message.reply_text(f"Xatolik chiqdi: {e}")

# ==========================================
# 6. AVTOMATIK XABARLAR VA GRAFIKLAR
# ==========================================

async def send_meme(context, chat_id, meme_list, **kwargs):
    meme = random.choice(meme_list)
    text = meme["text"].format(**kwargs)
    try:
        await context.bot.send_animation(chat_id=chat_id, animation=meme["gif"], caption=text, parse_mode='HTML')
    except Exception as e:
        print(f"Meme xato: {e}")

async def daily_summary(context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("SELECT value FROM settings WHERE key='group_chat_id'")
    row = cursor.fetchone()
    if not row: return 
    chat_id = int(row[0])
    stats = get_stats_by_period(today_only=True)
    if not stats: return 
    sorted_pts = sorted(stats.items(), key=lambda x: (x[1]['pts'], x[1]['gf'] - x[1]['ga']), reverse=True)
    winner = html.escape(sorted_pts[0][0])
    w_pts = sorted_pts[0][1]['pts']
    loser = html.escape(sorted_pts[-1][0])
    reason = f"Eng ko'p ochko yig'gan holda: {w_pts} ochko"
    await send_meme(context, chat_id, DAILY_WINNER_MEMES, player=winner, reason=reason)
    if len(sorted_pts) > 1:
        await asyncio.sleep(60)
        await send_meme(context, chat_id, DAILY_LOSER_MEMES, player=loser)

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
    reason = f"Eng ko'p ochko yig'gan holda: {w_pts} ochko"
    await send_meme(context, chat_id, WEEKLY_WINNER_MEMES, player=winner, reason=reason)

async def weekly_analytics_chart(context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("SELECT value FROM settings WHERE key='group_chat_id'")
    row = cursor.fetchone()
    if not row: return 
    chat_id = int(row[0])

    tz_uz = timezone(timedelta(hours=5))
    now = datetime.now(tz_uz)
    curr_start = now - timedelta(days=7)
    prev_start = curr_start - timedelta(days=7)

    curr_stats = get_stats_by_date_range(curr_start, now)
    prev_stats = get_stats_by_date_range(prev_start, curr_start)

    if not curr_stats: return

    chart_buf = create_comparison_chart(curr_stats, prev_stats, "📊 HAFTALIK ANALITIKA (O'sish va Pasayish)")
    caption = "📈 <b>Haftalik Analitika Markazi:</b>\nKim o'sdi, kim quladi? Barchasi grafikda yaqqol ko'rinib turibdi! Yashillar - hurmatga loyiq, Qizillar - mashg'ulotni ko'paytiring!"
    
    try:
        await context.bot.send_photo(chat_id=chat_id, photo=chart_buf, caption=caption, parse_mode='HTML')
    except Exception as e:
        print(f"Haftalik grafik yuborishda xato: {e}")

async def monthly_analytics_chart(context: ContextTypes.DEFAULT_TYPE):
    tz_uz = timezone(timedelta(hours=5))
    now = datetime.now(tz_uz)
    
    if now.day != 1: return 

    cursor.execute("SELECT value FROM settings WHERE key='group_chat_id'")
    row = cursor.fetchone()
    if not row: return 
    chat_id = int(row[0])

    curr_end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    curr_start = (curr_end - timedelta(days=1)).replace(day=1)
    prev_end = curr_start
    prev_start = (prev_end - timedelta(days=1)).replace(day=1)

    curr_stats = get_stats_by_date_range(curr_start, curr_end)
    prev_stats = get_stats_by_date_range(prev_start, prev_end)

    if not curr_stats: return

    sorted_pts = sorted(curr_stats.items(), key=lambda x: (x[1]['pts'], x[1]['gf'] - x[1]['ga']), reverse=True)
    winner_username = sorted_pts[0][0]
    winner_data = sorted_pts[0][1]

    cursor.execute("SELECT user_id FROM users WHERE LOWER(username) = LOWER(?)", (winner_username,))
    user_row = cursor.fetchone()
    winner_id = user_row[0] if user_row else None

    try:
        cert_buf = await generate_certificate(
            context, winner_id, winner_username, 
            winner_data['pts'], winner_data['w'], winner_data['true_ppg']
        )
        cert_caption = f"🎉 <b>OY QIROLI ANIQLANDI!</b>\n\n{html.escape(winner_username)}, bu maxsus Oltin Sertifikat senga ataldi! O'z rasming bilan faxrlanib yuraver! 🏆😎"
        await context.bot.send_photo(chat_id=chat_id, photo=cert_buf, caption=cert_caption, parse_mode='HTML')
        await asyncio.sleep(60) 
    except Exception as e:
        print(f"Sertifikat yuborishda xato: {e}")

    chart_buf = create_comparison_chart(curr_stats, prev_stats, f"🏆 OYLIK SARHISOB ({curr_start.strftime('%B')})")
    caption = "🏆 <b>OYLIK YAKUNIY SARHISOB!</b>\n\nBir oy davomida kim qancha ter to'kdi? Kim o'tgan oyga nisbatan kuchaydi va kim reyting tubiga quladi? Barchasi shu grafikda!"
    
    try:
        await context.bot.send_photo(chat_id=chat_id, photo=chart_buf, caption=caption, parse_mode='HTML')
    except Exception as e:
        print(f"Oylik grafik yuborishda xato: {e}")

async def auto_announce(context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("SELECT value FROM settings WHERE key='group_chat_id'")
    row = cursor.fetchone()
    if not row: return 
    chat_id = int(row[0])
    stats = get_stats_by_period(days=7)
    if not stats or len(stats) < 2: return 
    sorted_pts = sorted(stats.items(), key=lambda x: (x[1]['pts'], x[1]['gf'] - x[1]['ga']), reverse=True)
    top_pts_player, top_pts = html.escape(sorted_pts[0][0]), sorted_pts[0][1]['pts']
    bottom_player, bottom_pts = html.escape(sorted_pts[-1][0]), sorted_pts[-1][1]['pts']
    valid_ppg = {k: v for k, v in stats.items() if v['games'] >= 3 and v['unique_opponents'] >= 2}
    top_ppg_player = html.escape(sorted(valid_ppg.items(), key=lambda x: x[1]['true_ppg'], reverse=True)[0][0]) if valid_ppg else None
    top_ppg = sorted(valid_ppg.items(), key=lambda x: x[1]['true_ppg'], reverse=True)[0][1]['true_ppg'] if valid_ppg else 0

    TOP_PTS_TEMPLATES = [
        {"text": f"👑 <b>\"Meni o'zingga tenglashtirma, kazo-kazolardanman men!\"</b>\n\n📊 {top_pts_player} {top_pts} ochko bilan hammadan tepada, qolganlar ta'zim qiling!", "gif": GIF_WIN_1},
        {"text": f"🕺 <b>\"To'y bolani o'zini o'yinga chorlaymiz!\"</b>\n\n📊 {top_pts_player} {top_pts} ochko bilan butun hafta maydonda yallo qildi!", "gif": GIF_WIN_2},
        {"text": f"😎 <b>\"Normalniy bollar bilan normalniy o'ynaymiz!\"</b>\n\n📊 {top_pts_player} {top_pts} ochko yig'ib, hammangni hurmatingni joyiga qo'ydi!", "gif": GIF_WIN_3}
    ]
    TOP_PPG_TEMPLATES = [
        {"text": f"🚜 <b>\"Yo'ldan qoch, qishloqilar!\"</b>\n\n📈 {top_ppg_player} {top_ppg:.2f} koeffitsiyent bilan hammadan sifatli o'ynayapti!", "gif": "CgACAgIAAxkBAAO8aoXamtCs_ekIJh7Dj7X1N7r0Z9UAAqeuAAJtRTBI4RGqc2Mp8Mk9BA"},
        {"text": f"🧠 <b>\"Muammo nimadaligini bilasanmi? Ularda reja yoʻq!\"</b>\n\n📈 {top_ppg_player} esa {top_ppg:.2f} koeffitsiyent bilan hammangni aql bilan yutyapti, o'rganinglar!", "gif": GIF_LOSE_10},
        {"text": f"🎩 <b>\"Sizlar faqat soniga ishlaysizlar, men sifatiga!\"</b>\n\n📈 {top_ppg_player} dan {top_ppg:.2f} koeffitsiyentlik haqiqiy master-klass!", "gif": GIF_WIN_3}
    ]
    BOTTOM_TEMPLATES = [
        {"text": f"🔫 <b>\"Otib tashlanglar buni!!!\"</b>\n\n📉 {bottom_player} atigi {bottom_pts} ochko bilan reyting tubida yotibdi...", "gif": "CgACAgIAAxkBAAPAaoXa4BGj3cO2B5AwUDDJgOCSvOkAAqquAAJtRTBIcHwysyjc8y89BA"},
        {"text": f"🤦‍♂️ <b>\"E, yashamargur, shuyam o'yin bo'ldimi?!\"</b>\n\n📉 {bottom_player} atigi {bottom_pts} ochko yig'ibdi. Uyalsang bo'lmaydimi?", "gif": GIF_LOSE_1},
        {"text": f"😭 <b>\"Dada, man o'ynamayman!\"</b>\n\n📉 {bottom_player} {bottom_pts} ochko bilan burchakda yig'lab o'tiribdi.", "gif": GIF_LOSE_6},
        {"text": f"♟ <b>\"Aka, bu oʻyin sizniki emas ekan, shaxmatga oʻting...\"</b>\n\n📉 {bottom_player}, {bottom_pts} ochko bilan nima qilib yuribsiz bu yerda?", "gif": GIF_LOSE_11},
        {"text": f"⛰ <b>\"Aytudim-a shu tepalikka chiqmaylik deb!\"</b>\n\n📉 {bottom_player} kuchlilar orasiga qo'shilib qolib, qattiq pushaymon bo'lyapti ({bottom_pts} ochko).", "gif": GIF_LOSE_10},
        {"text": f"🐢 <b>\"Kim edigu, kim bo'ldik!\"</b>\n\n📉 {bottom_player} ning ahvoliga maymunlar yig'layapti ({bottom_pts} ochko).", "gif": GIF_LOSE_4},
        {"text": f"📉 <b>\"Uka, bu sening darajang emas...\"</b>\n\n📉 {bottom_player} kattalar o'yiniga adashib kirib qolibdi ({bottom_pts} ochko).", "gif": GIF_LOSE_9}
    ]

    try:
        pts_choice = random.choice(TOP_PTS_TEMPLATES)
        await context.bot.send_animation(chat_id=chat_id, animation=pts_choice["gif"], caption=pts_choice["text"], parse_mode='HTML')
        if top_ppg_player:
            await asyncio.sleep(60) 
            ppg_choice = random.choice(TOP_PPG_TEMPLATES)
            await context.bot.send_animation(chat_id=chat_id, animation=ppg_choice["gif"], caption=ppg_choice["text"], parse_mode='HTML')
        await asyncio.sleep(60) 
        bot_choice = random.choice(BOTTOM_TEMPLATES)
        await context.bot.send_animation(chat_id=chat_id, animation=bot_choice["gif"], caption=bot_choice["text"], parse_mode='HTML')
    except Exception as e: print(f"Hafta o'rtasi xato: {e}")

async def daily_provocation(context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("SELECT value FROM settings WHERE key='group_chat_id'")
    row = cursor.fetchone()
    if not row: return 
    chat_id = int(row[0])
    stats = get_stats_by_period(days=3)
    if stats and len(stats) >= 2:
        sorted_pts = sorted(stats.items(), key=lambda x: (x[1]['pts'], x[1]['gf'] - x[1]['ga']), reverse=True)
        top1, bottom = html.escape(sorted_pts[0][0]), html.escape(sorted_pts[-1][0])
        TEXT_TEMPLATES = [
            f"🔥 Oxirgi 3 kunda {top1} quturib ketdi! Kimdir buni to'xtatadimi?\n{bottom}, sen umuman aralashma, borib choy damla!",
            f"🗣 Eshitishimcha, {top1} hammangni 'shogirdim' deyapti.\nAyniqsa {bottom}, sen qachon oxirgi marta yutganding o'zi?",
            f"🚑 {bottom} ni ahvoliga maymunlar yig'layapti.\n{top1} esa taxtda yallo qilyapti. Qani, bugun kim maydonga chiqadi?",
            f"🎮 {top1} oxirgi paytlar joystikni 'sindirib' tashlayapti.\n{bottom} masalan, faqat to'p olib kelib beryapti...",
            f"🤡 Reytingni qaranglar! {bottom} shunchaki 'ochko tarqatuvchi' xomiylik qilyapti.\n{top1} esa mazza qilib ochko yig'yapti.",
            f"⚔️ Qani, jangchilar! {top1} ni bugun kimdir yutib, 'popugini' pasaytirib qo'yadimi?\n{bottom} dan umid yo'q!",
            f"🤫 Hamma jim, oxirgi kunlar qiroli {top1} gapiryapti!\n{bottom}, sen gapirma, senga ruxsat yo'q!",
            f"🎯 {top1} nishonga aniq uryapti oxirgi payt.\n{bottom} esa o'z darvozasiga... Bugun kim kimgadir 'dars' beradimi?",
            f"🏆 {top1} o'zini 'Kibersport ustasi' deb e'lon qildi.\n{bottom}, sen indama, sen hali 'Beginner'san.",
            f"🔥 Oxirgi kunlardagi qonli janglarda {top1} tirik qoldi.\n{bottom} esa... uni eslashni ham xohlamayman."
        ]
        msg = random.choice(TEXT_TEMPLATES)
    else:
        msg = "😴 O'liklar! 3 kundan beri hech kim tuzukroq o'ynamadi! Joystiklar zanglab qoldimi?"

    PROVOCATION_GIFS = [
        "CgACAgIAAxkBAAPSaoXtV4ObWISdS22M5bnctKMhMp8AAu8uAALJZdhLxChEqBW77G49BA",
        "CgACAgIAAxkBAAPQaoXtECWaUNM94OLb5JgofX5kBK4AAlpDAAIBqoFJnwedkRUYrPw9BA",
        "CgACAgIAAxkBAAPMaoXszpxA2B4nwpAlUF5vyFxHoSMAAuaNAAJVUjhKnmpsH2xmho09BA",
        "CgACAgQAAxkBAAPKaoXsdFqMNM4xLwlBtZk8U7EEc84AAtkLAAJE7UlQ0YObLgABdEplPQQ",
        "CgACAgIAAxkBAAPXaoXwI3rSOzFAE4qks7wYU6W5GP0AAvggAAKNo_hIrUSBpx_YY809BA",
        "CgACAgQAAxkBAAPcaobl2D9Y4RFGne2d0Kf8t-NhQ6QAAiQDAAIjswRTK7vd7ugL1bs9BA",
        "CgACAgQAAxkBAAPeaobl2whD8vugn1TXg33gxjs6iUUAAtYEAAJ21kBRyvDUiyzY28o9BA",
        "CgACAgQAAxkBAAPgaobl3aoFfmQJWt2cX1TexEBo5skAAh4GAAIPjmRScbDwMX0EKRk9BA",
        "CgACAgIAAxkBAAPiaobl42APKuamkr1_dpIQW8ehbeIAAtp1AAKEyChIO11GXGkH0gc9BA",
        "CgACAgIAAxkBAAPkaobl7UG7o0mo8eb5ZqU1dIB1v3wAApgDAALn5VBKvEPRQpKYUSI9BA",
        "CgACAgIAAxkBAAPmaobmBol5Z8Jq3pLXX8aBbaZ890wAAtsQAAI-vUhImXLrj4Ay1kI9BA",
        "CgACAgQAAxkBAAPoaobmInjOh8CbCYBwpRGcRulx9XIAAmgKAAJ8FFBQBHFGEW6LfGY9BA",
        "CgACAgIAAxkBAAPqaobmR4iRbvxvDkTLwG-U_t_TszwAAjYUAAICY1BIjtZ4B_6ChG89BA",
        "CgACAgQAAxkBAAPsaobmYGR_YQGgczhjgkPGTxUBclMAAgEMAALi4kFQkP6QlJAC7TY9BA",
        "CgACAgIAAxkBAAPuaobnku9otow45p0dWzgPhxzjboEAAuMUAALpSUFIpL-poiovxyU9BA"
    ]
    try:
        await context.bot.send_animation(chat_id=chat_id, animation=random.choice(PROVOCATION_GIFS), caption=msg, parse_mode='HTML')
    except Exception as e: print(f"16:00 xato: {e}")

async def check_inactive_players(context: ContextTypes.DEFAULT_TYPE):
    cursor.execute("SELECT value FROM settings WHERE key='group_chat_id'")
    row = cursor.fetchone()
    if not row: return 
    chat_id = int(row[0])
    cursor.execute("SELECT p1, p2 FROM matches")
    all_players = set([p for match in cursor.fetchall() for p in match])
    start_utc = (datetime.utcnow() - timedelta(days=5)).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("SELECT p1, p2 FROM matches WHERE date >= ?", (start_utc,))
    active_players = set([p for match in cursor.fetchall() for p in match])
    inactive_players = all_players - active_players
    if inactive_players:
        mentions = ", ".join([html.escape(p) for p in inactive_players])
        msg = f"🤬 <b>\"Qayerlarda daydib yuribsan, guruhdan badarg‘a qilaymi? Kafangado bo‘lasan-ku!\"</b>\n\n{mentions} — 5 kundan beri maydonda ko'rinmaysizlar! Tirikmisizlar o'zi?"
        try:
            await context.bot.send_animation(chat_id=chat_id, animation="CgACAgIAAxkBAAO8aoXamtCs_ekIJh7Dj7X1N7r0Z9UAAqeuAAJtRTBI4RGqc2Mp8Mk9BA", caption=msg, parse_mode='HTML')
        except Exception as e: print(f"Inactive xato: {e}")

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
    app.add_handler(CommandHandler("testcert", test_cert))
    app.add_handler(MessageHandler(filters.ANIMATION, get_gif_id))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_match))

    tz_uz = timezone(timedelta(hours=5))
    
    app.job_queue.run_daily(daily_summary, time=time(hour=23, minute=0, tzinfo=tz_uz))
    app.job_queue.run_daily(weekly_summary, time=time(hour=20, minute=0, tzinfo=tz_uz), days=(6,))
    app.job_queue.run_daily(weekly_analytics_chart, time=time(hour=20, minute=1, tzinfo=tz_uz), days=(6,))
    app.job_queue.run_daily(monthly_analytics_chart, time=time(hour=12, minute=0, tzinfo=tz_uz))
    app.job_queue.run_daily(check_inactive_players, time=time(hour=15, minute=0, tzinfo=tz_uz))
    app.job_queue.run_daily(auto_announce, time=time(hour=17, minute=0, tzinfo=tz_uz), days=(3,))
    
    now = datetime.now(tz_uz)
    first_16 = now.replace(hour=16, minute=0, second=0, microsecond=0)
    if now > first_16: first_16 += timedelta(days=1)
    app.job_queue.run_repeating(daily_provocation, interval=timedelta(days=2), first=first_16)

    print("Bot ishga tushdi...")
    app.run_polling()

if __name__ == "__main__":
    main()

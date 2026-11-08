import time
import random
import sqlite3
import threading
import os
import telebot
from telebot.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, 
    ReplyKeyboardMarkup, KeyboardButton, LabeledPrice
)

TOKEN = "9150172701:AAFIZT8-MtcjLDVKWNGDZrJNwOvR3oVRWXI"

bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=4)

waiting_for_promo = set()
waiting_for_withdraw = set()
waiting_for_deposit = set()

GAMES = {
    "owocowy": {
        "name": "🍒 Owocowy Raj",
        "type": "slot",
        "chance": 28,
        "mult": 2,
        "bonus_chance": 12,
        "symbols": ["🍒", "🍋", "🍉", "🍇", "🔔"],
        "frame": "🍓══════════════🍓",
        "bonus_name": "🧺 Koszyk Obfitości",
        "bonus_desc": "Wybierz jeden z 3 koszyków! W każdym kryje się gwarantowana wygrana!",
        "bonus_buttons": ["🧺 Koszyk 1", "🧺 Koszyk 2", "🧺 Koszyk 3"],
        "desc": "Częste trafienia + Bonus Koszyków! (Wygrana: x2)"
    },
    "faraon": {
        "name": "🏺 Złoto Faraona",
        "type": "slot",
        "chance": 18,
        "mult": 3,
        "bonus_chance": 12,
        "symbols": ["🏺", "🪲", "👁️", "🐍", "☀️"],
        "frame": "🏜️══════════════🏜️",
        "bonus_name": "⚰️ Komnata Faraona",
        "bonus_desc": "Otwórz jeden z 3 starożytnych sarkofagów i odbierz złoto bez ryzyka!",
        "bonus_buttons": ["⚰️ Sarkofag 1", "⚰️ Sarkofag 2", "⚰️ Sarkofag 3"],
        "desc": "Egipskie skarby + Bonus Sarkofagów! (Wygrana: x3)"
    },
    "zeus": {
        "name": "⚡ Grom Zeusa",
        "type": "slot",
        "chance": 10,
        "mult": 6,
        "bonus_chance": 12,
        "symbols": ["⚡", "🏛️", "🦅", "🔱", "🏺"],
        "frame": "🌩️══════════════🌩️",
        "bonus_name": "🌩️ Gniew Olimpu",
        "bonus_desc": "Uderz piorunem w jedną z 3 chmur, aby zdobyć boski mnożnik!",
        "bonus_buttons": ["☁️ Chmura 1", "☁️ Chmura 2", "☁️ Chmura 3"],
        "desc": "Wysokie wygrane + Bonus Olimpu! (Wygrana: x6)"
    },
    "diament": {
        "name": "💎 Diamentowy Jackpot",
        "type": "slot",
        "chance": 4,
        "mult": 15,
        "bonus_chance": 12,
        "symbols": ["💎", "💍", "👑", "💵", "🏦"],
        "frame": "💎══════════════💎",
        "bonus_name": "🔐 Skarbiec Miliardera",
        "bonus_desc": "Włam się do jednego z 3 złotych sejfów po ogromną gotówkę!",
        "bonus_buttons": ["🔐 Sejf 1", "🔐 Sejf 2", "🔐 Sejf 3"],
        "desc": "Gigantyczny mnożnik + Bonus Sejfów! (Wygrana: x15)"
    },
    "blackjack": {
        "name": "🃏 Blackjack (Oczko)",
        "type": "table",
        "desc": "Graj z krupierem do 21 punktów! (Wygrana: x2)"
    },
    "roulette": {
        "name": "🎡 Europejska Ruletka",
        "type": "table",
        "desc": "Obstawiaj kolory (x2) lub konkretną liczbę (x36)!"
    }
}

db_lock = threading.Lock()
conn = sqlite3.connect("casino.db", check_same_thread=False)
conn.execute("PRAGMA journal_mode=WAL;")
conn.execute("PRAGMA synchronous=NORMAL;")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY, 
    balance INTEGER DEFAULT 0, 
    current_bet INTEGER DEFAULT 50,
    free_spins INTEGER DEFAULT 0,
    bonus_activated INTEGER DEFAULT 0,
    current_game TEXT DEFAULT 'owocowy',
    pending_bonus INTEGER DEFAULT 0
)
""")

for col_sql in [
    "ALTER TABLE users ADD COLUMN current_game TEXT DEFAULT 'owocowy'",
    "ALTER TABLE users ADD COLUMN pending_bonus INTEGER DEFAULT 0"
]:
    try:
        cursor.execute(col_sql)
    except sqlite3.OperationalError:
        pass

cursor.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS custom_promos (
    code TEXT PRIMARY KEY,
    reward_type TEXT,
    amount INTEGER,
    max_uses INTEGER,
    used_count INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS used_promos (
    user_id INTEGER,
    code TEXT,
    PRIMARY KEY (user_id, code)
)
""")
conn.commit()

def get_admin_id():
    with db_lock:
        cursor.execute("SELECT value FROM settings WHERE key = 'admin_id'")
        row = cursor.fetchone()
        return row[0] if row else None

def set_admin_id(user_id: int):
    with db_lock:
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('admin_id', ?)", (user_id,))
        conn.commit()

def is_admin(user_id: int) -> bool:
    return get_admin_id() == user_id

def get_user_data(user_id: int):
    with db_lock:
        cursor.execute("SELECT balance, current_bet, free_spins, bonus_activated, current_game, pending_bonus FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row is None:
            cursor.execute("INSERT INTO users (user_id, balance, current_bet, free_spins, bonus_activated, current_game, pending_bonus) VALUES (?, 0, 50, 0, 0, 'owocowy', 0)", (user_id,))
            conn.commit()
            return 0, 50, 0, 0, "owocowy", 0
        game = row[4] if row[4] in GAMES else "owocowy"
        return row[0], row[1], row[2], row[3], game, row[5]

def update_balance(user_id: int, amount: int):
    get_user_data(user_id)
    with db_lock:
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()

def set_user_bet(user_id: int, bet: int):
    with db_lock:
        cursor.execute("UPDATE users SET current_bet = ? WHERE user_id = ?", (bet, user_id))
        conn.commit()

def set_user_game(user_id: int, game_id: str):
    with db_lock:
        cursor.execute("UPDATE users SET current_game = ? WHERE user_id = ?", (game_id, user_id))
        conn.commit()

def set_pending_bonus(user_id: int, state: int):
    with db_lock:
        cursor.execute("UPDATE users SET pending_bonus = ? WHERE user_id = ?", (state, user_id))
        conn.commit()

def update_free_spins(user_id: int, amount: int):
    get_user_data(user_id)
    with db_lock:
        cursor.execute("UPDATE users SET free_spins = free_spins + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()

def activate_welcome_promo(user_id: int):
    with db_lock:
        cursor.execute("UPDATE users SET bonus_activated = 1 WHERE user_id = ?", (user_id,))
        conn.commit()

def get_bottom_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, is_persistent=True)
    kb.add(KeyboardButton("🎰 OTWÓRZ PANEL KASYNA"))
    return kb

def get_panel_text(user_id: int, balance: int, bet: int, free_spins: int, game_id: str):
    game = GAMES.get(game_id, GAMES["owocowy"])
    admin_badge = " 👑 *(ADMIN)*" if is_admin(user_id) else ""
    pln_value = balance / 100.0
    return (
        f"🎰 *PANEL GŁÓWNY KASYNA*{admin_badge} 🎰\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🕹 Wybrana gra: *{game['name']}*\n"
        f"ℹ️ _{game['desc']}_\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Saldo: *{balance}* monet (~{pln_value:.2f} zł)\n"
        f"🎲 Stawka: *{bet}* monet | 🎁 Spiny: *{free_spins}*\n"
        f"🆔 Twoje ID: `{user_id}`\n\n"
        f"👇 *Wybierz opcję poniżej:*"
    )

def get_menu(user_id: int, balance: int, bet: int, free_spins: int, game_id: str):
    game = GAMES.get(game_id, GAMES["owocowy"])
    if game["type"] == "slot":
        spin_text = f"🎰 GRAJ ({game['name']}) [Darmowe: {free_spins}]" if free_spins > 0 else f"🎰 GRAJ ({game['name']}) - {bet} monet"
    elif game_id == "blackjack":
        spin_text = f"🃏 ROZPOCZNIJ BLACKJACKA - {bet} monet"
    else:
        spin_text = f"🎡 OBŚCIEŻ RULETKĘ - {bet} monet"

    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton(text=spin_text, callback_data="play_main_game"))
    kb.row(
        InlineKeyboardButton(text="🕹 Wybierz Grę / Automat", callback_data="choose_game_menu"),
        InlineKeyboardButton(text="⚙️ Zmień Stawkę", callback_data="change_bet_menu")
    )
    kb.row(
        InlineKeyboardButton(text="💸 Wypłać środki (100 monet = 1 zł)", callback_data="withdraw_menu"),
        InlineKeyboardButton(text="🎟️ Wpisz kod", callback_data="enter_promo_menu")
    )
    kb.row(
        InlineKeyboardButton(text="🎁 Kod: 100darmowe", callback_data="activate_code"),
        InlineKeyboardButton(text="⭐ Doładuj konto (Stars)", callback_data="deposit_menu")
    )
    kb.row(InlineKeyboardButton(text=f"💰 Odśwież saldo ({balance} monet)", callback_data="check_balance"))
    if is_admin(user_id):
        kb.row(InlineKeyboardButton(text="👑 Panel Admina", callback_data="admin_menu"))
    return kb

def process_promo_code(user_id: int, code_raw: str):
    code = code_raw.strip().lower()
    balance, bet, free_spins, bonus_activated, game_id, _ = get_user_data(user_id)
    if code == "100darmowe":
        if bonus_activated == 1:
            return False, "❌ Kod `100darmowe` jest już aktywny! Doładuj konto za min. 250 Stars, aby odebrać 100 spinów."
        elif bonus_activated == 2:
            return False, "❌ Wykorzystałeś już kod powitalny `100darmowe`!"
        activate_welcome_promo(user_id)
        return True, "🎁 *Kod '100darmowe' został aktywowany!*\n\nKup teraz dowolny pakiet za **min. 250 Stars**, a system automatycznie dopisze Ci **100 darmowych spinów**!"

    with db_lock:
        cursor.execute("SELECT reward_type, amount, max_uses, used_count FROM custom_promos WHERE code = ?", (code,))
        promo = cursor.fetchone()
        if not promo:
            return False, f"❌ Kod promocyjny `{code}` nie istnieje!"
        r_type, amount, max_uses, used_count = promo
        if used_count >= max_uses:
            return False, f"❌ Limit użyć dla kodu `{code}` został wyczerpany!"
        cursor.execute("SELECT 1 FROM used_promos WHERE user_id = ? AND code = ?", (user_id, code))
        if cursor.fetchone():
            return False, f"❌ Już odebrałeś nagrodę z kodu `{code}`!"
        cursor.execute("INSERT INTO used_promos (user_id, code) VALUES (?, ?)", (user_id, code))
        cursor.execute("UPDATE custom_promos SET used_count = used_count + 1 WHERE code = ?", (code,))
        if r_type == "monety":
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
            nagroda_txt = f"*+{amount} monet* 💰"
        else:
            cursor.execute("UPDATE users SET free_spins = free_spins + ? WHERE user_id = ?", (amount, user_id))
            nagroda_txt = f"*+{amount} darmowych spinów* 🎰"
        conn.commit()
    return True, f"🎉 *Kod '{code}' zaakceptowany!*\nOtrzymujesz nagrodę: {nagroda_txt}!"

@bot.message_handler(commands=['zostanadminem'])
def cmd_become_admin(message):
    current_admin = get_admin_id()
    user_id = message.from_user.id
    if current_admin is None:
        set_admin_id(user_id)
        balance, bet, free_spins, _, game_id, _ = get_user_data(user_id)
        bot.send_message(message.chat.id, f"✅ *Zostałeś Administratorem bota!*\nTwoje ID (`{user_id}`) zapisano.", parse_mode="Markdown", reply_markup=get_menu(user_id, balance, bet, free_spins, game_id))
    elif current_admin == user_id:
        bot.send_message(message.chat.id, "👑 Już jesteś Administratorem!")
    else:
        bot.send_message(message.chat.id, "❌ Ten bot ma już właściciela!")

@bot.message_handler(commands=['daj'])
def cmd_give_money(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.send_message(message.chat.id, "❌ Brak uprawnień!")
        return
    parts = message.text.split()
    if len(parts) != 3:
        bot.send_message(message.chat.id, "ℹ️ Użycie: `/daj ID_GRACZA KWOTA`", parse_mode="Markdown")
        return
    try:
        target_id = int(parts[1])
        amount = int(parts[2])
    except ValueError:
        bot.send_message(message.chat.id, "❌ ID oraz kwota muszą być liczbami!")
        return
    update_balance(target_id, amount)
    target_bal, _, _, _, _, _ = get_user_data(target_id)
    bot.send_message(message.chat.id, f"✅ Dodano *{amount}* monet graczowi `{target_id}`!\nNowe saldo: *{target_bal}* monet.", parse_mode="Markdown")
    if target_id != user_id:
        try:
            bot.send_message(target_id, f"🎁 *Prezent od Administratora!*\nOtrzymujesz *+{amount}* monet!\n💰 Saldo: *{target_bal}* monet.", parse_mode="Markdown")
        except Exception:
            pass

@bot.message_handler(commands=['nowykod'])
def cmd_create_promo(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.send_message(message.chat.id, "❌ Brak uprawnień!")
        return
    parts = message.text.split()
    if len(parts) < 4:
        bot.send_message(message.chat.id, "🎟️ *Tworzenie kodu:*\n`/nowykod NAZWA monety/spiny ILOŚĆ LIMIT`", parse_mode="Markdown")
        return
    code = parts[1].strip().lower()
    r_type = parts[2].strip().lower()
    if r_type not in ("monety", "spiny"):
        bot.send_message(message.chat.id, "❌ Typ musi brzmieć `monety` lub `spiny`!")
        return
    try:
        amount = int(parts[3])
        max_uses = int(parts[4]) if len(parts) >= 5 else 100
    except ValueError:
        bot.send_message(message.chat.id, "❌ Liczby muszą być poprawne!")
        return
    with db_lock:
        cursor.execute("INSERT OR REPLACE INTO custom_promos (code, reward_type, amount, max_uses, used_count) VALUES (?, ?, ?, ?, 0)", (code, r_type, amount, max_uses))
        conn.commit()
    bot.send_message(message.chat.id, f"✅ Stworzono kod `{code}` na *{amount} ({r_type})* dla *{max_uses} osób*!", parse_mode="Markdown")

@bot.message_handler(commands=['start'])
@bot.message_handler(func=lambda message: True, content_types=['text'])
def handle_all_messages(message):
    user_id = message.from_user.id
    text = message.text.strip()

    if user_id in waiting_for_deposit and not text.startswith("/") and text != "🎰 OTWÓRZ PANEL KASYNA":
        waiting_for_deposit.discard(user_id)
        try:
            stars_count = int(text)
        except ValueError:
            bot.send_message(message.chat.id, "❌ Wpisz poprawną liczbę gwiazdek (np. `100` lub `500`).", parse_mode="Markdown")
            return
        if stars_count <= 0:
            bot.send_message(message.chat.id, "❌ Liczba gwiazdek musi być większa od 0!")
            return
        coins_count = stars_count * 10
        prices = [LabeledPrice(label=f"Doładowanie: {coins_count} monet", amount=stars_count)]
        bot.send_invoice(chat_id=user_id, title=f"Doładowanie: {coins_count} monet", description=f"Zakup {stars_count} Telegram Stars.", invoice_payload=f"coins_{coins_count}_{stars_count}", provider_token="", currency="XTR", prices=prices)
        return

    if user_id in waiting_for_withdraw and not text.startswith("/") and text != "🎰 OTWÓRZ PANEL KASYNA":
        waiting_for_withdraw.discard(user_id)
        balance, bet, free_spins, _, game_id, _ = get_user_data(user_id)
        try:
            parts = text.split(maxsplit=1)
            withdraw_amount = int(parts[0])
            payment_details = parts[1] if len(parts) > 1 else "Brak szczegółów"
        except ValueError:
            bot.send_message(message.chat.id, "❌ *Błędny format!* Wpisz najpierw liczbę monet, a po spacji dane do wypłaty.", parse_mode="Markdown")
            return
        if withdraw_amount <= 0:
            bot.send_message(message.chat.id, "❌ Kwota musi być większa od 0!")
            return
        if balance < withdraw_amount:
            bot.send_message(message.chat.id, f"❌ Nie masz tylu monet! Saldo: {balance}")
            return
        update_balance(user_id, -withdraw_amount)
        new_balance, _, _, _, _, _ = get_user_data(user_id)
        bot.send_message(message.chat.id, "Twoja wypłata została wysłana do potwierdzenia. Maksymalny termin wypłaty to 7 dni.", parse_mode="Markdown", reply_markup=get_menu(user_id, new_balance, bet, free_spins, game_id))
        admin_id = get_admin_id()
        if admin_id:
            try:
                pln_calc = withdraw_amount / 100.0
                bot.send_message(admin_id, f"🚨 *NOWE ZLECENIE WYPŁATY!* 🚨\n\n👤 Od: ID `{user_id}`\n💰 Kwota: *{withdraw_amount}* monet (~{pln_calc:.2f} zł)\n📱 Dane:\n`{payment_details}`", parse_mode="Markdown")
            except Exception:
                pass
        return

    if user_id in waiting_for_promo and not text.startswith("/") and text != "🎰 OTWÓRZ PANEL KASYNA":
        waiting_for_promo.discard(user_id)
        ok, msg_txt = process_promo_code(user_id, text)
        balance, bet, free_spins, _, game_id, _ = get_user_data(user_id)
        bot.send_message(message.chat.id, f"{msg_txt}\n\n" + get_panel_text(user_id, balance, bet, free_spins, game_id), parse_mode="Markdown", reply_markup=get_menu(user_id, balance, bet, free_spins, game_id))
        return

    waiting_for_promo.discard(user_id)
    waiting_for_withdraw.discard(user_id)
    waiting_for_deposit.discard(user_id)
    balance, bet, free_spins, _, game_id, _ = get_user_data(user_id)
    bot.send_message(message.chat.id, "🎰 *Panel Kasyna gotowy do gry:*", parse_mode="Markdown", reply_markup=get_bottom_keyboard())
    bot.send_message(message.chat.id, get_panel_text(user_id, balance, bet, free_spins, game_id), parse_mode="Markdown", reply_markup=get_menu(user_id, balance, bet, free_spins, game_id))

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    msg_id = call.message.message_id

    try:
        if call.data == "admin_menu":
            if not is_admin(user_id):
                bot.answer_callback_query(call.id, "❌ Brak uprawnień!", show_alert=True)
                return
            bot.answer_callback_query(call.id)
            kb = InlineKeyboardMarkup()
            kb.row(InlineKeyboardButton(text="➕ +1 000 monet", callback_data="adm_add_1000"), InlineKeyboardButton(text="➕ +10 000 monet", callback_data="adm_add_10000"))
            kb.row(InlineKeyboardButton(text="🔙 Powrót", callback_data="back_to_menu"))
            bot.edit_message_text("👑 *Panel Admina*\nUżywaj komend `/daj ID KWOTA` oraz `/nowykod`.", chat_id=chat_id, message_id=msg_id, parse_mode="Markdown", reply_markup=kb)

        elif call.data.startswith("adm_add_"):
            if not is_admin(user_id):
                return
            amount = int(call.data.split("_")[2])
            update_balance(user_id, amount)
            balance, _, _, _, _, _ = get_user_data(user_id)
            bot.answer_callback_query(call.id, f"✅ Dodano +{amount} monet! Saldo: {balance}", show_alert=True)

        elif call.data == "withdraw_menu":
            waiting_for_withdraw.add(user_id)
            bot.answer_callback_query(call.id)
            kb = InlineKeyboardMarkup()
            kb.row(InlineKeyboardButton(text="🔙 Anuluj", callback_data="back_to_menu"))
            bot.edit_message_text("💸 *WYPŁATA ŚRODKÓW*\n\n💱 *Przelicznik:* `100 monet = 1 zł`\n\nNapisz na czacie wiadomość w formacie:\n`KWOTA NUMER_KONTO_LUB_REVOLUT_BLIK`", chat_id=chat_id, message_id=msg_id, parse_mode="Markdown", reply_markup=kb)

        elif call.data == "enter_promo_menu":
            waiting_for_promo.add(user_id)
            bot.answer_callback_query(call.id)
            kb = InlineKeyboardMarkup()
            kb.row(InlineKeyboardButton(text="🔙 Anuluj", callback_data="back_to_menu"))
            bot.edit_message_text("🎟️ *Wpisz kod promocyjny* na czacie poniżej:", chat_id=chat_id, message_id=msg_id, parse_mode="Markdown", reply_markup=kb)

        elif call.data == "activate_code":
            ok, msg_txt = process_promo_code(user_id, "100darmowe")
            bot.answer_callback_query(call.id, "✅ OK" if ok else "❌ Info", show_alert=not ok)
            kb = InlineKeyboardMarkup()
            kb.row(InlineKeyboardButton(text="⭐ Doładuj konto (Bonus 100 spinów od 250 Stars)", callback_data="deposit_menu"))
            kb.row(InlineKeyboardButton(text="🔙 Powrót", callback_data="back_to_menu"))
            bot.edit_message_text(msg_txt, chat_id=chat_id, message_id=msg_id, parse_mode="Markdown", reply_markup=kb)

        elif call.data == "choose_game_menu":
            bot.answer_callback_query(call.id)
            kb = InlineKeyboardMarkup()
            for g_id, g_info in GAMES.items():
                kb.row(InlineKeyboardButton(text=f"{g_info['name']}", callback_data=f"setgame_{g_id}"))
            kb.row(InlineKeyboardButton(text="🔙 Powrót", callback_data="back_to_menu"))
            bot.edit_message_text("🕹 *WYBIERZ GRĘ LUB AUTOMAT:*", chat_id=chat_id, message_id=msg_id, parse_mode="Markdown", reply_markup=kb)

        elif call.data.startswith("setgame_"):
            game_id = call.data.split("_")[1]
            if game_id in GAMES:
                set_user_game(user_id, game_id)
                balance, bet, free_spins, _, game_id, _ = get_user_data(user_id)
                bot.answer_callback_query(call.id, f"Wybrano: {GAMES[game_id]['name']}!")
                bot.edit_message_text(get_panel_text(user_id, balance, bet, free_spins, game_id), chat_id=chat_id, message_id=msg_id, parse_mode="Markdown", reply_markup=get_menu(user_id, balance, bet, free_spins, game_id))

        elif call.data == "change_bet_menu":
            bot.answer_callback_query(call.id)
            kb = InlineKeyboardMarkup()
            kb.row(InlineKeyboardButton(text="10 monet", callback_data="setbet_10"), InlineKeyboardButton(text="50 monet", callback_data="setbet_50"), InlineKeyboardButton(text="100 monet", callback_data="setbet_100"))
            kb.row(InlineKeyboardButton(text="250 monet", callback_data="setbet_250"), InlineKeyboardButton(text="500 monet", callback_data="setbet_500"))
            kb.row(InlineKeyboardButton(text="🔙 Powrót", callback_data="back_to_menu"))
            bot.edit_message_text("⚙️ *Wybierz stawkę:*", chat_id=chat_id, message_id=msg_id, parse_mode="Markdown", reply_markup=kb)

        elif call.data.startswith("setbet_"):
            new_bet = int(call.data.split("_")[1])
            set_user_bet(user_id, new_bet)
            balance, bet, free_spins, _, game_id, _ = get_user_data(user_id)
            bot.answer_callback_query(call.id, f"Stawka: {new_bet}")
            bot.edit_message_text(get_panel_text(user_id, balance, bet, free_spins, game_id), chat_id=chat_id, message_id=msg_id, parse_mode="Markdown", reply_markup=get_menu(user_id, balance, bet, free_spins, game_id))

        elif call.data == "deposit_menu":
            bot.answer_callback_query(call.id)
            kb = InlineKeyboardMarkup()
            kb.row(InlineKeyboardButton(text="⭐ Wpisz własną ilość Stars", callback_data="custom_deposit"))
            kb.row(InlineKeyboardButton(text="⭐ 50 Stars ➔ 500 monet", callback_data="star_50_500"))
            kb.row(InlineKeyboardButton(text="🔥 250 Stars (Wymóg kodu 100darmowe!) ➔ 2500 monet", callback_data="star_250_2500"))
            kb.row(InlineKeyboardButton(text="🔙 Powrót", callback_data="back_to_menu"))
            bot.edit_message_text("⭐ *SKLEP DOŁADOWAŃ (TELEGRAM STARS)* ⭐\n\n💱 *Przelicznik:* `100 monet = 1 zł`", chat_id=chat_id, message_id=msg_id, parse_mode="Markdown", reply_markup=kb)

        elif call.data == "custom_deposit":
            waiting_for_deposit.add(user_id)
            bot.answer_callback_query(call.id)
            kb = InlineKeyboardMarkup()
            kb.row(InlineKeyboardButton(text="🔙 Anuluj", callback_data="back_to_menu"))
            bot.edit_message_text("⭐ *WŁASNA ILOŚĆ STARS*\n\nNapisz na czacie liczbę gwiazdek (Stars), jaką chcesz wpłacić (np. `100` lub `500`).", chat_id=chat_id, message_id=msg_id, parse_mode="Markdown", reply_markup=kb)

        elif call.data.startswith("star_"):
            bot.answer_callback_query(call.id)
            _, stars_str, coins_str = call.data.split("_")
            prices = [LabeledPrice(label=f"Pakiet {coins_str} monet", amount=int(stars_str))]
            bot.send_invoice(chat_id=user_id, title=f"Doładowanie: {coins_str} monet", description="Zakup monet w kasynie.", invoice_payload=f"coins_{coins_str}_{stars_str}", provider_token="", currency="XTR", prices=prices)

        elif call.data == "back_to_menu":
            waiting_for_promo.discard(user_id)
            waiting_for_withdraw.discard(user_id)
            waiting_for_deposit.discard(user_id)
            bot.answer_callback_query(call.id)
            balance, bet, free_spins, _, game_id, _ = get_user_data(user_id)
            bot.edit_message_text(get_panel_text(user_id, balance, bet, free_spins, game_id), chat_id=chat_id, message_id=msg_id, parse_mode="Markdown", reply_markup=get_menu(user_id, balance, bet, free_spins, game_id))

        elif call.data == "play_main_game":
            balance, bet, free_spins, _, game_id, _ = get_user_data(user_id)
            game = GAMES.get(game_id, GAMES["owocowy"])

            if game["type"] == "slot":
                if free_spins > 0:
                    update_free_spins(user_id, -1)
                    is_free_spin = True
                    bot.answer_callback_query(call.id, f"Darmowy spin! 🎰")
                else:
                    is_free_spin = False
                    if balance < bet:
                        bot.answer_callback_query(call.id, "❌ Za mało monet!", show_alert=True)
                        return
                    bot.answer_callback_query(call.id, "Kręcimy! 🎰")
                    update_balance(user_id, -bet)

                msg = bot.send_dice(chat_id, emoji="🎰")
                time.sleep(2.2)

                effective_bet = 50 if is_free_spin else bet
                roll = random.randint(1, 100)
                bonus_roll = random.randint(1, 100)
                syms = game["symbols"]

                if roll <= game["chance"]:
                    s = random.choice(syms)
                    reels = f"║  {s}  │  {s}  │  {s}  ║"
                    win = effective_bet * game["mult"]
                    update_balance(user_id, win)
                    wynik = f"🎉 *TRAFIONY!* Wygrana: *+{win}* monet (x{game['mult']})!"
                else:
                    s1, s2, s3 = random.sample(syms, 3)
                    reels = f"║  {s1}  │  {s2}  │  {s3}  ║"
                    wynik = f"📉 *Pusto.*"

                slot_visual = f"*{game['name']}*\n{game['frame']}\n`╔════════════════╗`\n`{reels}`\n`╚════════════════╝`\n{game['frame']}\n"

                if bonus_roll <= game["bonus_chance"]:
                    set_pending_bonus(user_id, effective_bet)
                    kb_bonus = InlineKeyboardMarkup()
                    for idx, b_text in enumerate(game["bonus_buttons"]):
                        kb_bonus.row(InlineKeyboardButton(text=b_text, callback_data=f"pickbonus_{idx}"))
                    bot.reply_to(msg, f"{slot_visual}\n{wynik}\n\n🚨 *DARMOWA GRA BONUSOWA!* 🎁 *{game['bonus_name']}*\nKliknij poniżej:", parse_mode="Markdown", reply_markup=kb_bonus)
                    return

                balance, bet, free_spins, _, game_id, _ = get_user_data(user_id)
                bot.reply_to(msg, f"{slot_visual}\n{wynik}\n\n" + get_panel_text(user_id, balance, bet, free_spins, game_id), parse_mode="Markdown", reply_markup=get_menu(user_id, balance, bet, free_spins, game_id))

            elif game_id == "blackjack":
                if balance < bet:
                    bot.answer_callback_query(call.id, "❌ Za mało monet na Blackjacka!", show_alert=True)
                    return
                update_balance(user_id, -bet)
                bot.answer_callback_query(call.id, "🃏 Rozdano karty!")
                p_card1, p_card2 = random.randint(2, 11), random.randint(2, 11)
                p_sum = p_card1 + p_card2
                d_card = random.randint(15, 21)
                kb_bj = InlineKeyboardMarkup()
                kb_bj.row(
                    InlineKeyboardButton(text="🃏 Dobierz (Hit)", callback_data=f"bj_hit_{p_sum}_{d_card}_{bet}"),
                    InlineKeyboardButton(text="🛑 Pasuj (Stand)", callback_data=f"bj_stand_{p_sum}_{d_card}_{bet}")
                )
                bot.send_message(chat_id, f"🃏 *BLACKJACK (OCZKO)*\n\nTwoje karty: **{p_card1}** i **{p_card2}** (Suma: **{p_sum}**)\nKarta krupiera: **{d_card - 5}** (?)", parse_mode="Markdown", reply_markup=kb_bj)

            elif game_id == "roulette":
                if balance < bet:
                    bot.answer_callback_query(call.id, "❌ Za mało monet na ruletkę!", show_alert=True)
                    return
                bot.answer_callback_query(call.id, "🎡 Wybierz zakład w ruletce!")
                kb_rl = InlineKeyboardMarkup()
                kb_rl.row(
                    InlineKeyboardButton(text="🔴 Czerwone (x2)", callback_data=f"rl_bet_red_{bet}"),
                    InlineKeyboardButton(text="⚫ Czarne (x2)", callback_data=f"rl_bet_black_{bet}")
                )
                kb_rl.row(InlineKeyboardButton(text="🟢 Zielone Zero (x36)", callback_data=f"rl_bet_zero_{bet}"))
                bot.send_message(chat_id, f"🎡 *EUROPEJSKA RULETKA*\nStawka: **{bet} monet**\nNa co stawiasz?", parse_mode="Markdown", reply_markup=kb_rl)

        elif call.data.startswith("bj_"):
            parts = call.data.split("_")
            action = parts[1]
            p_sum = int(parts[2])
            d_card = int(parts[3])
            bet_amt = int(parts[4])

            if action == "hit":
                new_card = random.randint(2, 10)
                p_sum += new_card
                if p_sum > 21:
                    balance, bet, free_spins, _, game_id, _ = get_user_data(user_id)
                    bot.answer_callback_query(call.id, "💥 Przekroczono 21!", show_alert=True)
                    bot.edit_message_text(f"🃏 *BLACKJACK - PRZEGRANA*\nDobrałeś `{new_card}`. Suma: **{p_sum}**.\n📉 Straciłeś **{bet_amt}** monet.\n\n" + get_panel_text(user_id, balance, bet, free_spins, game_id), chat_id=chat_id, message_id=msg_id, parse_mode="Markdown", reply_markup=get_menu(user_id, balance, bet, free_spins, game_id))
                else:
                    bot.answer_callback_query(call.id, f"Dociągnąłeś {new_card}!")
                    kb_bj = InlineKeyboardMarkup()
                    kb_bj.row(InlineKeyboardButton(text="🃏 Dobierz", callback_data=f"bj_hit_{p_sum}_{d_card}_{bet_amt}"), InlineKeyboardButton(text="🛑 Pasuj", callback_data=f"bj_stand_{p_sum}_{d_card}_{bet_amt}"))
                    bot.edit_message_text(f"🃏 *BLACKJACK*\nSuma: **{p_sum}**", chat_id=chat_id, message_id=msg_id, parse_mode="Markdown", reply_markup=kb_bj)
            elif action == "stand":
                bot.answer_callback_query(call.id, "Sprawdzamy krupiera!")
                dealer_score = d_card
                win_amount = bet_amt * 2
                if p_sum > dealer_score or dealer_score > 21:
                    update_balance(user_id, win_amount)
                    result_txt = f"🎉 *WYGRANA!* Krupier miał {dealer_score}. Zyskujesz **+{win_amount}** monet!"
                elif p_sum == dealer_score:
                    update_balance(user_id, bet_amt)
                    result_txt = f"🤝 *REMIS!* Krupier miał {dealer_score}."
                else:
                    result_txt = f"📉 *PRZEGRANA!* Krupier miał {dealer_score}."
                balance, bet, free_spins, _, game_id, _ = get_user_data(user_id)
                bot.edit_message_text(f"🃏 *WYNIK BLACKJACKA*\n\n{result_txt}\n\n" + get_panel_text(user_id, balance, bet, free_spins, game_id), chat_id=chat_id, message_id=msg_id, parse_mode="Markdown", reply_markup=get_menu(user_id, balance, bet, free_spins, game_id))

        elif call.data.startswith("rl_bet_"):
            parts = call.data.split("_")
            choice = parts[2]
            bet_amt = int(parts[3])
            bot.answer_callback_query(call.id, "🎡 Kula wiruje...")
            time.sleep(1.2)
            winning_num = random.randint(0, 36)
            winning_color = "green" if winning_num == 0 else ("red" if winning_num in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36] else "black")
            won = False
            win_amt = 0
            if choice == "red" and winning_color == "red":
                won, win_amt = True, bet_amt * 2
            elif choice == "black" and winning_color == "black":
                won, win_amt = True, bet_amt * 2
            elif choice == "zero" and winning_color == "green":
                won, win_amt = True, bet_amt * 36
            if won:
                update_balance(user_id, win_amt)
                res_msg = f"🎉 Wypadło **{winning_num} ({winning_color.upper()})**.\nWygrywasz **+{win_amt}** monet!"
            else:
                res_msg = f"📉 Wypadło **{winning_num} ({winning_color.upper()})**."
            balance, bet, free_spins, _, game_id, _ = get_user_data(user_id)
            bot.edit_message_text(f"🎡 *WYNIK RULETKI*\n\n{res_msg}\n\n" + get_panel_text(user_id, balance, bet, free_spins, game_id), chat_id=chat_id, message_id=msg_id, parse_mode="Markdown", reply_markup=get_menu(user_id, balance, bet, free_spins, game_id))

        elif call.data.startswith("pickbonus_"):
            balance, bet, free_spins, _, game_id, pending_bonus_bet = get_user_data(user_id)
            if pending_bonus_bet <= 0:
                bot.answer_callback_query(call.id, "❌ Bonus odebrany!", show_alert=True)
                return
            set_pending_bonus(user_id, 0)
            game = GAMES.get(game_id, GAMES["owocowy"])
            bonus_mult = random.choice([2, 3, 5, 8, 10, 15])
            bonus_win = pending_bonus_bet * bonus_mult
            update_balance(user_id, bonus_win)
            balance, bet, free_spins, _, game_id, _ = get_user_data(user_id)
            bot.answer_callback_query(call.id, f"🎉 Wygrana bonusowa: +{bonus_win}!", show_alert=True)
            bot.edit_message_text(f"🎊 *WYNIK BONUSU: {game['bonus_name']}* 🎊\nMnożnik **x{bonus_mult}**!\nWygrywasz: **+{bonus_win} monet**!\n\n" + get_panel_text(user_id, balance, bet, free_spins, game_id), chat_id=chat_id, message_id=msg_id, parse_mode="Markdown", reply_markup=get_menu(user_id, balance, bet, free_spins, game_id))

        elif call.data == "check_balance":
            balance, bet, free_spins, _, game_id, _ = get_user_data(user_id)
            pln_val = balance / 100.0
            bot.answer_callback_query(call.id, f"💰 Saldo: {balance} monet (~{pln_val:.2f} zł)", show_alert=True)
            bot.edit_message_text(get_panel_text(user_id, balance, bet, free_spins, game_id), chat_id=chat_id, message_id=msg_id, parse_mode="Markdown", reply_markup=get_menu(user_id, balance, bet, free_spins, game_id))

    except Exception:
        pass

@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def got_payment(message):
    payload_parts = message.successful_payment.invoice_payload.split("_")
    coins, stars = int(payload_parts[1]), int(payload_parts[2])
    user_id = message.from_user.id
    update_balance(user_id, coins)
    balance, bet, free_spins, bonus_activated, game_id, _ = get_user_data(user_id)
    bonus_msg = ""
    if bonus_activated == 1 and stars >= 250:
        update_free_spins(user_id, 100)
        with db_lock:
            cursor.execute("UPDATE users SET bonus_activated = 2 WHERE user_id = ?", (user_id,))
            conn.commit()
        bonus_msg = "\n🎁 *Kod '100darmowe' zrealizowany!* Dodano **+100 darmowych spinów**!"
    balance, bet, free_spins, _, game_id, _ = get_user_data(user_id)
    bot.send_message(message.chat.id, f"🎉 *Płatność udana!* Dodano *+{coins}* monet.{bonus_msg}\n\n" + get_panel_text(user_id, balance, bet, free_spins, game_id), parse_mode="Markdown", reply_markup=get_menu(user_id, balance, bet, free_spins, game_id))

try:
    bot.set_my_commands([telebot.types.BotCommand("/start", "🎰 Otwórz Panel Kasyna")])
except Exception:
    pass

print(">>> BOT KASYNO WEB CLOUD URUCHOMIONY! <<<")
bot.remove_webhook()
bot.infinity_polling(timeout=10, long_polling_timeout=5, allowed_updates=["message", "callback_query", "pre_checkout_query", "chat_member", "my_chat_member"])

import os
import random
import sqlite3
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import telebot
from telebot import types

# --- WBUDOWANY SERWER HTTP (Dla Render.com 24/7) ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Bot Kasyno dziala 24/7!".encode("utf-8"))

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    print(f"Serwer HTTP uruchomiony na porcie {port}")
    server.serve_forever()

# Uruchomienie serwera w tle
threading.Thread(target=run_web_server, daemon=True).start()

# --- KONFIGURACJA BOTA ---
TOKEN = os.environ.get("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=4)

# --- BAZA DANYCH ---
db_lock = threading.Lock()
conn = sqlite3.connect("casino.db", check_same_thread=False)
cursor = conn.cursor()

# Tworzenie tabel
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY, 
    balance INTEGER DEFAULT 0, 
    current_bet INTEGER DEFAULT 50,
    free_spins INTEGER DEFAULT 0,
    bonus_activated INTEGER DEFAULT 0,
    current_game TEXT DEFAULT 'owocowy',
    pending_bonus INTEGER DEFAULT 0,
    pending_promo TEXT DEFAULT ''
)
""")

for col_sql in [
    "ALTER TABLE users ADD COLUMN current_game TEXT DEFAULT 'owocowy'",
    "ALTER TABLE users ADD COLUMN pending_bonus INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN pending_promo TEXT DEFAULT ''"
]:
    try:
        cursor.execute(col_sql)
    except sqlite3.OperationalError:
        pass

cursor.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY, 
    value TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS custom_promos (
    code TEXT PRIMARY KEY,
    reward_type TEXT,
    amount INTEGER,
    max_uses INTEGER,
    used_count INTEGER DEFAULT 0,
    min_deposit INTEGER DEFAULT 0
)
""")

try:
    cursor.execute("ALTER TABLE custom_promos ADD COLUMN min_deposit INTEGER DEFAULT 0")
except sqlite3.OperationalError:
    pass

cursor.execute("""
CREATE TABLE IF NOT EXISTS used_promos (
    user_id INTEGER,
    code TEXT,
    PRIMARY KEY(user_id, code)
)
""")
conn.commit()

# --- SŁOWNIK GIER ---
GAMES = {
    "owocowy": {
        "name": "🍒 Owocowy Raj",
        "type": "slot",
        "chance": 28,
        "symbols": ["🍒", "🍋", "🍊", "🍉", "🍇", "⭐", "🔔"],
        "frame": "🍒 🍋 🍊"
    },
    "zeus": {
        "name": "⚡ Grom Zeusa",
        "type": "slot",
        "chance": 26,
        "symbols": ["⚡", "🏛️", "🏺", "🦅", "🔥", "💎", "👑"],
        "frame": "⚡ 🏛️ 🏺"
    },
    "faraon": {
        "name": "🏺 Złoto Faraona",
        "type": "slot",
        "chance": 27,
        "symbols": ["🏺", "🐍", "👁️", "🐪", "🌴", "👑", "💰"],
        "frame": "🏺 🐍 👁️"
    },
    "jackpot": {
        "name": "💎 Diamentowy Jackpot",
        "type": "slot",
        "chance": 24,
        "symbols": ["💎", "💰", "7️⃣", "👑", "⭐", "🍀", "💎"],
        "frame": "💎 💰 7️⃣"
    },
    "blackjack": {
        "name": "🃏 Blackjack (Oczko)",
        "type": "blackjack",
        "chance": 45,
        "symbols": [],
        "frame": "🃏 Krupier vs Gracz"
    },
    "ruletka": {
        "name": "🎡 Europejska Ruletka",
        "type": "ruletka",
        "chance": 48,
        "symbols": [],
        "frame": "🔴 0 🟢 ⚫"
    }
}

# --- FUNKCJE POMOCNICZE ---
def is_admin(user_id: int):
    with db_lock:
        cursor.execute("SELECT value FROM settings WHERE key = 'admin_id'")
        row = cursor.fetchone()
        if not row:
            return False
        return int(row[0]) == user_id

def get_user_data(user_id: int):
    with db_lock:
        cursor.execute("SELECT balance, current_bet, free_spins, bonus_activated, current_game, pending_bonus, pending_promo FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row is None:
            cursor.execute("INSERT INTO users (user_id, balance, current_bet, free_spins, bonus_activated, current_game, pending_bonus, pending_promo) VALUES (?, 0, 50, 0, 0, 'owocowy', 0, '')", (user_id,))
            conn.commit()
            return 0, 50, 0, 0, "owocowy", 0, ""
        game = row[4] if row[4] in GAMES else "owocowy"
        pending_promo = row[6] if len(row) > 6 and row[6] else ""
        return row[0], row[1], row[2], row[3], game, row[5], pending_promo

def update_balance(user_id: int, amount: int):
    with db_lock:
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()

def update_free_spins(user_id: int, amount: int):
    with db_lock:
        cursor.execute("UPDATE users SET free_spins = free_spins + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()

def activate_welcome_promo(user_id: int):
    with db_lock:
        cursor.execute("UPDATE users SET bonus_activated = 1 WHERE user_id = ?", (user_id,))
        conn.commit()

def get_panel_text(user_id: int, balance: int, bet: int, free_spins: int, game_id: int):
    game_info = GAMES.get(game_id, GAMES["owocowy"])
    pln = balance / 100.0
    admin_status = "👑 [ADMIN]" if is_admin(user_id) else ""
    return (
        f"🎰 *PANEL GŁÓWNY KASYNA* {admin_status}\n\n"
        f"🎮 Wybrana gra: *{game_info['name']}*\n"
        f"💰 Saldo: **{balance} monet** (`~{pln:.2f} zł`)\n"
        f"🎲 Stawka: **{bet} monet** | 🎁 Spiny: **{free_spins}**\n\n"
        f"🆔 Twoje ID: `{user_id}`\n\n"
        f"👇 Wybierz opcję poniżej:"
    )

def get_menu(user_id: int, balance: int, bet: int, free_spins: int, game_id: int):
    markup = types.InlineKeyboardMarkup(row_width=2)
    game_info = GAMES.get(game_id, GAMES["owocowy"])
    
    markup.add(types.InlineKeyboardButton(f"🎰 GRAJ ({game_info['frame']}) - {bet} monet", callback_data="play_spin"))
    markup.add(
        types.InlineKeyboardButton("🕹️ Wybierz Grę / Tryb", callback_data="choose_game"),
        types.InlineKeyboardButton("⚙️ Zmień Stawkę", callback_data="change_bet")
    )
    markup.add(
        types.InlineKeyboardButton("💸 Wypłacać środki...", callback_data="withdraw_menu"),
        types.InlineKeyboardButton("🎟️ Wpisz kod", callback_data="enter_promo")
    )
    markup.add(
        types.InlineKeyboardButton("🎁 Kod: 100darmowe", callback_data="promo_100darmowe"),
        types.InlineKeyboardButton("⭐ Doładuj konto...", callback_data="deposit_menu")
    )
    markup.add(types.InlineKeyboardButton(f"🔄 Odśwież saldo ({balance} monet)", callback_data="refresh_main"))
    
    if is_admin(user_id):
        markup.add(types.InlineKeyboardButton("👑 Panel Admina", callback_data="admin_panel"))
        
    return markup

# --- KOMENDY BOTA ---
@bot.message_handler(commands=['start'])
def cmd_start(message):
    user_id = message.from_user.id
    balance, bet, free_spins, bonus_activated, game_id, _, _ = get_user_data(user_id)
    bot.send_message(
        message.chat.id,
        get_panel_text(user_id, balance, bet, free_spins, game_id),
        parse_mode="Markdown",
        reply_markup=get_menu(user_id, balance, bet, free_spins, game_id)
    )

@bot.message_handler(commands=['zostanadminem'])
def cmd_zostanadminem(message):
    user_id = message.from_user.id
    with db_lock:
        cursor.execute("SELECT value FROM settings WHERE key = 'admin_id'")
        row = cursor.fetchone()
        if not row:
            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('admin_id', ?)", (str(user_id),))
            conn.commit()
            bot.send_message(message.chat.id, "👑 Zostałeś pomyślnie ustawiony jako główny administrator bota!")
        else:
            if int(row[0]) == user_id:
                bot.send_message(message.chat.id, "ℹ️ Już jesteś administratorem.")
            else:
                bot.send_message(message.chat.id, "❌ Administrator jest już przypisany do innego konta!")
    balance, bet, free_spins, bonus_activated, game_id, _, _ = get_user_data(user_id)
    bot.send_message(
        message.chat.id,
        get_panel_text(user_id, balance, bet, free_spins, game_id),
        parse_mode="Markdown",
        reply_markup=get_menu(user_id, balance, bet, free_spins, game_id)
    )

@bot.message_handler(commands=['nowykod'])
def cmd_create_promo(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.send_message(message.chat.id, "❌ Brak uprawnień!")
        return
    parts = message.text.split()
    if len(parts) < 4:
        bot.send_message(message.chat.id, "🎟️ *Tworzenie kodu:*\n`/nowykod NAZWA monety/spiny ILOŚĆ LIMIT [MIN_DEPOZYT_STARS]`", parse_mode="Markdown")
        return
    code = parts[1].strip().lower()
    r_type = parts[2].strip().lower()
    if r_type not in ("monety", "spiny"):
        bot.send_message(message.chat.id, "❌ Typ musi brzmieć `monety` lub `spiny`!")
        return
    try:
        amount = int(parts[3])
        max_uses = int(parts[4]) if len(parts) >= 5 else 100
        min_deposit = int(parts[5]) if len(parts) >= 6 else 0
    except ValueError:
        bot.send_message(message.chat.id, "❌ Liczby muszą być poprawne!")
        return
    with db_lock:
        cursor.execute("INSERT OR REPLACE INTO custom_promos (code, reward_type, amount, max_uses, used_count, min_deposit) VALUES (?, ?, ?, ?, 0, ?)", (code, r_type, amount, max_uses, min_deposit))
        conn.commit()
    dep_txt = f" (Wymóg wpłaty: min. {min_deposit} Stars)" if min_deposit > 0 else ""
    bot.send_message(message.chat.id, f"✅ Stworzono kod `{code}` na *{amount} ({r_type})* dla *{max_uses} osób*{dep_txt}!", parse_mode="Markdown")

def process_promo_code(user_id: int, code_raw: str):
    code = code_raw.strip().lower()
    balance, bet, free_spins, bonus_activated, game_id, _, _ = get_user_data(user_id)
    if code == "100darmowe":
        if bonus_activated == 1:
            return False, "❌ Kod `100darmowe` jest już aktywny! Doładuj konto za min. 250 Stars, aby odebrać 100 spinów."
        elif bonus_activated == 2:
            return False, "❌ Wykorzystałeś już kod powitalny `100darmowe`!"
        activate_welcome_promo(user_id)
        return True, "🎁 *Kod '100darmowe' został aktywowany!*\n\nKup teraz dowolny pakiet za **min. 250 Stars**, a system automatycznie dopisze Ci **100 darmowych spinów**!"

    with db_lock:
        cursor.execute("SELECT reward_type, amount, max_uses, used_count, min_deposit FROM custom_promos WHERE code = ?", (code,))
        promo = cursor.fetchone()
        if not promo:
            return False, f"❌ Kod promocyjny `{code}` nie istnieje!"
        r_type, amount, max_uses, used_count, min_deposit = promo
        if used_count >= max_uses:
            return False, f"❌ Limit użyć dla kodu `{code}` został wyczerpany!"
        cursor.execute("SELECT 1 FROM used_promos WHERE user_id = ? AND code = ?", (user_id, code))
        if cursor.fetchone():
            return False, f"❌ Już odebrałeś nagrodę z kodu `{code}`!"
        
        if min_deposit > 0:
            cursor.execute("UPDATE users SET pending_promo = ? WHERE user_id = ?", (code, user_id))
            conn.commit()
            return True, f"🎟️ *Kod '{code}' zapisany!* Ten kod wymaga doładowania za **min. {min_deposit} Stars**.\n\nDoładuj konto przez sklep, a nagroda (*+{amount} {r_type}*) zostanie przyznana automatycznie!"

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

# --- OBSŁUGA PŁATNOŚCI STARS ---
@bot.message_handler(content_types=['successful_payment'])
def got_payment(message):
    payload_parts = message.successful_payment.invoice_payload.split("_")
    coins, stars = int(payload_parts[1]), int(payload_parts[2])
    user_id = message.from_user.id
    update_balance(user_id, coins)
    
    balance, bet, free_spins, bonus_activated, game_id, _, pending_promo = get_user_data(user_id)
    bonus_msg = ""
    
    if bonus_activated == 1 and stars >= 250:
        update_free_spins(user_id, 100)
        with db_lock:
            cursor.execute("UPDATE users SET bonus_activated = 2 WHERE user_id = ?", (user_id,))
            conn.commit()
        bonus_msg += "\n🎁 *Kod '100darmowe' zrealizowany!* Dodano **+100 darmowych spinów**!"

    if pending_promo:
        with db_lock:
            cursor.execute("SELECT reward_type, amount, min_deposit FROM custom_promos WHERE code = ?", (pending_promo,))
            p_data = cursor.fetchone()
        if p_data:
            r_type, amount, min_dep = p_data
            if stars >= min_dep:
                with db_lock:
                    cursor.execute("INSERT OR IGNORE INTO used_promos (user_id, code) VALUES (?, ?)", (user_id, pending_promo))
                    cursor.execute("UPDATE custom_promos SET used_count = used_count + 1 WHERE code = ?", (pending_promo,))
                    cursor.execute("UPDATE users SET pending_promo = '' WHERE user_id = ?", (user_id,))
                    if r_type == "monety":
                        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
                        bonus_msg += f"\n🎉 *Kod '{pending_promo}' zrealizowany!* Dodano *+{amount} monet* 💰!"
                    else:
                        cursor.execute("UPDATE users SET free_spins = free_spins + ? WHERE user_id = ?", (amount, user_id))
                        bonus_msg += f"\n🎉 *Kod '{pending_promo}' zrealizowany!* Dodano *+{amount} darmowych spinów* 🎰!"
                    conn.commit()

    balance, bet, free_spins, _, game_id, _, _ = get_user_data(user_id)
    bot.send_message(message.chat.id, f"🎉 *Płatność udana!* Dodano *+{coins}* monet.{bonus_msg}\n\n" + get_panel_text(user_id, balance, bet, free_spins, game_id), parse_mode="Markdown", reply_markup=get_menu(user_id, balance, bet, free_spins, game_id))

# --- CALLBACKI I INTERAKCJA ---
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    balance, bet, free_spins, bonus_activated, game_id, _, _ = get_user_data(user_id)

    if call.data == "refresh_main":
        try:
            bot.edit_message_text(
                get_panel_text(user_id, balance, bet, free_spins, game_id),
                call.message.chat.id,
                call.message.message_id,
                parse_mode="Markdown",
                reply_markup=get_menu(user_id, balance, bet, free_spins, game_id)
            )
        except Exception:
            pass

    elif call.data == "promo_100darmowe":
        success, msg = process_promo_code(user_id, "100darmowe")
        bot.answer_callback_query(call.id, "Aktywowano kod!" if success else "Info o kodzie", show_alert=True)
        bot.send_message(call.message.chat.id, msg, parse_mode="Markdown")

    elif call.data == "enter_promo":
        msg = bot.send_message(call.message.chat.id, "🎟️ Wyślij na czacie swój kod promocyjny (np. `/kod mojkod` lub po prostu treść kodu):")
        bot.register_next_step_handler(msg, process_text_promo)

    elif call.data == "deposit_menu":
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("⭐ 250 Stars (25 000 monet + Kod 100darmowe)", callback_data="buy_250"),
            types.InlineKeyboardButton("⭐ 500 Stars (55 000 monet)", callback_data="buy_500"),
            types.InlineKeyboardButton("🔙 Powrót", callback_data="refresh_main")
        )
        bot.edit_message_text("⭐ *Wybierz pakiet doładowania Stars:*", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "buy_250":
        bot.send_invoice(
            chat_id=call.message.chat.id,
            title="Doładowanie 25 000 monet",
            description="Pakiet 25 000 monet w RoyalSpin Casino + Kwalifikacja do kodu 100darmowe",
            invoice_payload="coins_25000_250",
            currency="XTR",
            prices=[types.LabeledPrice(label="25 000 monet", amount=250)]
        )

    elif call.data == "buy_500":
        bot.send_invoice(
            chat_id=call.message.chat.id,
            title="Doładowanie 55 000 monet",
            description="Pakiet 55 000 monet w RoyalSpin Casino (z bonusowym przelicznikiem)",
            invoice_payload="coins_55000_500",
            currency="XTR",
            prices=[types.LabeledPrice(label="55 000 monet", amount=500)]
        )

    elif call.data == "choose_game":
        markup = types.InlineKeyboardMarkup(row_width=1)
        for g_key, g_val in GAMES.items():
            markup.add(types.InlineKeyboardButton(g_val['name'], callback_data=f"setgame_{g_key}"))
        markup.add(types.InlineKeyboardButton("🔙 Powrót", callback_data="refresh_main"))
        bot.edit_message_text("🕹️ *Wybierz grę lub tryb:*", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data.startswith("setgame_"):
        new_game = call.data.split("_")[1]
        with db_lock:
            cursor.execute("UPDATE users SET current_game = ? WHERE user_id = ?", (new_game, user_id))
            conn.commit()
        balance, bet, free_spins, _, game_id, _, _ = get_user_data(user_id)
        bot.edit_message_text(
            get_panel_text(user_id, balance, bet, free_spins, game_id),
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=get_menu(user_id, balance, bet, free_spins, game_id)
        )

    elif call.data == "change_bet":
        markup = types.InlineKeyboardMarkup(row_width=3)
        for b in [10, 25, 50, 100, 250, 500]:
            markup.add(types.InlineKeyboardButton(f"{b} monet", callback_data=f"setbet_{b}"))
        markup.add(types.InlineKeyboardButton("🔙 Powrót", callback_data="refresh_main"))
        bot.edit_message_text("⚙️ *Wybierz stawkę zakładu:*", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data.startswith("setbet_"):
        new_bet = int(call.data.split("_")[1])
        with db_lock:
            cursor.execute("UPDATE users SET current_bet = ? WHERE user_id = ?", (new_bet, user_id))
            conn.commit()
        balance, bet, free_spins, _, game_id, _, _ = get_user_data(user_id)
        bot.edit_message_text(
            get_panel_text(user_id, balance, bet, free_spins, game_id),
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown",
            reply_markup=get_menu(user_id, balance, bet, free_spins, game_id)
        )

    elif call.data == "play_spin":
        game_info = GAMES.get(game_id, GAMES["owocowy"])
        # Sprawdzamy czy ma spiny czy saldo
        use_free = False
        if free_spins > 0:
            use_free = True
        elif balance < bet:
            bot.answer_callback_query(call.id, "❌ Masz za mało monet na ten zakład! Doładuj konto.", show_alert=True)
            return

        if use_free:
            update_free_spins(user_id, -1)
        else:
            update_balance(user_id, -bet)

        # Logika gry
        win = 0
        if game_info["type"] == "slot":
            symbols = game_info["symbols"]
            s1, s2, s3 = random.choice(symbols), random.choice(symbols), random.choice(symbols)
            result_str = f"{s1} | {s2} | {s3}"
            if s1 == s2 == s3:
                win = bet * 10
                msg_res = f"🎉 *JACKPOT!* Trafiłeś trzy symbole {s1}! Wygrana: **+{win} monet**!"
            elif s1 == s2 or s2 == s3 or s1 == s3:
                win = bet * 2
                msg_res = f"✨ *Wygrana!* Trafiłeś parę. Wygrana: **+{win} monet**!"
            else:
                msg_res = f"😢 Niestety tym razem nic nie trafiłeś."
        elif game_info["type"] == "blackjack":
            player_cards = random.randint(15, 21)
            dealer_cards = random.randint(14, 21)
            result_str = f"Twoje karty: {player_cards} | Krupier: {dealer_cards}"
            if player_cards > dealer_cards:
                win = bet * 2
                msg_res = f"🃏 *Wygrana w Blackjacku!* ({player_cards} vs {dealer_cards}) Wygrana: **+{win} monet**!"
            elif player_cards == dealer_cards:
                win = bet  # Zwrot stawki
                msg_res = f"🤝 *Remis!* Stawka wraca na konto."
            else:
                msg_res = f"❌ *Przegrana!* Krupier miał lepszy układ."
        else:  # ruletka
            kolor = random.choice(["🔴 Czerwony", "⚫ Czarny", "🟢 Zielone Zero"])
            result_str = f"Wylosowano: {kolor}"
            if "Czerwony" in kolor or "Czarny" in kolor:
                win = bet * 2
                msg_res = f"🎡 *Trafiłeś kolor!* Wygrana: **+{win} monet**!"
            else:
                win = bet * 36
                msg_res = f"🌟 *NIESAMOWITE! ZIELONE ZERO!* Wygrana: **+{win} monet**!"

        if win > 0:
            update_balance(user_id, win)

        balance, bet, free_spins, _, game_id, _, _ = get_user_data(user_id)
        try:
            bot.edit_message_text(
                f"{result_str}\n\n{msg_res}\n\n" + get_panel_text(user_id, balance, bet, free_spins, game_id),
                call.message.chat.id,
                call.message.message_id,
                parse_mode="Markdown",
                reply_markup=get_menu(user_id, balance, bet, free_spins, game_id)
            )
        except Exception:
            pass

    elif call.data == "withdraw_menu":
        bot.answer_callback_query(call.id, "Wypłaty realizowane są automatycznie przez panel administracyjny.", show_alert=True)

    elif call.data == "admin_panel" and is_admin(user_id):
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("💰 Dodaj komuś monety (/daj)", callback_data="admin_info_daj"),
            types.InlineKeyboardButton("🎟️ Stwórz kod promocyjny (/nowykod)", callback_data="admin_info_kod"),
            types.InlineKeyboardButton("🔙 Powrót do menu", callback_data="refresh_main")
        )
        bot.edit_message_text("👑 *PANEL ADMINISTRATORA*\n\nMożesz używać komend bezpośrednio na czacie:\n• `/daj ID ILOŚĆ` - dodaje monety\n• `/nowykod NAZWA monety/spiny ILOŚĆ LIMIT [MIN_DEPOZYT]`", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=['daj'])
def cmd_daj(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        bot.send_message(message.chat.id, "❌ Brak uprawnień!")
        return
    parts = message.text.split()
    if len(parts) < 3:
        bot.send_message(message.chat.id, "użycie: `/daj ID ILOŚĆ`", parse_mode="Markdown")
        return
    try:
        target_id = int(parts[1])
        amount = int(parts[2])
    except ValueError:
        bot.send_message(message.chat.id, "❌ Błędne argumenty!")
        return
    update_balance(target_id, amount)
    bot.send_message(message.chat.id, f"✅ Dodano {amount} monet dla użytkownika `{target_id}`!", parse_mode="Markdown")

def process_text_promo(message):
    user_id = message.from_user.id
    code = message.text.replace("/kod", "").strip()
    success, msg = process_promo_code(user_id, code)
    balance, bet, free_spins, _, game_id, _, _ = get_user_data(user_id)
    bot.send_message(message.chat.id, msg, parse_mode="Markdown", reply_markup=get_menu(user_id, balance, bet, free_spins, game_id))

@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

# Uruchomienie bota
if __name__ == "__main__":
    print(">>> BOT KASYNO URUCHOMIONY <<<")
    bot.infinity_polling(skip_pending=True)

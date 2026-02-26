import os, asyncio, logging, aiosqlite
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, Update, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- SOZLAMALAR ---
# Tokenni bu yerga qo'ying yoki Render Env orqali bering
BOT_TOKEN = "8699288154:AAHnlS2B6JhMJFJdYuBSiK23zsJPh6P8ALc"
ADMINS = [8252667611]
RENDER_URL = "https://sarakino.onrender.com"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()

# --- FSM HOLATLARI ---
class AdminStates(StatesGroup):
    add_movie = State()
    del_movie = State()
    add_ch = State()
    del_ch = State()
    send_ads = State()

# --- DATABASE FUNKSIYALARI ---
async def db_op(query, params=(), fetch=False):
    async with aiosqlite.connect("cinema.db") as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, params)
        if fetch:
            data = await cursor.fetchall()
            return data
        await db.commit()

async def init_db():
    await db_op("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY)")
    await db_op("CREATE TABLE IF NOT EXISTS movies (id TEXT PRIMARY KEY, file_id TEXT)")
    await db_op("CREATE TABLE IF NOT EXISTS channels (id TEXT PRIMARY KEY, link TEXT)")
    await db_op("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, status INTEGER)")
    await db_op("INSERT OR IGNORE INTO settings VALUES ('bot_active', 1)")

# --- MAJBURIY OBUNA MIDDLEWARE ---
class SubMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Message, data):
        if not event.text or event.text.startswith("/start"): 
            return await handler(event, data)
        
        # Bot holatini tekshirish
        status = await db_op("SELECT status FROM settings WHERE key='bot_active'", fetch=True)
        if status and status[0]['status'] == 0 and event.from_user.id not in ADMINS:
            return await event.answer("⚠️ Bot vaqtincha texnik xizmat ko'rsatish rejimida.")

        # Kanallarni tekshirish
        channels = await db_op("SELECT id, link FROM channels", fetch=True)
        for ch in channels:
            try:
                user = await event.bot.get_chat_member(ch['id'], event.from_user.id)
                if user.status in ['left', 'kicked']:
                    kb = [[InlineKeyboardButton(text="Obuna bo'lish", url=ch['link'])],
                          [InlineKeyboardButton(text="Tekshirish ✅", callback_data="check_sub")]]
                    return await event.answer(f"❌ Botdan foydalanish uchun kanalga a'zo bo'ling!", 
                                              reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
            except: continue
        return await handler(event, data)

dp.message.middleware(SubMiddleware())

# --- ADMIN KEYBOARDS ---
def admin_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Kino (+)", callback_data="add_m"), InlineKeyboardButton(text="🎬 Kino (-)", callback_data="del_m")],
        [InlineKeyboardButton(text="📢 Kanal (+)", callback_data="add_ch"), InlineKeyboardButton(text="📢 Kanal (-)", callback_data="del_ch")],
        [InlineKeyboardButton(text="📊 Stat", callback_data="stats"), InlineKeyboardButton(text="✉️ Reklama", callback_data="ads")],
        [InlineKeyboardButton(text="⚙️ Bot Yoqish/O'chirish", callback_data="toggle_bot")],
        [InlineKeyboardButton(text="❌ Panelni yopish", callback_data="close_admin")]
    ])

# --- USER HANDLERS ---
@dp.message(Command("start"))
async def start_cmd(m: Message):
    await db_op("INSERT OR IGNORE INTO users VALUES (?)", (m.from_user.id,))
    await m.answer("👋 Salom! Kino kodini kiriting va tomosha qiling.")

@dp.message(F.text.isdigit())
async def get_movie(m: Message):
    res = await db_op("SELECT file_id FROM movies WHERE id=?", (m.text,), fetch=True)
    if res:
        await m.answer_video(res[0]['file_id'], caption=f"🎬 Kino kodi: {m.text}\n\nDo'stlaringizga ham ulashing!")
    else:
        await m.answer("😔 Kechirasiz, bu kod bilan kino topilmadi.")

# --- ADMIN CALLBACKS & HANDLERS ---
@dp.message(Command("admin"), F.from_user.id.in_(ADMINS))
async def admin_panel(m: Message):
    await m.answer("🛠 Professional Admin Panelga xush kelibsiz:", reply_markup=admin_main_kb())

@dp.callback_query(F.data == "check_sub")
async def check_sub(c: CallbackQuery):
    await c.answer("Obuna tekshirildi, qaytadan urinib ko'ring!", show_alert=True)
    await c.message.delete()

@dp.callback_query(F.data == "stats")
async def show_stats(c: CallbackQuery):
    u = await db_op("SELECT COUNT(*) as cnt FROM users", fetch=True)
    m = await db_op("SELECT COUNT(*) as cnt FROM movies", fetch=True)
    await c.message.edit_text(f"📊 **Statistika:**\n\n👤 Foydalanuvchilar: {u[0]['cnt']}\n🎬 Kinolar bazasi: {m[0]['cnt']}", 
                              reply_markup=admin_main_kb(), parse_mode="Markdown")

@dp.callback_query(F.data == "toggle_bot")
async def toggle_bot_status(c: CallbackQuery):
    res = await db_op("SELECT status FROM settings WHERE key='bot_active'", fetch=True)
    new_status = 0 if res[0]['status'] == 1 else 1
    await db_op("UPDATE settings SET status=? WHERE key='bot_active'", (new_status,))
    msg = "✅ Bot ishga tushirildi" if new_status == 1 else "⚠️ Bot to'xtatildi"
    await c.answer(msg, show_alert=True)

# --- KINO BOSHQARISH ---
@dp.callback_query(F.data == "add_m")
async def add_movie_step1(c: CallbackQuery, state: FSMContext):
    await c.message.answer("🎞 Kinoni yuboring (Video shaklida) va uning kodini caption (tavsif) qismida yozing:")
    await state.set_state(AdminStates.add_movie)

@dp.message(AdminStates.add_movie, F.video)
async def add_movie_step2(m: Message, state: FSMContext):
    if not m.caption:
        return await m.answer("❌ Xato! Video captioniga kino kodini yozib qayta yuboring.")
    await db_op("INSERT OR REPLACE INTO movies VALUES (?,?)", (m.caption, m.video.file_id))
    await m.answer(f"✅ Kino bazaga qo'shildi! Kod: {m.caption}")
    await state.clear()

@dp.callback_query(F.data == "del_m")
async def del_movie_step1(c: CallbackQuery, state: FSMContext):
    await c.message.answer("🗑 O'chirmoqchi bo'lgan kino kodini yuboring:")
    await state.set_state(AdminStates.del_movie)

@dp.message(AdminStates.del_movie)
async def del_movie_step2(m: Message, state: FSMContext):
    await db_op("DELETE FROM movies WHERE id=?", (m.text,))
    await m.answer(f"🗑 Kino (Kod: {m.text}) bazadan o'chirildi.")
    await state.clear()

# --- KANAL BOSHQARISH ---
@dp.callback_query(F.data == "add_ch")
async def add_ch_step1(c: CallbackQuery, state: FSMContext):
    await c.message.answer("📢 Kanal ID va Linkini probel bilan yuboring:\nMasalan: `-100123456 https://t.me/kanal_link` \n\n*Bot kanalga admin bo'lishi shart!*")
    await state.set_state(AdminStates.add_ch)

@dp.message(AdminStates.add_ch)
async def add_ch_step2(m: Message, state: FSMContext):
    try:
        cid, clink = m.text.split(" ")
        await db_op("INSERT OR REPLACE INTO channels VALUES (?,?)", (cid, clink))
        await m.answer("✅ Majburiy obuna kanali qo'shildi.")
        await state.clear()
    except:
        await m.answer("❌ Xato format. Qayta urinib ko'ring.")

@dp.callback_query(F.data == "del_ch")
async def del_ch_step1(c: CallbackQuery, state: FSMContext):
    channels = await db_op("SELECT * FROM channels", fetch=True)
    text = "O'chirmoqchi bo'lgan kanal ID'sini nusxalab yuboring:\n\n"
    for ch in channels:
        text += f"ID: `{ch['id']}` \nLink: {ch['link']}\n\n"
    await c.message.answer(text, parse_mode="Markdown")
    await state.set_state(AdminStates.del_ch)

@dp.message(AdminStates.del_ch)
async def del_ch_step2(m: Message, state: FSMContext):
    await db_op("DELETE FROM channels WHERE id=?", (m.text,))
    await m.answer("🗑 Kanal ro'yxatdan o'chirildi.")
    await state.clear()

# --- REKLAMA ---
@dp.callback_query(F.data == "ads")
async def send_ads_step1(c: CallbackQuery, state: FSMContext):
    await c.message.answer("✉️ Reklama xabarini yuboring (Rasm, Video, Text farqi yo'q):")
    await state.set_state(AdminStates.send_ads)

@dp.message(AdminStates.send_ads)
async def send_ads_step2(m: Message, state: FSMContext):
    users = await db_op("SELECT id FROM users", fetch=True)
    sent, failed = 0, 0
    await m.answer("🚀 Reklama tarqatish boshlandi...")
    for user in users:
        try:
            await m.copy_to(user['id'])
            sent += 1
            await asyncio.sleep(0.05)
        except: failed += 1
    await m.answer(f"✅ Reklama tugatildi!\n📤 Yuborildi: {sent}\n❌ Bloklagan: {failed}")
    await state.clear()

@dp.callback_query(F.data == "close_admin")
async def close_admin(c: CallbackQuery):
    await c.message.delete()

# --- WEBHOOK & FASTAPI ---
@app.on_event("startup")
async def on_startup():
    await init_db()
    await bot.set_webhook(f"{RENDER_URL}/webhook", drop_pending_updates=True)

@app.post("/webhook")
async def webhook_handle(request: Request):
    update = Update.model_validate(await request.json(), context={"bot": bot})
    await dp.feed_update(bot, update)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
import os, asyncio, logging, aiosqlite
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, Update, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- SOZLAMALAR ---
TOKEN = "8699288154:AAHnlS2B6JhMJFJdYuBSiK23zsJPh6P8ALc"
ADMINS = [8553997595, 8252667611]  # Adminlar ID ro'yxati
RENDER_URL = "https://sarakino.onrender.com"

bot = Bot(token=TOKEN)
dp = Dispatcher()
app = FastAPI()

# --- HOLATLAR (FSM) ---
class AdminStates(StatesGroup):
    add_movie = State()
    del_movie = State()
    add_ch = State()
    del_ch = State()
    send_ads = State()

# --- DATABASE FUNKSIYALARI ---
async def db_op(query, params=(), fetch=False):
    async with aiosqlite.connect("cinema.db") as db:
        cursor = await db.execute(query, params)
        data = await cursor.fetchall() if fetch else None
        await db.commit()
        return data

async def init_db():
    await db_op("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY)")
    await db_op("CREATE TABLE IF NOT EXISTS movies (id TEXT PRIMARY KEY, file_id TEXT)")
    await db_op("CREATE TABLE IF NOT EXISTS channels (id TEXT PRIMARY KEY, link TEXT)")
    await db_op("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, status INTEGER)")
    await db_op("INSERT OR IGNORE INTO settings VALUES ('bot_active', 1)")

# --- MAJBURIY OBUNA MIDDLEWARE ---
class SubMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Message, data):
        if not event.text or event.text.startswith("/start"): return await handler(event, data)
        
        # Bot faolligini tekshirish
        status = await db_op("SELECT status FROM settings WHERE key='bot_active'", fetch=True)
        if status[0][0] == 0 and event.from_user.id not in ADMINS:
            return await event.answer("⚠️ Bot vaqtincha texnik xizmat ko'rsatishda.")

        # Kanalga obunani tekshirish
        channels = await db_op("SELECT id, link FROM channels", fetch=True)
        for ch_id, ch_link in channels:
            try:
                user = await event.bot.get_chat_member(ch_id, event.from_user.id)
                if user.status in ['left', 'kicked']:
                    btn = [[InlineKeyboardButton(text="Obuna bo'lish", url=ch_link)], [InlineKeyboardButton(text="Tekshirish", callback_data="check_sub")]]
                    return await event.answer("❌ Kanalga a'zo bo'lmagansiz!", reply_markup=InlineKeyboardMarkup(inline_keyboard=btn))
            except: continue
        return await handler(event, data)

dp.message.middleware(SubMiddleware())

# --- ADMIN PANEL TUGMALARI ---
def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Kino (+/-)", callback_data="m_manage"), InlineKeyboardButton(text="📢 Kanallar (+/-)", callback_data="ch_manage")],
        [InlineKeyboardButton(text="📊 Stat", callback_data="stats"), InlineKeyboardButton(text="✉️ Reklama", callback_data="ads")],
        [InlineKeyboardButton(text="⚙️ Bot Holati", callback_data="toggle_bot")]
    ])

# --- HANDLERS ---
@dp.message(Command("start"))
async def start(m: Message):
    await db_op("INSERT OR IGNORE INTO users VALUES (?)", (m.from_user.id,))
    await m.answer("👋 Xush kelibsiz! Kino kodini yuboring.")

@dp.message(F.text.isdigit())
async def get_movie(m: Message):
    res = await db_op("SELECT file_id FROM movies WHERE id=?", (m.text,), fetch=True)
    if res: await m.answer_video(res[0][0], caption=f"🎬 Kod: {m.text}")
    else: await m.answer("❌ Kino topilmadi.")

# --- ADMIN COMMANDS ---
@dp.message(Command("admin"), F.from_user.id.in_(ADMINS))
async def admin_main(m: Message):
    await m.answer("🛠 Admin Panel:", reply_markup=admin_kb())

@dp.callback_query(F.data == "stats")
async def stats(c: CallbackQuery):
    u = await db_op("SELECT COUNT(*) FROM users", fetch=True)
    m = await db_op("SELECT COUNT(*) FROM movies", fetch=True)
    await c.message.edit_text(f"📊 Statistika:\n👤 Userlar: {u[0][0]}\n🎬 Kinolar: {m[0][0]}", reply_markup=admin_kb())

@dp.callback_query(F.data == "m_manage")
async def m_manage(c: CallbackQuery):
    kb = [[InlineKeyboardButton(text="➕ Qo'shish", callback_data="add_m"), InlineKeyboardButton(text="🗑 O'chirish", callback_data="del_m")]]
    await c.message.edit_text("Kinoni boshqarish:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "add_m")
async def add_m(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Kinoni yuboring va captionga kodini yozing.")
    await state.set_state(AdminStates.add_movie)

@dp.message(AdminStates.add_movie, F.video)
async def save_m(m: Message, state: FSMContext):
    if m.caption:
        await db_op("INSERT INTO movies VALUES (?,?)", (m.caption, m.video.file_id))
        await m.answer("✅ Saqlandi.")
        await state.clear()

@dp.callback_query(F.data == "ads")
async def ads_start(c: CallbackQuery, state: FSMContext):
    await c.message.answer("Reklama xabarini yuboring (Video, Rasm yoki Text):")
    await state.set_state(AdminStates.send_ads)

@dp.message(AdminStates.send_ads)
async def send_ads(m: Message, state: FSMContext):
    users = await db_op("SELECT id FROM users", fetch=True)
    count = 0
    for u in users:
        try:
            await m.copy_to(u[0])
            count += 1
            await asyncio.sleep(0.05)
        except: continue
    await m.answer(f"✅ {count} kishiga yuborildi.")
    await state.clear()

# --- WEBHOOK SETUP ---
@app.on_event("startup")
async def on_startup():
    await init_db()
    await bot.set_webhook(f"{RENDER_URL}/webhook")

@app.post("/webhook")
async def webhook_handle(request: Request):
    update = Update.model_validate(await request.json(), context={"bot": bot})
    await dp.feed_update(bot, update)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
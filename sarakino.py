import os, asyncio, logging, aiosqlite
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, Update, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- SOZLAMALAR ---
BOT_TOKEN = "8699288154:AAHnlS2B6JhMJFJdYuBSiK23zsJPh6P8ALc"
RENDER_URL = "https://sarakino.onrender.com"
DEFAULT_ADMINS = [8252667611] 

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()

# --- FSM HOLATLARI ---
class AdminStates(StatesGroup):
    add_movie_file = State()
    add_movie_details = State()
    del_movie = State()
    add_ch = State()
    del_ch = State()
    add_admin = State()
    del_admin = State()
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
    await db_op("CREATE TABLE IF NOT EXISTS movies (id TEXT PRIMARY KEY, file_id TEXT, caption TEXT)")
    await db_op("CREATE TABLE IF NOT EXISTS channels (username TEXT PRIMARY KEY, link TEXT)")
    await db_op("CREATE TABLE IF NOT EXISTS admins (id INTEGER PRIMARY KEY)")
    await db_op("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, status INTEGER)")
    await db_op("INSERT OR IGNORE INTO settings VALUES ('bot_active', 1)")
    for admin_id in DEFAULT_ADMINS:
        await db_op("INSERT OR IGNORE INTO admins VALUES (?)", (admin_id,))

# --- ADMINLARNI TEKSHIRISH ---
async def get_admins():
    res = await db_op("SELECT id FROM admins", fetch=True)
    return [row['id'] for row in res]

# --- MAJBURIY OBUNA MIDDLEWARE ---
class SubMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Message, data):
        if not event.text or event.text.startswith("/start"): return await handler(event, data)
        
        admins = await get_admins()
        status = await db_op("SELECT status FROM settings WHERE key='bot_active'", fetch=True)
        if status and status[0]['status'] == 0 and event.from_user.id not in admins:
            return await event.answer("⚠️ Bot vaqtincha texnik xizmat ko'rsatish rejimida.")

        channels = await db_op("SELECT username FROM channels", fetch=True)
        for ch in channels:
            try:
                username = ch['username'].replace('@','')
                user = await event.bot.get_chat_member(f"@{username}", event.from_user.id)
                if user.status in ['left', 'kicked']:
                    kb = [[InlineKeyboardButton(text="Obuna bo'lish", url=f"https://t.me/{username}")],
                          [InlineKeyboardButton(text="Tekshirish ✅", callback_data="check_sub")]]
                    return await event.answer("❌ Botdan foydalanish uchun kanalga a'zo bo'ling!", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
            except: continue
        return await handler(event, data)

dp.message.middleware(SubMiddleware())

# --- KEYBOARDS ---
def admin_menu():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🎬 Kino qo'shish"), KeyboardButton(text="🗑 Kino o'chirish")],
        [KeyboardButton(text="📢 Kanal qo'shish"), KeyboardButton(text="📢 Kanal o'chirish")],
        [KeyboardButton(text="👤 Admin qo'shish"), KeyboardButton(text="👤 Admin o'chirish")],
        [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="✉️ Reklama")],
        [KeyboardButton(text="⚙️ Bot Yoqish/O'chirish"), KeyboardButton(text="❌ Panelni yopish")]
    ], resize_keyboard=True)

# --- USER HANDLERS ---
@dp.message(Command("start"))
async def start_cmd(m: Message):
    await db_op("INSERT OR IGNORE INTO users VALUES (?)", (m.from_user.id,))
    await m.answer("👋 Salom! Kino kodini kiriting va tomosha qiling.")

@dp.message(F.text.isdigit())
async def get_movie(m: Message):
    res = await db_op("SELECT * FROM movies WHERE id=?", (m.text,), fetch=True)
    if res:
        await m.answer_video(res[0]['file_id'], caption=res[0]['caption'])
    else:
        await m.answer("😔 Kechirasiz, bu kod bilan kino topilmadi.")

# --- ADMIN PANEL ---
@dp.message(Command("admin"))
async def admin_entry(m: Message):
    if m.from_user.id in await get_admins():
        await m.answer("🛠 Admin panel ochildi:", reply_markup=admin_menu())

@dp.message(F.text == "📊 Statistika")
async def show_stats(m: Message):
    if m.from_user.id in await get_admins():
        u = await db_op("SELECT COUNT(*) as cnt FROM users", fetch=True)
        mov = await db_op("SELECT COUNT(*) as cnt FROM movies", fetch=True)
        await m.answer(f"📊 Statistika:\n👤 Userlar: {u[0]['cnt']}\n🎬 Kinolar: {mov[0]['cnt']}")

# --- KINO QO'SHISH (FORWARD VA GALEREYA) ---
@dp.message(F.text == "🎬 Kino qo'shish")
async def add_movie_start(m: Message, state: FSMContext):
    if m.from_user.id in await get_admins():
        await m.answer("🎞 Kinoni yuboring (galereyadan yoki Forward qilib):")
        await state.set_state(AdminStates.add_movie_file)

@dp.message(AdminStates.add_movie_file, (F.video | F.document))
async def add_movie_file(m: Message, state: FSMContext):
    file_id = m.video.file_id if m.video else m.document.file_id
    await state.update_data(file_id=file_id)
    await m.answer("🔢 Kino kodini va ma'lumotlarini quyidagi formatda yuboring:\n\n`KOD` (birinchi qatorda kod bo'lsin)\nNomi:\nYili:\nJanri:")
    await state.set_state(AdminStates.add_movie_details)

@dp.message(AdminStates.add_movie_details)
async def add_movie_finish(m: Message, state: FSMContext):
    data = await state.get_data()
    text_lines = m.text.split('\n')
    movie_id = text_lines[0].strip()
    details = "\n".join(text_lines[1:])
    
    caption = (f"🎬 **Kino topildi!**\n\n"
               f"📦 **Kod:** {movie_id}\n"
               f"{details}\n\n"
               f"📢 **Kanal:** @SaraFilmUzHD\n"
               f"👤 **Admin:** @mra_uz\n\n"
               f"🍿 Yoqimli tomosha!")
    
    await db_op("INSERT OR REPLACE INTO movies VALUES (?,?,?)", (movie_id, data['file_id'], caption))
    await m.answer(f"✅ Kino saqlandi!\nKod: {movie_id}", reply_markup=admin_menu())
    await state.clear()

# --- REKLAMA (USERLAR VA KANALLARGA) ---
@dp.message(F.text == "✉️ Reklama")
async def ads_start(m: Message, state: FSMContext):
    if m.from_user.id in await get_admins():
        await m.answer("✉️ Reklama xabarini yuboring. Bot buni barcha foydalanuvchilarga va ro'yxatdagi kanallarga tarqatadi:")
        await state.set_state(AdminStates.send_ads)

@dp.message(AdminStates.send_ads)
async def send_ads_finish(m: Message, state: FSMContext):
    users = await db_op("SELECT id FROM users", fetch=True)
    channels = await db_op("SELECT username FROM channels", fetch=True)
    u_count, c_count = 0, 0
    
    await m.answer("🚀 Reklama tarqatilmoqda...")
    
    # Userlarga yuborish
    for u in users:
        try:
            await m.copy_to(u['id'])
            u_count += 1
            await asyncio.sleep(0.05)
        except: continue
        
    # Kanallarga yuborish
    for ch in channels:
        try:
            await m.copy_to(f"@{ch['username'].replace('@','')}")
            c_count += 1
        except: continue
        
    await m.answer(f"✅ Tugatildi!\n👤 Userlar: {u_count}\n📢 Kanallar: {c_count}")
    await state.clear()

# --- QOLGAN ADMIN FUNKSIYALARI ---
@dp.message(F.text == "📢 Kanal qo'shish")
async def add_ch_start(m: Message, state: FSMContext):
    if m.from_user.id in await get_admins():
        await m.answer("📢 Kanal usernamesini yuboring (masalan: @SaraFilmUzHD):")
        await state.set_state(AdminStates.add_ch)

@dp.message(AdminStates.add_ch)
async def add_ch_finish(m: Message, state: FSMContext):
    username = m.text.replace("@", "").strip()
    await db_op("INSERT OR REPLACE INTO channels VALUES (?,?)", (username, f"https://t.me/{username}"))
    await m.answer(f"✅ @{username} qo'shildi.")
    await state.clear()

@dp.message(F.text == "👤 Admin qo'shish")
async def add_admin_start(m: Message, state: FSMContext):
    if m.from_user.id in await get_admins():
        await m.answer("👤 Yangi admin ID raqamini yuboring:")
        await state.set_state(AdminStates.add_admin)

@dp.message(AdminStates.add_admin)
async def add_admin_finish(m: Message, state: FSMContext):
    if m.text.isdigit():
        await db_op("INSERT OR IGNORE INTO admins VALUES (?)", (int(m.text),))
        await m.answer(f"✅ {m.text} admin qilindi.")
        await state.clear()

@dp.message(F.text == "⚙️ Bot Yoqish/O'chirish")
async def toggle_bot(m: Message):
    if m.from_user.id in await get_admins():
        res = await db_op("SELECT status FROM settings WHERE key='bot_active'", fetch=True)
        new_st = 0 if res[0]['status'] == 1 else 1
        await db_op("UPDATE settings SET status=? WHERE key='bot_active'", (new_st,))
        await m.answer(f"⚙️ Bot: {'Yoqildi ✅' if new_st == 1 else 'Oʻchirildi ❌'}")

@dp.message(F.text == "❌ Panelni yopish")
async def close_panel(m: Message):
    await m.answer("Panel yopildi.", reply_markup=types.ReplyKeyboardRemove())

@dp.callback_query(F.data == "check_sub")
async def check_callback(c: CallbackQuery):
    await c.answer("Tekshirildi, kodni yuboring!")
    await c.message.delete()

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
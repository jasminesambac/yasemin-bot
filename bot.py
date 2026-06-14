import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SHEET_ID = os.getenv("SHEET_ID")
CREDENTIALS_JSON = os.getenv("GOOGLE_SHEETS_CREDENTIALS")

creds_dict = json.loads(CREDENTIALS_JSON)
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
gc = gspread.authorize(creds)
sh = gc.open_by_key(SHEET_ID)
inventory_sheet = sh.worksheet("inventory")

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

def ana_menu():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("📋 Stok Listesi", callback_data="stok_liste"))
    return kb

def stok_listesi_menu(stoklar, page=0):
    items_per_page = 10
    total = (len(stoklar) + items_per_page - 1) // items_per_page
    kb = InlineKeyboardMarkup(row_width=1)
    start = page * items_per_page
    end = start + items_per_page
    for i in stoklar[start:end]:
        ad = i.get('Malzeme / Alet', '-')
        kalan = i.get('Kalan Miktar', '0')
        birim = i.get('Birim', '')
        kb.add(InlineKeyboardButton(f"{ad}: {kalan} {birim}", callback_data="dummy"))
    if page > 0:
        kb.add(InlineKeyboardButton("◀️ Önceki", callback_data=f"page_{page-1}"))
    if page < total - 1:
        kb.add(InlineKeyboardButton("Sonraki ▶️", callback_data=f"page_{page+1}"))
    kb.add(InlineKeyboardButton("🔙 Menü", callback_data="menu"))
    return kb, total

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer("🌿 **Yasemin Asistan**", reply_markup=ana_menu())

@dp.callback_query_handler(lambda c: True)
async def callback(callback_query: types.CallbackQuery):
    data = callback_query.data
    msg = callback_query.message
    await bot.answer_callback_query(callback_query.id)

    if data == "menu":
        await bot.edit_message_text("🌿 **Yasemin Asistan**", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=ana_menu())
        return

    if data == "stok_liste":
        try:
            stoklar = inventory_sheet.get_all_records()
            if not stoklar:
                await bot.edit_message_text("❌ Stok boş", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=ana_menu())
                return
            menu, total = stok_listesi_menu(stoklar, 0)
            await bot.edit_message_text(f"📦 **ENVANTER LİSTESİ** (Sayfa 1/{total})", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=menu)
        except Exception as e:
            await bot.edit_message_text(f"❌ Hata: {e}", chat_id=msg.chat.id, message_id=msg.message_id)
        return

    if data.startswith("page_"):
        page = int(data.split("_")[1])
        try:
            stoklar = inventory_sheet.get_all_records()
            menu, total = stok_listesi_menu(stoklar, page)
            await bot.edit_message_text(f"📦 **ENVANTER LİSTESİ** (Sayfa {page+1}/{total})", chat_id=msg.chat.id, message_id=msg.message_id, reply_markup=menu)
        except Exception as e:
            await bot.edit_message_text(f"❌ Hata: {e}", chat_id=msg.chat.id, message_id=msg.message_id)
        return

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
import os
import logging
import requests
from aiogram import Bot, Dispatcher, executor, types
from google import genai

# --- API ANAHTARLARI ---
API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_KEY")
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY")
GROK_KEY = os.getenv("GROK_API_KEY")

# --- GEMINI KURULUMU ---
gemini_client = genai.Client(api_key=GEMINI_KEY)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# --- GEMINI (Çalışan model) ---
def ask_gemini(question):
    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=question
        )
        return response.text[:500]
    except Exception as e:
        return f"Gemini hatası: {str(e)[:100]}"

# --- DEEPSEEK (Geçici olarak pasif) ---
def ask_deepseek(question):
    return "DeepSeek: Şimdilik devre dışı"

# --- GROK (Geçici olarak pasif) ---
def ask_grok(question):
    return "Grok: Şimdilik devre dışı"

# --- KOMUTLAR ---
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer("🌿 **Yasemin 3'lu Asistan** aktif!\n\n/sor [soru] - 3 AI'ya sor")

@dp.message_handler(commands=['sor'])
async def ask_all(message: types.Message):
    question = message.get_args()
    if not question:
        await message.reply("Lütfen bir soru yaz: /sor [sorunuz]")
        return
    
    msg = await message.reply("🔄 **3 AI aynı anda çalışıyor...**")
    
    gemini = ask_gemini(question)
    deepseek = ask_deepseek(question)
    grok = ask_grok(question)
    
    final = f"🤖 **3'lu Yapay Zeka Analizi:**\n\n"
    final += f"🔹 **Gemini:** {gemini}\n\n"
    final += f"🔹 **DeepSeek:** {deepseek}\n\n"
    final += f"🔹 **Grok:** {grok}"
    
    await bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=final[:4000])

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)import os
import logging
import requests
from aiogram import Bot, Dispatcher, executor, types
from google import genai

# --- API ANAHTARLARI (Railway'den alınacak) ---
API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_KEY")
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY")
GROK_KEY = os.getenv("GROK_API_KEY")

# --- GEMINI KURULUMU ---
gemini_client = genai.Client(api_key=GEMINI_KEY)

# --- LOG AYARLARI ---
logging.basicConfig(level=logging.INFO)

# --- BOT BAŞLATMA ---
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# --- YAPAY ZEKA SORGU FONKSİYONLARI ---
def ask_gemini(question):
    try:
        response = gemini_client.models.generate_content(
            model="gemini-1.5-flash",
            contents=question
        )
        return response.text[:500]
    except Exception as e:
        return f"Gemini hatası: {str(e)[:100]}"

def ask_deepseek(question):
    try:
        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {DEEPSEEK_KEY}", "Content-Type": "application/json"}
        data = {"model": "deepseek-chat", "messages": [{"role": "user", "content": question}]}
        response = requests.post(url, headers=headers, json=data).json()
        return response.get("choices", [{}])[0].get("message", {}).get("content", "-")[:500]
    except Exception as e:
        return f"DeepSeek hatası: {str(e)[:100]}"

def ask_grok(question):
    try:
        url = "https://api.x.ai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {GROK_KEY}", "Content-Type": "application/json"}
        data = {"model": "grok-beta", "messages": [{"role": "user", "content": question}]}
        response = requests.post(url, headers=headers, json=data).json()
        return response.get("choices", [{}])[0].get("message", {}).get("content", "-")[:500]
    except Exception as e:
        return f"Grok hatası: {str(e)[:100]}"

# --- KOMUTLAR ---
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer("🌿 **Yasemin 3'lu Asistan** aktif!\n\n📌 Komutlar:\n/sor [sorun] - 3 AI'ya sor\n/stok - Envanter göster\n/kaydet [işlem] - Kayıt ekle")

@dp.message_handler(commands=['sor'])
async def ask_all(message: types.Message):
    question = message.get_args()
    if not question:
        await message.reply("Lütfen bir soru yaz: /sor [sorunuz]")
        return
    
    msg = await message.reply("🔄 **3 AI aynı anda çalışıyor...**")
    
    gemini = ask_gemini(question)
    deepseek = ask_deepseek(question)
    grok = ask_grok(question)
    
    final = f"🤖 **3'lu Yapay Zeka Analizi:**\n\n"
    final += f"🔹 **Gemini:** {gemini}\n\n"
    final += f"🔹 **DeepSeek:** {deepseek}\n\n"
    final += f"🔹 **Grok:** {grok}"
    
    await bot.edit_message_text(chat_id=message.chat.id, message_id=msg.message_id, text=final[:4000])

@dp.message_handler(commands=['stok'])
async def show_stock(message: types.Message):
    await message.answer("📦 Stok sistemi hazırlanıyor... (CSV eklenecek)")

@dp.message_handler(commands=['kaydet'])
async def save_record(message: types.Message):
    text = message.get_args()
    if not text:
        await message.reply("Lütfen kaydedilecek işlemi yaz: /kaydet [işlem]")
        return
    await message.reply(f"✅ Kaydedildi: {text}\n\n(CSV bağlantısı yakında eklenecek)")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)

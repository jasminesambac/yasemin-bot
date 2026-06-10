import os
import logging
import requests
from aiogram import Bot, Dispatcher, executor, types

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_KEY")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# --- MODELLERİ LİSTELE (GEÇİCİ KOMUT) ---
@dp.message_handler(commands=['modeller'])
async def list_models(message: types.Message):
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_KEY}"
    
    try:
        response = requests.get(url)
        result = response.json()
        
        if "error" in result:
            await message.reply(f"Hata: {result['error']['message']}")
            return
        
        # Sadece generateContent destekleyen modelleri filtrele
        modeller = []
        for model in result.get("models", []):
            if "generateContent" in model.get("supportedGenerationMethods", []):
                modeller.append(model["name"].replace("models/", ""))
        
        if modeller:
            cevap = "✅ **Çalışan Modeller:**\n\n" + "\n".join(f"• {m}" for m in modeller[:10])
            await message.reply(cevap)
        else:
            await message.reply("Hiç generateContent modeli bulunamadı.")
            
    except Exception as e:
        await message.reply(f"Bağlantı hatası: {str(e)[:100]}")

# --- NORMAL SORU KOMUTU (OTOMATİK DENE) ---
@dp.message_handler(commands=['sor'])
async def ask(message: types.Message):
    question = message.get_args()
    if not question:
        await message.reply("Lütfen bir soru yaz: /sor [sorunuz]")
        return
    
    msg = await message.reply("🤔 Gemini düşünüyor...")
    
    # Önce /modeller'de çıkan isimlerden birini bulmaya çalışacağız
    # Geçici olarak en güncel tahminler:
    dene_modeller = [
        "gemini-2.0-flash-exp",
        "gemini-1.5-pro",
        "gemini-1.5-flash",
        "gemini-pro"
    ]
    
    cevap = "Hiçbir model çalışmadı."
    for model in dene_modeller:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_KEY}"
        data = {"contents": [{"parts": [{"text": question}]}]}
        
        try:
            response = requests.post(url, json=data)
            result = response.json()
            if "error" not in result:
                cevap = f"✅ **{model}** çalışıyor!\n\n{result['candidates'][0]['content']['parts'][0]['text'][:500]}"
                break
        except:
            continue
    
    await bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=msg.message_id,
        text=f"🤖 **Gemini:**\n\n{cevap}"
    )

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer("🌿 Bot çalışıyor!\n\n📌 **Komutlar:**\n/modeller - Çalışan modelleri listele\n/sor [soru] - Gemini'ye sor")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)import os
import logging
import requests
from aiogram import Bot, Dispatcher, executor, types

API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_KEY")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Denenecek modeller
MODELS = [
    "gemini-2.0-flash-exp",
    "gemini-1.5-pro",
    "gemini-pro"
]

def ask_gemini(question):
    for model in MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_KEY}"
        
        data = {
            "contents": [{
                "parts": [{"text": question}]
            }]
        }
        
        try:
            response = requests.post(url, json=data)
            result = response.json()
            
            if "error" in result:
                continue  # Bu model çalışmadı, diğerini dene
            
            return f"[{model}]\n{result['candidates'][0]['content']['parts'][0]['text'][:500]}"
            
        except:
            continue
    
    return "Hiçbir model çalışmadı! Lütfen Google AI Studio'dan yeni API anahtarı al."

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer("🌿 Bot çalışıyor! /sor [soru] yaz")

@dp.message_handler(commands=['sor'])
async def ask(message: types.Message):
    question = message.get_args()
    if not question:
        await message.reply("Lütfen bir soru yaz: /sor [sorunuz]")
        return
    
    msg = await message.reply("🤔 Gemini düşünüyor...")
    
    cevap = ask_gemini(question)
    
    await bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=msg.message_id,
        text=f"🤖 **Gemini:**\n\n{cevap}"
    )

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)

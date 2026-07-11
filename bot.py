import asyncio
import base64
import calendar
import csv
import concurrent.futures
import io
import json
import logging
import os
import re
import threading
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from time import monotonic
from typing import Any

import gspread
import requests
from oauth2client.service_account import ServiceAccountCredentials
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except Exception:
    plt = None


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("yasemin-bot")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

TR_TZ_OFFSET = timedelta(hours=3)
DATE_FMT = "%d-%m-%Y"
MSG_LIMIT = 3900
CACHE_TTL_SECONDS = 15

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
SHEET_ID = os.getenv("SHEET_ID", "").strip()
CREDENTIALS_JSON = os.getenv("GOOGLE_SHEETS_CREDENTIALS", "").strip()
AGNES_API_KEY = os.getenv("AGNES_API_KEY", "").strip()
AGNES_BASE_URL = os.getenv("AGNES_BASE_URL", "https://apihub.agnes-ai.com/v1").strip()
AGNES_MODEL = os.getenv("AGNES_MODEL", "agnes-2.0-flash").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
GROQ_WHISPER_MODEL = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3").strip()
if GROQ_WHISPER_MODEL == "hisper-large-v3":
    GROQ_WHISPER_MODEL = "whisper-large-v3"
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "").strip()
PINECONE_HOST = os.getenv("PINECONE_HOST", "").strip()
LLAMA_CLOUD_API_KEY = os.getenv("LLAMA_CLOUD_API_KEY", "").strip()
PERENUAL_API_KEY = os.getenv("PERENUAL_API_KEY", "").strip()
PERENUAL_IDENTIFY_API_KEY = os.getenv("PERENUAL_IDENTIFY_API_KEY", "").strip()
PLANTNET_API_KEY = os.getenv("PLANTNET_API_KEY", "").strip()
PLANTNET_PROJECT = os.getenv("PLANTNET_PROJECT", "all").strip() or "all"
PORT = int(os.getenv("PORT", "10000"))

INVENTORY_HEADERS = ["ID", "Kategori", "Malzeme / Alet", "Başlangıç Miktarı", "Kullanılan", "Kalan Miktar", "Birim", "Görevi / Not", "Son_Kullanma", "CreatedAt"]
HISTORY_HEADERS = ["ID", "Tarih", "Islem", "Malzeme", "Miktar", "Birim", "pH", "Not", "CreatedAt"]
KOMPOST_HEADERS = ["Tarih", "Islem", "Kullanilan_Malzeme_Miktar", "pH", "Not", "ID"]
PH_HEADERS = ["ID", "Tarih", "Teneke_No", "pH", "Not", "CreatedAt"]
REMINDER_HEADERS = ["ID", "Tarih", "Saat", "Metin", "Durum", "Chat_ID", "Tekrar", "Hafta_Gunu", "Ay_Gunu", "Gun_Araligi", "Bitis_Tarihi", "Kalan_Tekrar", "Yil_Ay", "CreatedAt"]
OBSERVATION_HEADERS = ["ID", "Tarih", "Kategori", "Not", "Foto_File_ID", "AI_Yorum", "CreatedAt"]
PLAN_HEADERS = ["ID", "Tarih", "Islem", "Hedef", "Malzeme_Miktar", "pH", "Not", "Durum", "CreatedAt", "CompletedAt"]
AREA_HEADERS = ["ID", "Alan", "Not", "Durum", "CreatedAt"]
RECIPE_HEADERS = ["ID", "Ad", "Islem", "Malzeme_Miktar", "pH", "Not", "Durum", "CreatedAt"]
ISSUE_HEADERS = ["ID", "Tarih", "Alan", "Baslik", "Not", "Durum", "CreatedAt", "ClosedAt"]
DIARY_HEADERS = ["ID", "Tarih", "Not", "CreatedAt"]
ESSENCE_HEADERS = ["ID", "Baslangic", "Cicek", "Yag", "Kap", "Gun", "Not", "Durum", "CreatedAt", "ClosedAt"]
ALERT_HEADERS = ["Key", "Value", "UpdatedAt"]
AI_DOC_HEADERS = ["ID", "Tarih", "Dosya", "Ozet", "Metin", "Pinecone", "CreatedAt"]
AI_LOG_HEADERS = ["ID", "Tarih", "Saat", "Kullanici", "Tur", "Girdi", "Cevap", "Ek", "CreatedAt"]

SHEET: dict[str, gspread.Worksheet] = {}
AI_CLIENT = None
GROQ_CLIENT = None
RECORD_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
AI_LOG_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=1)


class HealthHandler(BaseHTTPRequestHandler):
    def send_health(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path not in ("/", "/health"):
            self.send_response(404)
            self.end_headers()
            return
        self.send_health()
        self.wfile.write(b"Yasemin bot calisiyor")

    def do_HEAD(self) -> None:
        if self.path not in ("/", "/health"):
            self.send_response(404)
            self.end_headers()
            return
        self.send_health()

    def log_message(self, format: str, *args: Any) -> None:
        return


def start_health_server() -> None:
    def run() -> None:
        try:
            HTTPServer(("0.0.0.0", PORT), HealthHandler).serve_forever()
        except Exception:
            log.exception("Health server baslatilamadi")

    threading.Thread(target=run, daemon=True).start()
    log.info("Health server %s portunda basladi", PORT)


def now() -> datetime:
    return datetime.utcnow() + TR_TZ_OFFSET


def today_str() -> str:
    return now().strftime(DATE_FMT)


def normalize_name(value: Any) -> str:
    return str(value or "").strip().casefold()


def parse_decimal(value: Any) -> float:
    text = str(value).strip().replace(",", ".")
    return float(text)


def format_decimal(value: float) -> str:
    if abs(value - int(value)) < 0.000001:
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def parse_date(value: str | None, *, allow_words: bool = True) -> str | None:
    if not value:
        return None
    text = value.strip().lower()
    if allow_words and text in {"bugün", "bugun", "today"}:
        return today_str()
    if allow_words and text in {"dün", "dun", "yesterday"}:
        return (now() - timedelta(days=1)).strftime(DATE_FMT)
    text = text.replace("/", "-").replace(".", "-")
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d-%m-%y"):
        try:
            return datetime.strptime(text, fmt).strftime(DATE_FMT)
        except ValueError:
            pass
    return None


def parse_month(value: str) -> tuple[int, int] | None:
    text = value.strip().replace("/", "-").replace(".", "-")
    for fmt in ("%m-%Y", "%Y-%m"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.month, dt.year
        except ValueError:
            pass
    return None


def parse_time(value: str) -> str | None:
    text = value.strip()
    if re.fullmatch(r"\d{1,2}:\d{2}", text):
        h, m = text.split(":")
        if 0 <= int(h) <= 23 and 0 <= int(m) <= 59:
            return f"{int(h):02d}:{int(m):02d}"
    return None


def parse_datetime(date_value: Any, time_value: Any) -> datetime | None:
    date = parse_date(str(date_value or ""))
    time = parse_time(str(time_value or ""))
    if not date or not time:
        return None
    try:
        return datetime.strptime(f"{date} {time}", f"{DATE_FMT} %H:%M")
    except ValueError:
        return None


def next_weekday_date(weekday: int, from_day: datetime | None = None) -> str:
    base = (from_day or now()).date()
    days = (weekday - base.weekday()) % 7
    target = base + timedelta(days=days)
    return target.strftime(DATE_FMT)


def next_monthday_date(day: int, from_day: datetime | None = None) -> str:
    base = (from_day or now()).date()
    day = max(1, min(day, 31))
    last_day = calendar.monthrange(base.year, base.month)[1]
    target = base.replace(day=min(day, last_day))
    if target < base:
        year = base.year + (1 if base.month == 12 else 0)
        month = 1 if base.month == 12 else base.month + 1
        last_day = calendar.monthrange(year, month)[1]
        target = target.replace(year=year, month=month, day=min(day, last_day))
    return target.strftime(DATE_FMT)


def next_monthly_after(due: datetime, day: int, current: datetime) -> datetime:
    year = due.year
    month = due.month
    while True:
        month += 1
        if month == 13:
            month = 1
            year += 1
        last_day = calendar.monthrange(year, month)[1]
        target = due.replace(year=year, month=month, day=min(day, last_day))
        if target > current:
            return target


def next_yearly_date(day: int, month: int, from_day: datetime | None = None) -> str:
    base = from_day or now()
    year = base.year
    last_day = calendar.monthrange(year, month)[1]
    target = base.replace(year=year, month=month, day=min(day, last_day))
    if target.date() < base.date():
        year += 1
        last_day = calendar.monthrange(year, month)[1]
        target = target.replace(year=year, day=min(day, last_day))
    return target.strftime(DATE_FMT)


def next_yearly_after(due: datetime, day: int, month: int, current: datetime) -> datetime:
    year = due.year
    while True:
        year += 1
        last_day = calendar.monthrange(year, month)[1]
        target = due.replace(year=year, month=month, day=min(day, last_day))
        if target > current:
            return target


def repeat_label(row_or_repeat: Any) -> str:
    repeat = row_or_repeat
    interval_days = None
    if isinstance(row_or_repeat, dict):
        repeat = row_or_repeat.get("Tekrar", "tek")
        interval_days = row_or_repeat.get("Gun_Araligi")
    repeat = str(repeat or "tek").strip().casefold()
    if repeat in {"günlük", "gunluk", "her gün", "hergun", "daily"}:
        return "Her gün"
    if repeat in {"haftalık", "haftalik", "weekly"}:
        return "Haftalık"
    if repeat in {"aylık", "aylik", "monthly"}:
        return "Aylık"
    if repeat in {"aralık", "aralik", "gunde_bir", "interval"}:
        try:
            n = int(float(str(interval_days or "0").replace(",", ".")))
        except Exception:
            n = 0
        return f"Her {n} günde bir" if n > 0 else "Aralıklı"
    if repeat in {"yıllık", "yillik", "yearly"}:
        return "Yıllık (Mevsimsel)"
    return "Tek seferlik"


def reminder_limit_suffix(row: dict[str, Any]) -> str:
    remaining = str(row.get("Kalan_Tekrar") or "").strip()
    end_date = str(row.get("Bitis_Tarihi") or "").strip()
    if remaining:
        try:
            n = int(float(remaining.replace(",", ".")))
            return f", {n} tekrar kaldı"
        except Exception:
            pass
    if end_date:
        return f", {end_date} tarihine kadar"
    return ""


def chunks(text: str, limit: int = MSG_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    current = ""
    for line in text.splitlines(True):
        if len(current) + len(line) > limit:
            parts.append(current)
            current = ""
        while len(line) > limit:
            parts.append(line[:limit])
            line = line[limit:]
        current += line
    if current:
        parts.append(current)
    return parts


async def send_chunks(update: Update, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    target = update.effective_message
    if not target:
        return
    parts = chunks(text)
    for i, part in enumerate(parts):
        await target.reply_text(part, reply_markup=reply_markup if i == len(parts) - 1 else None)


async def edit_or_send(update: Update, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    query = update.callback_query
    if query and query.message:
        try:
            await query.message.edit_text(text, reply_markup=reply_markup)
            return
        except BadRequest as exc:
            if "Message is not modified" in str(exc):
                return
            if "message to edit not found" not in str(exc).lower() and "message can't be edited" not in str(exc).lower():
                log.warning("edit failed: %s", exc)
        try:
            await query.message.reply_text(text, reply_markup=reply_markup)
        except Exception:
            log.exception("reply_text failed")
        return
    await send_chunks(update, text, reply_markup)


def kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=data) for label, data in row] for row in rows])


MENU_BUTTON_TEXT = "🏠 Menü"


def persistent_menu_kb() -> ReplyKeyboardMarkup:
    """Sohbetin altında hep sabit duran, komut yazmaya gerek bırakmayan menü butonu."""
    return ReplyKeyboardMarkup([[KeyboardButton(MENU_BUTTON_TEXT)]], resize_keyboard=True, is_persistent=True)


def back_cancel(back_to: str) -> InlineKeyboardMarkup:
    return kb([[("Geri", back_to), ("İptal", "cancel"), ("Ana Menü", "m:main")]])


def main_menu() -> InlineKeyboardMarkup:
    return kb([
        [("📍 Bugün", "m:today")],
        [("📋 Kayıtlar", "g:records"), ("🌱 Bahçe", "g:garden")],
        [("🧪 Üretim", "g:production"), ("🤖 AI", "g:ai")],
        [("🌿 Bitki AI", "m:plant_ai")],
        [("⚙️ Sistem", "g:system")],
    ])


def records_group_menu() -> InlineKeyboardMarkup:
    return kb([
        [("📦 Stok", "m:stock"), ("📌 Sorun", "m:issues")],
        [("📜 Geçmiş", "m:history"), ("🔬 pH", "m:ph")],
        [("📔 Günlük", "m:diary"), ("📸 Gözlem", "m:observation")],
        [("📊 Rapor", "m:report")],
        [("🔙 Geri", "m:main")],
    ])


def garden_group_menu() -> InlineKeyboardMarkup:
    return kb([
        [("🌱 Alanlar", "m:areas"), ("🗓️ Plan", "m:plan")],
        [("⏰ Hatırlatma", "m:reminder"), ("🌤️ Hava", "m:weather")],
        [("🔙 Geri", "m:main")],
    ])


def production_group_menu() -> InlineKeyboardMarkup:
    return kb([
        [("🪱 Kompost", "m:compost"), ("🌸 Esans", "m:essence")],
        [("🧪 Reçeteler", "m:recipes")],
        [("🔙 Geri", "m:main")],
    ])


def ai_group_menu() -> InlineKeyboardMarkup:
    return kb([
        [("🤖 AI Sor", "m:ai"), ("📸 Foto AI", "obs:ai")],
        [("🔙 Geri", "m:main")],
    ])


def plant_ai_menu() -> InlineKeyboardMarkup:
    return kb([
        [("🔎 Bitki Ara", "plant:search"), ("📋 Bakım Bilgisi", "plant:care")],
        [("📷 Bitki Tanı", "plant:identify"), ("🤖 AI Tavsiye", "plant:advice")],
        [("🔙 Geri", "m:main")],
    ])


def system_group_menu() -> InlineKeyboardMarkup:
    return kb([
        [("🧭 Durum", "m:status"), ("💾 Yedekle", "backup")],
        [("🚨 Kritik Stok", "stock:critical"), ("🔍 Hızlı Arama", "search:start")],
        [("🔙 Geri", "m:main")],
    ])


def stock_menu() -> InlineKeyboardMarkup:
    return kb([
        [("📋 Stok Listesi", "stock:list"), ("🔍 Stok Sorgula", "stock:search")],
        [("⬇️ Stoktan Düş", "stock:use"), ("➕ Yeni Malzeme Ekle", "stock:add")],
        [("❌ Malzeme Sil", "stock:delete"), ("↩️ Geri Al", "stock:undo")],
        [("🚨 Kritik Stok", "stock:critical")],
        [("🔙 Geri", "m:main")],
    ])


def ph_menu() -> InlineKeyboardMarkup:
    return kb([
        [("🔬 Son pH", "ph:last"), ("📊 Tüm pH (Tek Teneke)", "ph:one")],
        [("📋 Tüm Tenekelerin Tüm pH", "ph:all"), ("➕ pH Ekle", "ph:add")],
        [("❌ pH Sil", "ph:delete")],
        [("🔙 Geri", "m:main")],
    ])


def history_menu() -> InlineKeyboardMarkup:
    return kb([
        [("📜 Son 10 İşlem", "hist:last10"), ("📋 Tüm Geçmiş", "hist:all:0")],
        [("📅 Tarihli İşlemler", "hist:date"), ("❌ İşlem Sil", "hist:delete")],
        [("📝 İşlem Ekle", "hist:add")],
        [("🔙 Geri", "m:main")],
    ])


def compost_menu() -> InlineKeyboardMarkup:
    return kb([
        [("İşlem Geçmişi", "comp:all:0"), ("İşlem Ekle", "comp:add")],
        [("Tarihli İşlemler", "comp:date"), ("İşlem Sil", "comp:delete")],
        [("🔙 Geri", "m:main")],
    ])


def plan_menu() -> InlineKeyboardMarkup:
    return kb([
        [("➕ Plan Ekle", "plan:add"), ("📋 Yaklaşan Planlar", "plan:upcoming")],
        [("📅 Tarihli Planlar", "plan:date"), ("✅ Planı Tamamla", "plan:complete")],
        [("❌ Plan Sil", "plan:delete")],
        [("🔙 Geri", "m:main")],
    ])


def area_menu() -> InlineKeyboardMarkup:
    return kb([
        [("📋 Alan Listesi", "area:list"), ("➕ Alan Ekle", "area:add")],
        [("❌ Alan Sil", "area:delete")],
        [("🔙 Geri", "m:main")],
    ])


def recipe_menu() -> InlineKeyboardMarkup:
    return kb([
        [("📋 Reçete Listesi", "recipe:list"), ("➕ Reçete Ekle", "recipe:add")],
        [("🤖 AI Reçete Oluştur", "recipe:ai")],
        [("▶️ Reçete Uygula", "recipe:apply"), ("❌ Reçete Sil", "recipe:delete")],
        [("🔙 Geri", "m:main")],
    ])


def report_menu() -> InlineKeyboardMarkup:
    return kb([
        [("📊 Aylık Rapor", "report:month"), ("📅 Günlük Rapor", "report:daily")],
        [("📈 İstatistik", "report:stats"), ("📉 Stok Grafiği", "report:stock")],
        [("🔬 pH Grafiği", "report:ph_chart"), ("🌿 Sezon Özeti", "report:season")],
        [("🔙 Geri", "m:main")],
    ])


def ph_chart_menu() -> InlineKeyboardMarkup:
    fixed = ["Konteyner 1", "Konteyner 2", "Konteyner 3"] + [str(i) for i in range(1, 21)]
    tenekeler = sorted({str(r.get("Teneke_No", "")).strip() for r in records("ph_records") if str(r.get("Teneke_No", "")).strip()}, key=lambda x: int(x) if x.isdigit() else 999999)
    tenekeler = fixed + [t for t in tenekeler if t not in fixed]
    rows: list[list[tuple[str, str]]] = [[("📊 Tümü (üst üste)", "report:ph_chart:all")]]
    line: list[tuple[str, str]] = []
    for teneke in tenekeler[:40]:
        line.append((teneke, f"report:ph_chart:{teneke}"))
        if len(line) == 4:
            rows.append(line)
            line = []
    if line:
        rows.append(line)
    rows.append([("Geri", "m:report"), ("İptal", "cancel"), ("Ana Menü", "m:main")])
    return kb(rows)


def issue_menu() -> InlineKeyboardMarkup:
    return kb([
        [("➕ Sorun Aç", "issue:add"), ("📋 Açık Sorunlar", "issue:list")],
        [("📝 İşlem Ekle", "issue:note"), ("✅ Sorunu Kapat", "issue:close")],
        [("📅 Sorun Geçmişi", "issue:history")],
        [("🔙 Geri", "m:main")],
    ])


def diary_menu() -> InlineKeyboardMarkup:
    return kb([
        [("➕ Günlük Not Ekle", "diary:add"), ("📋 Son Günlükler", "diary:list")],
        [("📅 Tarihli Günlük", "diary:date"), ("🤖 AI Gün Özeti", "diary:ai")],
        [("❌ Günlük Sil", "diary:delete")],
        [("🔙 Geri", "m:main")],
    ])


def essence_menu() -> InlineKeyboardMarkup:
    return kb([
        [("➕ Esans Başlat", "ess:add"), ("📋 Aktif Esanslar", "ess:list")],
        [("⏳ Süresi Gelenler", "ess:due"), ("✅ Esansı Bitir", "ess:close")],
        [("❌ Esans Sil", "ess:delete")],
        [("🔙 Geri", "m:main")],
    ])


def reminder_menu() -> InlineKeyboardMarkup:
    return kb([
        [("➕ Hatırlatma Ekle", "rem:add"), ("📋 Bekleyen Hatırlatmalar", "rem:list")],
        [("❌ Hatırlatma Sil", "rem:delete")],
        [("🔙 Geri", "m:main")],
    ])


def reminder_limit_menu() -> InlineKeyboardMarkup:
    return kb([
        [("Sınırsız", "rem:limit:none")],
        [("Bitiş Tarihi Belirle", "rem:limit:enddate")],
        [("Tekrar Sayısı Belirle", "rem:limit:count")],
        [("Geri", "rem:add"), ("İptal", "cancel"), ("Ana Menü", "m:main")],
    ])


def observation_menu() -> InlineKeyboardMarkup:
    return kb([
        [("📷 Fotoğraflı Gözlem Ekle", "obs:add"), ("🤖 Fotoğrafı AI Yorumla", "obs:ai")],
        [("📋 Gözlem Geçmişi", "obs:all:0"), ("📅 Tarihli Gözlemler", "obs:date")],
        [("❌ Gözlem Sil", "obs:delete")],
        [("🔙 Geri", "m:main")],
    ])


def ai_menu() -> InlineKeyboardMarkup:
    return kb([
        [("Agnes AI", "ai:agnes"), ("Gemini", "ai:gemini")],
        [("Groq Hızlı", "ai:groq"), ("Güncel Ara", "ai:web")],
        [("İkisine de Sor", "ai:both"), ("Sesli Sor", "ai:voice")],
        [("Dosya Oku", "ai:file"), ("Dosyaya Sor", "ai:docq")],
        [("📊 Verilerime Sor", "ai:records")],
        [("AI Kayıtlar", "ai:logs")],
        [("AI Hafızayı Temizle", "ai:clear")],
        [("🔙 Geri", "m:main")],
    ])


def ai_logs_menu() -> InlineKeyboardMarkup:
    return kb([
        [("Agnes", "ailog:list:ai_agnes_logs"), ("Gemini", "ailog:list:ai_gemini_logs")],
        [("Groq", "ailog:list:ai_groq_logs"), ("Arama", "ailog:list:ai_web_logs")],
        [("Ses", "ailog:list:ai_voice_logs"), ("Dosya", "ailog:list:ai_file_logs")],
        [("Görsel", "ailog:list:ai_image_logs"), ("Sil", "ailog:delete")],
        [("🔙 Geri", "m:ai")],
    ])


def weather_menu() -> InlineKeyboardMarkup:
    return kb([
        [("🌤️ Anlık Hava", "weather:now"), ("📊 Aylık Hava", "weather:month")],
        [("🔙 Geri", "m:main")],
    ])


def category_menu() -> InlineKeyboardMarkup:
    return kb([
        [("Katı", "cat:Katı"), ("Sıvı", "cat:Sıvı")],
        [("Alet", "cat:Alet"), ("Mekanik", "cat:Mekanik")],
        [("Cihaz", "cat:Cihaz")],
        [("Geri", "m:stock"), ("İptal", "cancel"), ("Ana Menü", "m:main")],
    ])


def unit_menu(back_to: str = "stock:add") -> InlineKeyboardMarkup:
    return kb([
        [("gr", "unit:gr"), ("ml", "unit:ml"), ("L", "unit:L"), ("adet", "unit:adet")],
        [("Geri", back_to), ("İptal", "cancel"), ("Ana Menü", "m:main")],
    ])


def operation_type_menu(prefix: str) -> InlineKeyboardMarkup:
    back_to = "m:stock" if prefix == "use" else "m:plan" if prefix == "planadd" else "m:recipes" if prefix == "recipeadd" else "m:history"
    return kb([
        [("Sulama", f"{prefix}:tur:Sulama"), ("Gübreleme", f"{prefix}:tur:Gübreleme")],
        [("İlaçlama", f"{prefix}:tur:İlaçlama"), ("Hasat", f"{prefix}:tur:Hasat")],
        [("Toprak İşlemi", f"{prefix}:tur:Toprak İşlemi"), ("Çelik Alma", f"{prefix}:tur:Çelik Alma")],
        [("Çelik Kontrol", f"{prefix}:tur:Çelik Kontrol"), ("Sisleme", f"{prefix}:tur:Sisleme")],
        [("Diğer", f"{prefix}:tur:Diğer")],
        [("Geri", back_to), ("İptal", "cancel"), ("Ana Menü", "m:main")],
    ])


def date_choice_menu(prefix: str) -> InlineKeyboardMarkup:
    rows = [
        [("Bugün", f"{prefix}:date:today"), ("Dün", f"{prefix}:date:yesterday")],
        [("Özel Tarih", f"{prefix}:date:custom")],
    ]
    if prefix == "rem":
        rows.append([("Her Gün", "rem:date:daily"), ("Haftalık", "rem:date:weekly")])
        rows.append([("Aylık", "rem:date:monthly"), ("Her X Günde Bir", "rem:date:interval")])
        rows.append([("🌱 Her Yıl (Mevsimsel)", "rem:date:yearly")])
    back_to = "m:history" if prefix == "histadd" else "m:compost" if prefix == "compadd" else "m:plan" if prefix == "planadd" else "m:diary" if prefix == "diary" else "m:reminder"
    rows.append([("Geri", back_to), ("İptal", "cancel"), ("Ana Menü", "m:main")])
    return kb(rows)


def weekday_menu() -> InlineKeyboardMarkup:
    days = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    rows = [[(day, f"rem:weekday:{i}")] for i, day in enumerate(days)]
    rows.append([("Geri", "rem:add"), ("İptal", "cancel"), ("Ana Menü", "m:main")])
    return kb(rows)


def monthday_menu() -> InlineKeyboardMarkup:
    rows: list[list[tuple[str, str]]] = []
    for start in range(1, 32, 5):
        rows.append([(str(day), f"rem:monthday:{day}") for day in range(start, min(start + 5, 32))])
    rows.append([("Geri", "rem:add"), ("İptal", "cancel"), ("Ana Menü", "m:main")])
    return kb(rows)


def reminder_calendar_menu(year: int | None = None, month: int | None = None) -> InlineKeyboardMarkup:
    current = now()
    year = year or current.year
    month = month or current.month
    rows: list[list[tuple[str, str]]] = [[(f"{month:02d}-{year}", "noop")]]
    rows.append([("Pzt", "noop"), ("Sal", "noop"), ("Çar", "noop"), ("Per", "noop"), ("Cum", "noop"), ("Cmt", "noop"), ("Paz", "noop")])
    for week in calendar.monthcalendar(year, month):
        line = []
        for day in week:
            if day == 0:
                line.append((" ", "noop"))
            else:
                date_text = datetime(year, month, day).strftime(DATE_FMT)
                line.append((str(day), f"rem:calday:{date_text}"))
        rows.append(line)
    prev_year = year - 1 if month == 1 else year
    prev_month = 12 if month == 1 else month - 1
    next_year = year + 1 if month == 12 else year
    next_month = 1 if month == 12 else month + 1
    rows.append([("Önceki Ay", f"rem:cal:{prev_year}:{prev_month}"), ("Sonraki Ay", f"rem:cal:{next_year}:{next_month}")])
    rows.append([("Tarih Yaz", "rem:date:custom_text")])
    rows.append([("Geri", "rem:add"), ("İptal", "cancel"), ("Ana Menü", "m:main")])
    return kb(rows)


def time_choice_menu() -> InlineKeyboardMarkup:
    return kb([
        [("09:00", "rem:time:09:00"), ("12:00", "rem:time:12:00"), ("15:00", "rem:time:15:00")],
        [("17:00", "rem:time:17:00"), ("20:00", "rem:time:20:00"), ("Özel", "rem:time:custom")],
        [("Geri", "rem:add"), ("İptal", "cancel"), ("Ana Menü", "m:main")],
    ])


def ph_choice_menu(prefix: str = "histadd") -> InlineKeyboardMarkup:
    back_to = "m:compost" if prefix == "compadd" else "m:plan" if prefix == "planadd" else "m:recipes" if prefix == "recipeadd" else "m:history"
    return kb([
        [("5.0", f"{prefix}:ph:5.0"), ("5.5", f"{prefix}:ph:5.5"), ("6.0", f"{prefix}:ph:6.0")],
        [("6.5", f"{prefix}:ph:6.5"), ("7.0", f"{prefix}:ph:7.0"), ("Özel pH", f"{prefix}:ph_custom")],
        [("Ölçmedim", f"{prefix}:ph:")],
        [("Geri", back_to), ("İptal", "cancel"), ("Ana Menü", "m:main")],
    ])


def compost_type_menu() -> InlineKeyboardMarkup:
    return kb([
        [("Kompost Karıştırma", "compadd:tur:Kompost Karıştırma")],
        [("Kompost Kurma", "compadd:tur:Kompost Kurma")],
        [("Kompost Sulama", "compadd:tur:Kompost Sulama")],
        [("Kompost Kontrolü", "compadd:tur:Kompost Kontrolü")],
        [("Diğer", "compadd:tur:Diğer")],
        [("Geri", "m:compost"), ("İptal", "cancel"), ("Ana Menü", "m:main")],
    ])


def compost_container_menu(selected: list[str] | None = None) -> InlineKeyboardMarkup:
    selected = selected or []
    rows = []
    for container in ["Konteyner 1", "Konteyner 2", "Konteyner 3"]:
        label = f"✓ {container}" if container in selected else container
        rows.append([(label, f"compadd:container:{container}")])
    rows.append([("Devam Et", "compadd:containers_done")])
    rows.append([("Geri", "m:compost"), ("İptal", "cancel"), ("Ana Menü", "m:main")])
    return kb(rows)


def histadd_continue_menu() -> InlineKeyboardMarkup:
    return kb([
        [("Başka Malzeme Ekle", "histadd:more")],
        [("Devam Et", "histadd:done")],
        [("Geri", "m:history"), ("İptal", "cancel"), ("Ana Menü", "m:main")],
    ])


def planadd_continue_menu() -> InlineKeyboardMarkup:
    return kb([
        [("Başka Malzeme Ekle", "planadd:more")],
        [("Devam Et", "planadd:done")],
        [("Geri", "m:plan"), ("İptal", "cancel"), ("Ana Menü", "m:main")],
    ])


def recipeadd_continue_menu() -> InlineKeyboardMarkup:
    return kb([
        [("Başka Malzeme Ekle", "recipeadd:more")],
        [("Devam Et", "recipeadd:done")],
        [("Geri", "m:recipes"), ("İptal", "cancel"), ("Ana Menü", "m:main")],
    ])


def area_buttons(action: str, back_to: str = "m:areas") -> InlineKeyboardMarkup:
    rows: list[list[tuple[str, str]]] = []
    active = [r for r in records("areas") if str(r.get("Durum", "aktif")).strip().casefold() != "pasif"]
    for area in active[:30]:
        name = str(area.get("Alan", "Adsız"))[:35]
        rows.append([(name, f"area_select:{action}:{area['_row']}")])
    rows.append([("Alan Yaz", f"area_select:{action}:custom")])
    rows.append([("Geri", back_to), ("İptal", "cancel"), ("Ana Menü", "m:main")])
    return kb(rows)


def city_menu(prefix: str) -> InlineKeyboardMarkup:
    cities = ["İstanbul", "Ankara", "İzmir", "Bursa", "Antalya", "Adana", "Konya", "Trabzon"]
    rows = []
    for i in range(0, len(cities), 2):
        rows.append([(cities[i], f"{prefix}:city:{cities[i]}"), (cities[i + 1], f"{prefix}:city:{cities[i + 1]}")])
    rows.append([("Şehir Yaz", f"{prefix}:city:custom")])
    rows.append([("Geri", "m:weather"), ("İptal", "cancel"), ("Ana Menü", "m:main")])
    return kb(rows)


def init_sheets() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN eksik.")
    if not SHEET_ID:
        raise RuntimeError("SHEET_ID eksik.")
    if not CREDENTIALS_JSON:
        raise RuntimeError("GOOGLE_SHEETS_CREDENTIALS eksik.")
    wanted = {
        "inventory": INVENTORY_HEADERS,
        "history": HISTORY_HEADERS,
        "Kompost": KOMPOST_HEADERS,
        "ph_records": PH_HEADERS,
        "reminders": REMINDER_HEADERS,
        "observations": OBSERVATION_HEADERS,
        "plans": PLAN_HEADERS,
        "areas": AREA_HEADERS,
        "recipes": RECIPE_HEADERS,
        "issues": ISSUE_HEADERS,
        "diary": DIARY_HEADERS,
        "essences": ESSENCE_HEADERS,
        "alerts": ALERT_HEADERS,
        "ai_docs": AI_DOC_HEADERS,
        "ai_agnes_logs": AI_LOG_HEADERS,
        "ai_gemini_logs": AI_LOG_HEADERS,
        "ai_groq_logs": AI_LOG_HEADERS,
        "ai_web_logs": AI_LOG_HEADERS,
        "ai_voice_logs": AI_LOG_HEADERS,
        "ai_file_logs": AI_LOG_HEADERS,
        "ai_image_logs": AI_LOG_HEADERS,
    }

    try:
        creds_dict = json.loads(CREDENTIALS_JSON)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GOOGLE_SHEETS_CREDENTIALS geçerli JSON değil. Railway Variables değerini kontrol et.") from exc

    client_email = creds_dict.get("client_email", "")
    if not client_email:
        raise RuntimeError("GOOGLE_SHEETS_CREDENTIALS içinde client_email yok. Service account JSON dosyasının tamamı gerekli.")
    log.info("Google Sheets service account: %s", client_email)
    log.info("Google Sheet ID: ...%s", SHEET_ID[-6:] if len(SHEET_ID) >= 6 else SHEET_ID)

    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    try:
        spreadsheet = client.open_by_key(SHEET_ID)
    except Exception as exc:
        raise RuntimeError(
            "Google Sheets bağlantısı kurulamadı. Railway'deki GOOGLE_SHEETS_CREDENTIALS service account'u geçerli olmalı, "
            f"Google Sheet bu e-posta ile paylaşılmalı: {client_email}, ve SHEET_ID doğru olmalı. "
            f"Google hatası: {exc}"
        ) from exc
    for title, headers in wanted.items():
        try:
            ws = spreadsheet.worksheet(title)
        except gspread.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title=title, rows=1000, cols=len(headers) + 2)
        existing_headers = ws.row_values(1)
        if not existing_headers:
            ws.append_row(headers)
        else:
            for header in headers:
                if header not in existing_headers:
                    ws.update_cell(1, len(existing_headers) + 1, header)
                    existing_headers.append(header)
        SHEET[title] = ws


def init_ai() -> None:
    global AI_CLIENT, GROQ_CLIENT
    if AGNES_API_KEY and OpenAI:
        AI_CLIENT = OpenAI(base_url=AGNES_BASE_URL, api_key=AGNES_API_KEY)
    if GROQ_API_KEY and OpenAI:
        GROQ_CLIENT = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=GROQ_API_KEY)


def records(sheet_name: str) -> list[dict[str, Any]]:
    cached = RECORD_CACHE.get(sheet_name)
    if cached and monotonic() - cached[0] < CACHE_TTL_SECONDS:
        return [dict(row) for row in cached[1]]
    data = SHEET[sheet_name].get_all_records()
    for i, row in enumerate(data, start=2):
        row["_row"] = i
        if not row.get("ID"):
            row["_id"] = str(i - 1)
        else:
            row["_id"] = str(row.get("ID"))
    RECORD_CACHE[sheet_name] = (monotonic(), [dict(row) for row in data])
    return data


def next_id(sheet_name: str) -> int:
    ids = []
    for row in records(sheet_name):
        try:
            ids.append(int(row.get("ID") or row.get("_id") or 0))
        except Exception:
            pass
    return max(ids or [0]) + 1


def append_record(sheet_name: str, headers: list[str], values: dict[str, Any]) -> None:
    current_headers = SHEET[sheet_name].row_values(1)
    if not current_headers:
        SHEET[sheet_name].append_row(headers)
        current_headers = headers
    for header in headers:
        if header not in current_headers:
            SHEET[sheet_name].update_cell(1, len(current_headers) + 1, header)
            current_headers.append(header)
    row = [values.get(h, "") for h in current_headers]
    SHEET[sheet_name].append_row(row, value_input_option="USER_ENTERED")
    RECORD_CACHE.pop(sheet_name, None)


def write_ai_log(sheet_name: str, user_id: int | str, kind: str, prompt: str, answer: str, extra: str = "") -> int:
    item_id = next_id(sheet_name)
    append_record(sheet_name, AI_LOG_HEADERS, {
        "ID": item_id,
        "Tarih": today_str(),
        "Saat": now().strftime("%H:%M"),
        "Kullanici": user_id,
        "Tur": kind,
        "Girdi": prompt[:45000],
        "Cevap": answer[:45000],
        "Ek": extra[:4000],
        "CreatedAt": now().isoformat(timespec="seconds"),
    })
    return item_id


def log_ai(sheet_name: str, user_id: int | str, kind: str, prompt: str, answer: str, extra: str = "") -> int:
    def job() -> None:
        try:
            write_ai_log(sheet_name, user_id, kind, str(prompt), str(answer), str(extra))
        except Exception:
            log.exception("AI kaydı yazılamadı")

    AI_LOG_EXECUTOR.submit(job)
    return 0


def load_persistent_ai_history(sheet_name: str, user_id: int | str, limit: int = 6) -> list[dict[str, str]]:
    """Bot yeniden başladığında veya kullanıcı menüden çıkıp girdiğinde context.user_data
    sıfırlanır. Bu fonksiyon, o kullanıcının bu AI'daki son kayıtlı sorularını/cevaplarını
    Sheets'ten okuyup konuşma geçmişi olarak geri kazandırır (kalıcı hafıza hissi verir)."""
    try:
        rows = [r for r in records(sheet_name) if str(r.get("Kullanici", "")) == str(user_id)]
    except Exception:
        return []
    history: list[dict[str, str]] = []
    for row in rows[-limit:]:
        q = str(row.get("Girdi", "")).strip()[:2000]
        a = str(row.get("Cevap", "")).strip()[:2000]
        if q:
            history.append({"role": "user", "content": q})
        if a:
            history.append({"role": "assistant", "content": a})
    return history


async def show_ai_logs(update: Update, sheet_name: str) -> None:
    labels = {"ai_agnes_logs": "Agnes", "ai_gemini_logs": "Gemini", "ai_groq_logs": "Groq", "ai_web_logs": "Güncel Arama", "ai_voice_logs": "Ses", "ai_file_logs": "Dosya", "ai_image_logs": "Görsel"}
    rows = records(sheet_name)[-20:][::-1]
    if not rows:
        await edit_or_send(update, "Bu AI kaydında veri yok.", ai_logs_menu())
        return
    text = f"{labels.get(sheet_name, sheet_name)} AI Kayıtları\n\n"
    for row in rows:
        text += f"ID {row_id_text(row)} - {row.get('Tarih','-')} {row.get('Saat','')}\n"
        text += f"Girdi: {str(row.get('Girdi',''))[:180]}\n"
        text += f"Cevap: {str(row.get('Cevap',''))[:220]}\n\n"
    await edit_or_send(update, text[:MSG_LIMIT], ai_logs_menu())


async def handle_ai_log_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    if data.startswith("ailog:list:"):
        await show_ai_logs(update, data.split(":", 2)[2])
        return
    if data == "ailog:delete":
        context.user_data["flow"] = "ailog_delete"
        await edit_or_send(update, "Silmek için şu formatta yaz:\n\nsayfa ID\n\nÖrnek: groq 12\n\nSayfalar: agnes, gemini, groq, arama, ses, dosya, gorsel", back_cancel("ai:logs"))


async def handle_plant_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    if data == "plant:search":
        context.user_data["flow"] = "plant_search"
        await edit_or_send(update, "Aranacak bitki adını yaz. Örn: lavanta, monstera, rose", back_cancel("m:plant_ai"))
        return
    if data == "plant:care":
        context.user_data["flow"] = "plant_care"
        await edit_or_send(update, "Bakım bilgisi istediğin bitki adını yaz.", back_cancel("m:plant_ai"))
        return
    if data == "plant:advice":
        context.user_data["flow"] = "plant_advice"
        await edit_or_send(update, "Bitkiyle ilgili sorunu yaz. Perenual verisi + AI ile cevaplayacağım.", back_cancel("m:plant_ai"))
        return
    if data == "plant:identify":
        context.user_data["flow"] = "plant_identify"
        await edit_or_send(update, "Bitki fotoğrafını gönder. PlantNet ile tanımayı deneyeceğim (net, yakın çekim yaprak/çiçek fotoğrafı en iyi sonucu verir).", back_cancel("m:plant_ai"))


def find_inventory_by_row(row_number: int) -> dict[str, Any] | None:
    for row in records("inventory"):
        if int(row["_row"]) == row_number:
            return row
    return None


def expiring_soon_items(days_ahead: int = 14) -> list[dict[str, Any]]:
    """Son kullanma tarihine days_ahead gün ve daha az kalmış (veya süresi geçmiş) malzemeleri döner."""
    results = []
    for item in records("inventory"):
        expiry = str(item.get("Son_Kullanma", "")).strip()
        if not expiry:
            continue
        try:
            exp_date = datetime.strptime(expiry, DATE_FMT)
        except Exception:
            continue
        days_left = (exp_date.date() - now().date()).days
        if days_left <= days_ahead:
            row = dict(item)
            row["_days_left"] = days_left
            results.append(row)
    results.sort(key=lambda x: x["_days_left"])
    return results


def expiry_line(item: dict[str, Any]) -> str:
    days_left = item.get("_days_left", 0)
    durum = "süresi geçmiş" if days_left < 0 else f"{days_left} gün kaldı"
    return f"- {item.get('Malzeme / Alet', '-')}: {durum} ({item.get('Son_Kullanma', '-')})"


def find_inventory_by_name(name: str) -> dict[str, Any] | None:
    wanted = normalize_name(name)
    for row in records("inventory"):
        if normalize_name(row.get("Malzeme / Alet")) == wanted:
            return row
    for row in records("inventory"):
        if wanted in normalize_name(row.get("Malzeme / Alet")):
            return row
    return None


def set_cell_by_header(sheet_name: str, row_number: int, header: str, value: Any) -> None:
    header_row = SHEET[sheet_name].row_values(1)
    if header not in header_row:
        SHEET[sheet_name].update_cell(1, len(header_row) + 1, header)
        header_row.append(header)
    col = header_row.index(header) + 1
    SHEET[sheet_name].update_cell(row_number, col, value)
    RECORD_CACHE.pop(sheet_name, None)


def _a1(row: int, col: int) -> str:
    letters = ""
    n = col
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        letters = chr(65 + remainder) + letters
    return f"{letters}{row}"


def set_cells_by_header(sheet_name: str, row_number: int, values: dict[str, Any]) -> None:
    """Aynı satırdaki birden fazla hücreyi tek Sheets isteğiyle günceller (kota tasarrufu)."""
    if not values:
        return
    header_row = SHEET[sheet_name].row_values(1)
    updates = []
    for header, value in values.items():
        if header not in header_row:
            SHEET[sheet_name].update_cell(1, len(header_row) + 1, header)
            header_row.append(header)
        col = header_row.index(header) + 1
        updates.append({"range": _a1(row_number, col), "values": [[value]]})
    try:
        SHEET[sheet_name].batch_update(updates)
    except Exception:
        log.exception("batch_update basarisiz, tek tek deneniyor")
        for header, value in values.items():
            set_cell_by_header(sheet_name, row_number, header, value)
        return
    RECORD_CACHE.pop(sheet_name, None)


def alert_value(key: str) -> str:
    for row in records("alerts"):
        if str(row.get("Key", "")) == key:
            return str(row.get("Value", ""))
    return ""


def set_alert_value(key: str, value: str) -> None:
    for row in records("alerts"):
        if str(row.get("Key", "")) == key:
            set_cells_by_header("alerts", int(row["_row"]), {"Value": value, "UpdatedAt": now().isoformat(timespec="seconds")})
            return
    append_record("alerts", ALERT_HEADERS, {"Key": key, "Value": value, "UpdatedAt": now().isoformat(timespec="seconds")})


def add_history(islem: str, malzeme: str = "", miktar: Any = "", birim: str = "", ph: str = "", note: str = "", date: str | None = None) -> int:
    item_id = next_id("history")
    append_record("history", HISTORY_HEADERS, {
        "ID": item_id,
        "Tarih": date or today_str(),
        "Islem": islem,
        "Malzeme": malzeme,
        "Miktar": miktar,
        "Birim": birim,
        "pH": ph,
        "Not": note,
        "CreatedAt": now().isoformat(timespec="seconds"),
    })
    return item_id


def use_stock(name: str, amount: float, unit: str, op_type: str, note: str = "", date: str | None = None, ph: str = "", record_history: bool = True) -> tuple[bool, str, dict[str, Any] | None]:
    item = find_inventory_by_name(name)
    if not item:
        return False, "Malzeme bulunamadı.", None
    row_number = int(item["_row"])
    remaining_raw = str(item.get("Kalan Miktar", "")).strip()
    used_raw = str(item.get("Kullanılan", "0")).strip() or "0"
    material = str(item.get("Malzeme / Alet", name))
    old_remaining = remaining_raw

    if remaining_raw.casefold() == "stok bol":
        if record_history:
            add_history(op_type, material, format_decimal(amount), unit, ph, note, date)
        return True, "Stok bol", {"material": material, "row": row_number, "old_remaining": old_remaining, "amount": amount, "unit": unit}

    try:
        remaining = parse_decimal(remaining_raw)
        used = parse_decimal(used_raw)
    except Exception:
        return False, f"Bu malzemenin miktarı sayı değil: {remaining_raw}", None

    if amount > remaining:
        return False, f"Yetersiz stok. Kalan: {format_decimal(remaining)} {item.get('Birim', unit)}", None

    new_remaining = remaining - amount
    new_used = used + amount
    set_cells_by_header("inventory", row_number, {"Kalan Miktar": format_decimal(new_remaining), "Kullanılan": format_decimal(new_used)})
    if record_history:
        add_history(op_type, material, format_decimal(amount), unit, ph, note, date)
    return True, f"{format_decimal(new_remaining)} {item.get('Birim', unit)}", {"material": material, "row": row_number, "old_remaining": old_remaining, "amount": amount, "unit": unit}


def check_stock_available(name: str, amount: float) -> tuple[bool, str]:
    item = find_inventory_by_name(name)
    if not item:
        return False, f"{name} bulunamadı."
    remaining_raw = str(item.get("Kalan Miktar", "")).strip()
    if remaining_raw.casefold() == "stok bol":
        return True, ""
    try:
        remaining = parse_decimal(remaining_raw)
    except Exception:
        return False, f"{name} miktarı sayı değil: {remaining_raw}"
    if amount > remaining:
        return False, f"{name} için yetersiz stok. Kalan: {format_decimal(remaining)} {item.get('Birim', '')}"
    return True, ""


def inventory_buttons(action: str, page: int = 0) -> InlineKeyboardMarkup:
    items = records("inventory")
    page_size = 8
    start = page * page_size
    rows: list[list[tuple[str, str]]] = []
    for item in items[start:start + page_size]:
        name = str(item.get("Malzeme / Alet", "Adsız"))[:32]
        rows.append([(name, f"inv:{action}:{item['_row']}")])
    nav = []
    if page > 0:
        nav.append(("Önceki", f"invpage:{action}:{page - 1}"))
    if len(items) > start + page_size:
        nav.append(("Sonraki", f"invpage:{action}:{page + 1}"))
    if nav:
        rows.append(nav)
    if action == "compadd":
        rows.append([("Malzeme Kullanmadım / Devam Et", "compadd:done")])
        rows.append([("Geri", "m:compost"), ("İptal", "cancel"), ("Ana Menü", "m:main")])
    elif action == "planadd":
        rows.append([("Malzeme Kullanmayacağım / Devam Et", "planadd:done")])
        rows.append([("Geri", "m:plan"), ("İptal", "cancel"), ("Ana Menü", "m:main")])
    elif action == "recipeadd":
        rows.append([("Geri", "m:recipes"), ("İptal", "cancel"), ("Ana Menü", "m:main")])
    elif action == "essoil":
        rows.append([("Geri", "m:essence"), ("İptal", "cancel"), ("Ana Menü", "m:main")])
    else:
        rows.append([("Geri", "m:stock"), ("İptal", "cancel"), ("Ana Menü", "m:main")])
    return kb(rows)


def teneke_buttons(action: str) -> InlineKeyboardMarkup:
    fixed = ["Konteyner 1", "Konteyner 2", "Konteyner 3"] + [str(i) for i in range(1, 21)]
    tenekeler = sorted({str(r.get("Teneke_No", "")).strip() for r in records("ph_records") if str(r.get("Teneke_No", "")).strip()}, key=lambda x: int(x) if x.isdigit() else 999999)
    tenekeler = fixed + [t for t in tenekeler if t not in fixed]
    rows: list[list[tuple[str, str]]] = []
    line: list[tuple[str, str]] = []
    for teneke in tenekeler[:40]:
        line.append((teneke, f"teneke:{action}:{teneke}"))
        if len(line) == 4:
            rows.append(line)
            line = []
    if line:
        rows.append(line)
    rows.append([("Teneke Yaz", f"teneke:{action}:custom")])
    rows.append([("Geri", "m:ph"), ("İptal", "cancel"), ("Ana Menü", "m:main")])
    return kb(rows)


def row_id_text(row: dict[str, Any]) -> str:
    return str(row.get("ID") or row.get("_id") or "?")


def history_material(row: dict[str, Any]) -> str:
    if row.get("Malzeme"):
        return str(row.get("Malzeme"))
    old = str(row.get("Kullanilan_Malzeme_Miktar") or row.get("Kullanılan_Malzeme_Miktar") or "").strip()
    parts = old.split()
    if len(parts) >= 3:
        return " ".join(parts[2:])
    return old


def history_amount(row: dict[str, Any]) -> str:
    if row.get("Miktar"):
        return str(row.get("Miktar"))
    old = str(row.get("Kullanilan_Malzeme_Miktar") or row.get("Kullanılan_Malzeme_Miktar") or "").strip()
    parts = old.split()
    return parts[0] if parts else ""


def history_unit(row: dict[str, Any]) -> str:
    if row.get("Birim"):
        return str(row.get("Birim"))
    old = str(row.get("Kullanilan_Malzeme_Miktar") or row.get("Kullanılan_Malzeme_Miktar") or "").strip()
    parts = old.split()
    return parts[1] if len(parts) >= 2 else ""


def parse_material_summary(summary: Any) -> list[dict[str, Any]]:
    text = str(summary or "").strip()
    if not text or text in {"-", "Malzeme kullanılmadı"}:
        return []
    items = []
    for part in text.split(";"):
        bits = part.strip().split()
        if len(bits) < 3:
            continue
        try:
            amount = parse_decimal(bits[0])
        except Exception:
            continue
        items.append({"amount": amount, "unit": bits[1], "material": " ".join(bits[2:])})
    return items


def operational_records() -> list[dict[str, Any]]:
    rows = []
    for row in records("history"):
        item = dict(row)
        item["_source"] = "Geçmiş"
        rows.append(item)
    for row in records("Kompost"):
        item = dict(row)
        item["_source"] = "Kompost"
        rows.append(item)
    return rows


async def show_home(update: Update) -> None:
    await edit_or_send(update, "Yasemin Asistan\n\nBir işlem seç:", main_menu())


async def show_status(update: Update) -> None:
    def ok(value: bool) -> str:
        return "Hazır" if value else "Eksik"

    counts = {}
    for name in ["inventory", "history", "Kompost", "ph_records", "reminders", "observations", "plans", "areas", "recipes", "issues", "diary", "essences"]:
        try:
            counts[name] = len(records(name))
        except Exception:
            counts[name] = "?"
    waiting_reminders = "?"
    try:
        waiting_reminders = sum(1 for r in records("reminders") if str(r.get("Durum", "bekliyor")).casefold() == "bekliyor")
    except Exception:
        pass
    critical_stock = []
    try:
        for item in records("inventory"):
            remaining_raw = str(item.get("Kalan Miktar", "")).strip()
            if not remaining_raw or remaining_raw.casefold() == "stok bol":
                continue
            remaining = parse_decimal(remaining_raw)
            if remaining <= 0:
                critical_stock.append(f"- {item.get('Malzeme / Alet', '-')}: bitti")
            elif remaining <= 5:
                critical_stock.append(f"- {item.get('Malzeme / Alet', '-')}: {format_decimal(remaining)} {item.get('Birim', '')}")
    except Exception:
        critical_stock = []
    ph_warnings = []
    try:
        latest_by_teneke: dict[str, dict[str, Any]] = {}
        for row in records("ph_records"):
            teneke = str(row.get("Teneke_No", "")).strip()
            if teneke:
                latest_by_teneke[teneke] = row
        for teneke, row in latest_by_teneke.items():
            ph_value = parse_decimal(row.get("pH", ""))
            if ph_value < 5.5 or ph_value > 7.5:
                ph_warnings.append(f"- {teneke}: pH {format_decimal(ph_value)} ({row.get('Tarih', '-')})")
    except Exception:
        ph_warnings = []

    text = (
        "Bot Durumu\n\n"
        f"Google Sheets: {ok(bool(SHEET))}\n"
        f"Agnes AI: {ok(bool(AGNES_API_KEY))} ({AGNES_MODEL})\n"
        f"Gemini: {ok(bool(GEMINI_API_KEY))} ({GEMINI_MODEL})\n"
        "Hatırlatma kontrolü: 15 saniyede bir\n\n"
        "Kayıt Sayıları\n"
        f"Stok: {counts['inventory']}\n"
        f"Geçmiş: {counts['history']}\n"
        f"Kompost: {counts['Kompost']}\n"
        f"pH: {counts['ph_records']}\n"
        f"Hatırlatma: {counts['reminders']} (bekleyen: {waiting_reminders})\n"
        f"Gözlem: {counts['observations']}\n"
        f"Plan: {counts['plans']}\n"
        f"Alan: {counts['areas']}\n"
        f"Reçete: {counts['recipes']}\n"
        f"Sorun: {counts['issues']}\n"
        f"Günlük: {counts['diary']}\n"
        f"Esans: {counts['essences']}\n"
    )
    if critical_stock:
        text += "\nKritik Stok\n" + "\n".join(critical_stock[:12])
        if len(critical_stock) > 12:
            text += f"\n... ve {len(critical_stock) - 12} kayıt daha"
    else:
        text += "\nKritik stok görünmüyor."
    if ph_warnings:
        text += "\n\npH Dikkat\n" + "\n".join(ph_warnings[:12])
        if len(ph_warnings) > 12:
            text += f"\n... ve {len(ph_warnings) - 12} kayıt daha"
    else:
        text += "\n\npH dikkat uyarısı yok."
    try:
        expiring = expiring_soon_items()
    except Exception:
        expiring = []
    if expiring:
        text += "\n\nSon Kullanma Tarihi Yaklaşan\n" + "\n".join(expiry_line(x) for x in expiring[:12])
        if len(expiring) > 12:
            text += f"\n... ve {len(expiring) - 12} kayıt daha"
    else:
        text += "\n\nYaklaşan son kullanma tarihi yok."
    await edit_or_send(update, text, main_menu())


async def show_today(update: Update) -> None:
    date = today_str()
    ops = [r for r in operational_records() if parse_date(str(r.get("Tarih", ""))) == date]
    plans = [r for r in records("plans") if parse_date(str(r.get("Tarih", ""))) == date and str(r.get("Durum", "bekliyor")).casefold() == "bekliyor"]
    reminders = [r for r in records("reminders") if parse_date(str(r.get("Tarih", ""))) == date and str(r.get("Durum", "bekliyor")).casefold() == "bekliyor"]
    issues = [r for r in records("issues") if str(r.get("Durum", "açık")).casefold() == "açık"]
    ess_due = [r for r in records("essences") if str(r.get("Durum", "aktif")).casefold() == "aktif" and essence_due(r)]
    critical = []
    for item in records("inventory"):
        raw = str(item.get("Kalan Miktar", "")).strip()
        if not raw or raw.casefold() == "stok bol":
            continue
        try:
            if parse_decimal(raw) <= 5:
                critical.append(f"{item.get('Malzeme / Alet','-')} ({raw} {item.get('Birim','')})")
        except Exception:
            pass
    expiring = expiring_soon_items()
    text = f"Bugün - {date}\n\n"
    text += f"İşlem: {len(ops)}\nPlan: {len(plans)}\nHatırlatma: {len(reminders)}\nAçık sorun: {len(issues)}\nSüresi gelen esans: {len(ess_due)}\nKritik stok: {len(critical)}\nYaklaşan SKT: {len(expiring)}\n"
    if plans:
        text += "\nPlanlar\n" + "\n".join(f"- ID {row_id_text(r)} {r.get('Islem','-')} / {r.get('Hedef','-')}" for r in plans[:8])
    if reminders:
        text += "\n\nHatırlatmalar\n" + "\n".join(f"- ID {row_id_text(r)} {r.get('Saat','-')} {r.get('Metin','-')}" for r in reminders[:8])
    if ess_due:
        text += "\n\nEsans\n" + "\n".join(f"- ID {row_id_text(r)} {r.get('Cicek','-')} / {r.get('Kap','-')}" for r in ess_due[:8])
    if critical:
        text += "\n\nKritik Stok\n" + "\n".join(f"- {x}" for x in critical[:8])
    if expiring:
        text += "\n\nSon Kullanma Tarihi Yaklaşan\n" + "\n".join(expiry_line(x) for x in expiring[:8])
    await edit_or_send(update, text[:MSG_LIMIT], main_menu())


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    if update.effective_chat:
        set_alert_value("stock_chat_id", str(update.effective_chat.id))
    await show_home(update)
    if update.effective_message:
        await update.effective_message.reply_text(
            "Aşağıdaki Menü butonu her zaman burada duracak, istediğin an dokunup ana menüye dönebilirsin.",
            reply_markup=persistent_menu_kb(),
        )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await edit_or_send(update, "İşlem iptal edildi.\n\nAna menü:", main_menu())


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data or ""

    if data == "noop":
        return
    if data == "cancel":
        await cancel(update, context)
        return
    if data == "m:main":
        context.user_data.clear()
        await show_home(update)
        return
    if data == "m:today":
        context.user_data.clear()
        await show_today(update)
        return
    if data == "m:plant_ai":
        context.user_data.clear()
        await edit_or_send(update, "Bitki AI", plant_ai_menu())
        return
    if data == "g:records":
        context.user_data.clear()
        await edit_or_send(update, "Kayıtlar", records_group_menu())
        return
    if data == "g:garden":
        context.user_data.clear()
        await edit_or_send(update, "Bahçe", garden_group_menu())
        return
    if data == "g:production":
        context.user_data.clear()
        await edit_or_send(update, "Üretim", production_group_menu())
        return
    if data == "g:ai":
        context.user_data.clear()
        await edit_or_send(update, "AI", ai_group_menu())
        return
    if data == "g:system":
        context.user_data.clear()
        await edit_or_send(update, "Sistem", system_group_menu())
        return
    if data == "m:stock":
        context.user_data.clear()
        await edit_or_send(update, "Stok Yönetimi", stock_menu())
        return
    if data == "m:ph":
        context.user_data.clear()
        await edit_or_send(update, "pH Yönetimi", ph_menu())
        return
    if data == "m:history":
        context.user_data.clear()
        await edit_or_send(update, "Geçmiş Yönetimi", history_menu())
        return
    if data == "m:compost":
        context.user_data.clear()
        await edit_or_send(update, "Kompost", compost_menu())
        return
    if data == "m:plan":
        context.user_data.clear()
        await edit_or_send(update, "Plan", plan_menu())
        return
    if data == "m:areas":
        context.user_data.clear()
        await edit_or_send(update, "Alanlar", area_menu())
        return
    if data == "m:recipes":
        context.user_data.clear()
        await edit_or_send(update, "Reçeteler", recipe_menu())
        return
    if data == "m:issues":
        context.user_data.clear()
        await edit_or_send(update, "Sorun Takibi", issue_menu())
        return
    if data == "m:diary":
        context.user_data.clear()
        await edit_or_send(update, "Günlük", diary_menu())
        return
    if data == "m:essence":
        context.user_data.clear()
        await edit_or_send(update, "Esans Takibi", essence_menu())
        return
    if data == "m:report":
        context.user_data.clear()
        await edit_or_send(update, "Raporlar", report_menu())
        return
    if data == "m:reminder":
        context.user_data.clear()
        await edit_or_send(update, "Hatırlatmalar", reminder_menu())
        return
    if data == "m:observation":
        context.user_data.clear()
        await edit_or_send(update, "Gözlem", observation_menu())
        return
    if data == "m:status":
        context.user_data.clear()
        await show_status(update)
        return
    if data == "m:weather":
        context.user_data.clear()
        await edit_or_send(update, "Hava Durumu", weather_menu())
        return
    if data == "m:ai":
        context.user_data.pop("flow", None)
        await edit_or_send(update, "Hangi yapay zekaya sormak istersin?", ai_menu())
        return
    if data == "ai:agnes":
        context.user_data["flow"] = "ai_agnes"
        await edit_or_send(update, "Agnes AI'ya sormak istediğin şeyi yaz.", back_cancel("m:ai"))
        return
    if data == "ai:gemini":
        context.user_data["flow"] = "ai_gemini"
        await edit_or_send(update, "Gemini'ye sormak istediğin şeyi yaz.", back_cancel("m:ai"))
        return
    if data == "ai:groq":
        context.user_data["flow"] = "ai_groq"
        await edit_or_send(update, "Groq hızlı modele sormak istediğin şeyi yaz.", back_cancel("m:ai"))
        return
    if data == "ai:web":
        context.user_data["flow"] = "ai_web"
        await edit_or_send(update, "Güncel arama yapmak istediğin konuyu yaz.", back_cancel("m:ai"))
        return
    if data == "ai:voice":
        context.user_data["flow"] = "ai_voice"
        await edit_or_send(update, "Sesli mesaj gönder. Groq Whisper metne çevirecek, ardından AI cevaplayacak.", back_cancel("m:ai"))
        return
    if data == "ai:file":
        context.user_data["flow"] = "ai_file"
        await edit_or_send(update, "PDF/TXT/MD/CSV dosyası gönder. Özetleyip hafızaya kaydedeceğim.", back_cancel("m:ai"))
        return
    if data == "ai:docq":
        context.user_data["flow"] = "ai_docq"
        await edit_or_send(update, "Kaydedilmiş dosyalarla ilgili sorunu yaz.", back_cancel("m:ai"))
        return
    if data == "ai:records":
        context.user_data["flow"] = "ai_records"
        await edit_or_send(update, "Stok, geçmiş, pH, plan, sorun, esans, günlük ve hatırlatma kayıtlarına bakarak cevap vereceğim. Sorunu yaz.\n\nÖrn: bu ay en çok neyi kullandım, teneke 3'ün son pH'ı ne, açık sorun var mı", back_cancel("m:ai"))
        return
    if data == "ai:logs":
        await edit_or_send(update, "AI kayıtları", ai_logs_menu())
        return
    if data == "ai:both":
        context.user_data["flow"] = "ai_both"
        await edit_or_send(update, "Aynı soruyu Agnes ve Gemini'ye soracağım. Sorunu yaz.", back_cancel("m:ai"))
        return
    if data == "ai:clear":
        context.user_data.pop("ai_history", None)
        context.user_data.pop("gemini_history", None)
        context.user_data.pop("groq_history", None)
        context.user_data["ai_memory_cleared"] = True
        await edit_or_send(update, "AI konuşma hafızası temizlendi.", ai_menu())
        return

    if data == "stock:delete_confirm":
        await handle_stock_flow_callback(update, context, data)
        return
    if data.startswith("stock:"):
        await handle_stock_callback(update, context, data)
        return
    if data.startswith("inv:") or data.startswith("invpage:"):
        await handle_inventory_callback(update, context, data)
        return
    if data.startswith("cat:") or data.startswith("unit:") or data.startswith("use:"):
        await handle_stock_flow_callback(update, context, data)
        return
    if data.startswith("ph:") or data.startswith("teneke:"):
        await handle_ph_callback(update, context, data)
        return
    if data.startswith("hist:") or data.startswith("histadd:"):
        await handle_history_callback(update, context, data)
        return
    if data.startswith("comp:") or data.startswith("compadd:"):
        await handle_compost_callback(update, context, data)
        return
    if data.startswith("plan:") or data.startswith("planadd:"):
        await handle_plan_callback(update, context, data)
        return
    if data.startswith("area:") or data.startswith("area_select:"):
        await handle_area_callback(update, context, data)
        return
    if data.startswith("recipe:") or data.startswith("recipeadd:"):
        await handle_recipe_callback(update, context, data)
        return
    if data.startswith("ailog:"):
        await handle_ai_log_callback(update, context, data)
        return
    if data.startswith("plant:"):
        await handle_plant_callback(update, context, data)
        return
    if data.startswith("issue:"):
        await handle_issue_callback(update, context, data)
        return
    if data.startswith("diary:"):
        await handle_diary_callback(update, context, data)
        return
    if data.startswith("ess:"):
        await handle_essence_callback(update, context, data)
        return
    if data.startswith("report:"):
        await handle_report_callback(update, context, data)
        return
    if data.startswith("rem:"):
        await handle_reminder_callback(update, context, data)
        return
    if data.startswith("obs:"):
        await handle_observation_callback(update, context, data)
        return
    if data.startswith("weather:") or data.startswith("weathernow:") or data.startswith("weathermonth:"):
        await handle_weather_callback(update, context, data)
        return
    if data == "backup":
        await send_backup(update, context)
        return
    if data == "search:start":
        context.user_data["flow"] = "quick_search"
        await edit_or_send(update, "Aramak istediğin kelimeyi yaz. Örn: lavanta", back_cancel("g:system"))
        return
    if data == "qlog:confirm":
        pending = context.user_data.pop("quick_log_pending", None)
        if not pending:
            await edit_or_send(update, "Onaylanacak bir kayıt yok.", main_menu())
            return
        await execute_quick_log(update, pending)
        return
    if data == "qlog:cancel":
        context.user_data.pop("quick_log_pending", None)
        await edit_or_send(update, "İptal edildi.", main_menu())
        return


async def handle_stock_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    if data == "stock:list":
        items = records("inventory")
        if not items:
            await edit_or_send(update, "Stok listesi boş.", stock_menu())
            return
        text = "Stok Listesi\n\n"
        for item in items:
            text += f"ID {row_id_text(item)} - {item.get('Malzeme / Alet', '-')}: {item.get('Kalan Miktar', '-')} {item.get('Birim', '')}\n"
        await edit_or_send(update, text[:MSG_LIMIT], stock_menu())
        if len(text) > MSG_LIMIT and update.effective_message:
            for part in chunks(text)[1:]:
                await update.effective_message.reply_text(part)
        return
    if data == "stock:search":
        context.user_data["flow"] = "stock_search"
        await edit_or_send(update, "Malzeme adını yaz veya listeden seç:", inventory_buttons("search"))
        return
    if data == "stock:add":
        context.user_data["flow"] = "stock_add"
        context.user_data["draft"] = {}
        await edit_or_send(update, "Kategori seç:", category_menu())
        return
    if data == "stock:delete":
        await edit_or_send(update, "Silmek istediğin malzemeyi seç:", inventory_buttons("delete"))
        return
    if data == "stock:use":
        context.user_data["flow"] = "stock_use"
        context.user_data["draft"] = {}
        await edit_or_send(update, "Stoktan düşülecek malzemeyi seç:", inventory_buttons("use"))
        return
    if data == "stock:undo":
        undo = context.user_data.get("last_stock_use")
        if not undo:
            await edit_or_send(update, "Geri alınacak stok düşme işlemi yok.", stock_menu())
            return
        set_cell_by_header("inventory", int(undo["row"]), "Kalan Miktar", undo["old_remaining"])
        add_history("GERİ ALINDI", undo["material"], undo["amount"], undo["unit"], "", "Son stok düşme işlemi geri alındı")
        context.user_data.pop("last_stock_use", None)
        await edit_or_send(update, f"Geri alındı.\n{undo['material']} stoğu tekrar {undo['old_remaining']} oldu.", stock_menu())
    if data == "stock:critical":
        text = "Kritik Stok\n\n"
        found = False
        for item in records("inventory"):
            raw = str(item.get("Kalan Miktar", "")).strip()
            if not raw or raw.casefold() == "stok bol":
                continue
            try:
                kalan = parse_decimal(raw)
            except Exception:
                continue
            if kalan <= 5:
                found = True
                text += f"ID {row_id_text(item)} - {item.get('Malzeme / Alet','-')}: {format_decimal(kalan)} {item.get('Birim','')}\n"
        await edit_or_send(update, text if found else "Kritik stok yok.", stock_menu())


async def handle_inventory_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    if data.startswith("invpage:"):
        _, action, page = data.split(":")
        await edit_or_send(update, "Malzeme seç:", inventory_buttons(action, int(page)))
        return
    _, action, row_s = data.split(":")
    item = find_inventory_by_row(int(row_s))
    if not item:
        await edit_or_send(update, "Malzeme bulunamadı.", stock_menu())
        return
    if action == "search":
        name = item.get("Malzeme / Alet", "-")
        hist = [r for r in records("history") if normalize_name(history_material(r)) == normalize_name(name)]
        text = (
            f"Malzeme Detayı\n\n"
            f"ID: {row_id_text(item)}\n"
            f"Ad: {name}\n"
            f"Kategori: {item.get('Kategori', '-')}\n"
            f"Kalan: {item.get('Kalan Miktar', '-')} {item.get('Birim', '')}\n"
            f"Kullanılan: {item.get('Kullanılan', '-')}\n"
            f"Görev/Not: {item.get('Görevi / Not', '-')}\n\n"
            f"Son kullanımlar:\n"
        )
        for row in hist[-5:][::-1]:
            text += f"ID {row_id_text(row)} - {row.get('Tarih', '-')}: {row.get('Islem', '-')} {history_amount(row)} {history_unit(row)} - {row.get('Not', '')}\n"
        await edit_or_send(update, text, stock_menu())
        return
    if action == "delete":
        context.user_data["delete_row"] = int(row_s)
        await edit_or_send(update, f"{item.get('Malzeme / Alet')} silinsin mi?", kb([[("Evet, sil", "stock:delete_confirm"), ("Vazgeç", "m:stock")]]))
        return
    if action == "use":
        context.user_data["draft"] = {"material": item.get("Malzeme / Alet"), "unit": item.get("Birim", "")}
        context.user_data["flow"] = "stock_use_amount"
        await edit_or_send(update, f"Malzeme: {item.get('Malzeme / Alet')}\nMiktar yaz. Örn: 25", back_cancel("stock:use"))
        return


async def handle_stock_flow_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    if data == "stock:delete_confirm":
        row_num = context.user_data.get("delete_row")
        item = find_inventory_by_row(int(row_num)) if row_num else None
        if not item:
            await edit_or_send(update, "Silinecek malzeme bulunamadı.", stock_menu())
            return
        SHEET["inventory"].delete_rows(int(row_num))
        RECORD_CACHE.pop("inventory", None)
        add_history("ENVANTERDEN SİLİNDİ", item.get("Malzeme / Alet", ""), "", item.get("Birim", ""), "", "Malzeme silindi")
        context.user_data.pop("delete_row", None)
        await edit_or_send(update, "Malzeme silindi.", stock_menu())
        return
    if data.startswith("cat:"):
        context.user_data.setdefault("draft", {})["category"] = data.split(":", 1)[1]
        context.user_data["flow"] = "stock_add_name"
        await edit_or_send(update, "Malzeme adını yaz:", back_cancel("stock:add"))
        return
    if data.startswith("unit:"):
        context.user_data.setdefault("draft", {})["unit"] = data.split(":", 1)[1]
        context.user_data["flow"] = "stock_add_note"
        await edit_or_send(update, "Görev/Not yaz. Boş bırakmak için '-' yazabilirsin.", back_cancel("stock:add"))
        return
    if data.startswith("use:tur:"):
        context.user_data.setdefault("draft", {})["type"] = data.split(":", 2)[2]
        context.user_data["flow"] = "stock_use_note"
        await edit_or_send(update, "İsteğe bağlı not yaz. Not yoksa '-' yaz.", back_cancel("stock:use"))


async def handle_ph_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    if data == "ph:last":
        await edit_or_send(update, "Teneke seç:", teneke_buttons("last"))
        return
    if data == "ph:one":
        await edit_or_send(update, "Teneke seç:", teneke_buttons("one"))
        return
    if data == "ph:all":
        rows_by_teneke: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in records("ph_records"):
            rows_by_teneke[str(row.get("Teneke_No", "Bilinmiyor"))].append(row)
        if not rows_by_teneke:
            await edit_or_send(update, "pH kaydı yok.", ph_menu())
            return
        text = "Tüm Tenekelerin Son 5 pH Kaydı\n\n"
        for teneke in sorted(rows_by_teneke, key=lambda x: int(x) if x.isdigit() else 999999):
            text += f"Teneke {teneke}\n"
            for row in rows_by_teneke[teneke][-5:][::-1]:
                text += f"ID {row_id_text(row)} - {row.get('Tarih', '-')}: pH {row.get('pH', '-')}"
                if row.get("Not"):
                    text += f" - {row.get('Not')}"
                text += "\n"
            text += "\n"
        await edit_or_send(update, text[:MSG_LIMIT], ph_menu())
        if len(text) > MSG_LIMIT and update.effective_message:
            for part in chunks(text)[1:]:
                await update.effective_message.reply_text(part)
        return
    if data == "ph:add":
        context.user_data["draft"] = {}
        await edit_or_send(update, "Teneke veya konteyner seç:", teneke_buttons("add"))
        return
    if data == "ph:delete":
        await edit_or_send(update, "pH kaydı nasıl silinsin?", kb([
            [("ID ile sil", "ph:delete_id")],
            [("Teneke seçip son kaydı sil", "ph:delete_last")],
            [("Geri", "m:ph"), ("İptal", "cancel"), ("Ana Menü", "m:main")],
        ]))
        return
    if data == "ph:delete_id":
        context.user_data["flow"] = "ph_delete"
        await edit_or_send(update, "Silmek istediğin pH kaydının ID numarasını yaz.", back_cancel("m:ph"))
        return
    if data == "ph:delete_last":
        await edit_or_send(update, "Son pH kaydı silinecek tenekeyi seç:", teneke_buttons("delete_last"))
        return
    if data.startswith("teneke:"):
        _, action, teneke = data.split(":", 2)
        if teneke == "custom":
            context.user_data["flow"] = f"ph_{action}_custom"
            await edit_or_send(update, "Teneke numarasını yaz:", back_cancel("m:ph"))
            return
        if action == "add":
            context.user_data["draft"] = {"teneke": teneke}
            context.user_data["flow"] = "ph_add_value"
            await edit_or_send(update, f"{teneke}\n\npH değerini yaz. Örn: 6.5", back_cancel("m:ph"))
            return
        if action == "delete_last":
            await delete_last_ph_for_teneke(update, teneke)
            return
        await show_ph_for_teneke(update, teneke, action)


async def show_ph_for_teneke(update: Update, teneke: str, action: str) -> None:
    rows = [r for r in records("ph_records") if str(r.get("Teneke_No", "")).strip() == str(teneke)]
    if not rows:
        await edit_or_send(update, f"Teneke {teneke} için pH kaydı yok.", ph_menu())
        return
    if action == "last":
        row = rows[-1]
        text = f"Teneke {teneke} - Son pH\n\nID {row_id_text(row)}\nTarih: {row.get('Tarih', '-')}\npH: {row.get('pH', '-')}\nNot: {row.get('Not', '-')}"
    else:
        text = f"Teneke {teneke} - Tüm pH Kayıtları\n\n"
        for row in rows:
            text += f"ID {row_id_text(row)} - {row.get('Tarih', '-')}: pH {row.get('pH', '-')}"
            if row.get("Not"):
                text += f" - {row.get('Not')}"
            text += "\n"
    await edit_or_send(update, text, ph_menu())


async def delete_last_ph_for_teneke(update: Update, teneke: str) -> None:
    rows = [r for r in records("ph_records") if str(r.get("Teneke_No", "")).strip() == str(teneke)]
    if not rows:
        await edit_or_send(update, f"Teneke {teneke} için silinecek pH kaydı yok.", ph_menu())
        return
    row = rows[-1]
    SHEET["ph_records"].delete_rows(int(row["_row"]))
    RECORD_CACHE.pop("ph_records", None)
    await edit_or_send(update, f"Silindi: Teneke {teneke}, ID {row_id_text(row)}, pH {row.get('pH', '-')}", ph_menu())


async def handle_history_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    if data == "hist:last10":
        await show_history(update, 10)
        return
    if data == "hist:last30":
        await show_history_page(update, 0)
        return
    if data.startswith("hist:all:"):
        try:
            page = int(data.rsplit(":", 1)[1])
        except ValueError:
            page = 0
        await show_history_page(update, page)
        return
    if data == "hist:file":
        await send_history_file(update)
        return
    if data == "hist:date":
        context.user_data["flow"] = "history_date"
        await edit_or_send(update, "Tarih yaz. Örn: 14-06-2026 veya 2026-06-14", back_cancel("m:history"))
        return
    if data == "hist:delete":
        context.user_data["flow"] = "history_delete"
        await edit_or_send(update, "Silmek istediğin işlem ID numarasını yaz.", back_cancel("m:history"))
        return
    if data == "hist:add":
        context.user_data["flow"] = "histadd_date"
        context.user_data["draft"] = {"items": []}
        await edit_or_send(update, "İşlem tarihi seç:", date_choice_menu("histadd"))
        return
    if data.startswith("histadd:date:"):
        choice = data.rsplit(":", 1)[1]
        if choice == "custom":
            context.user_data["flow"] = "histadd_custom_date"
            await edit_or_send(update, "Özel tarihi yaz. Örn: 14-06-2026", back_cancel("hist:add"))
            return
        context.user_data.setdefault("draft", {})["date"] = today_str() if choice == "today" else (now() - timedelta(days=1)).strftime(DATE_FMT)
        await edit_or_send(update, "İşlem türü seç:", operation_type_menu("histadd"))
        return
    if data.startswith("histadd:tur:"):
        context.user_data.setdefault("draft", {})["type"] = data.split(":", 2)[2]
        await edit_or_send(update, "Malzeme seç:", inventory_buttons("histadd"))
        return
    if data == "histadd:more":
        await edit_or_send(update, "Eklemek istediğin diğer malzemeyi seç:", inventory_buttons("histadd"))
        return
    if data == "histadd:done":
        items = context.user_data.get("draft", {}).get("items", [])
        if not items:
            await edit_or_send(update, "Devam etmek için en az bir malzeme eklemelisin.", inventory_buttons("histadd"))
            return
        await edit_or_send(update, "pH seç:", ph_choice_menu())
        return
    if data == "histadd:ph_custom":
        context.user_data["flow"] = "histadd_custom_ph"
        await edit_or_send(update, "pH değerini yaz. Örn: 6.3", back_cancel("m:history"))
        return
    if data.startswith("histadd:ph:"):
        context.user_data.setdefault("draft", {})["ph"] = data.split(":", 2)[2]
        context.user_data["flow"] = "histadd_note"
        await edit_or_send(update, "Not yaz. Ne için yaptığını buraya yazabilirsin. Not yoksa '-' yaz.", back_cancel("m:history"))
        return


async def handle_compost_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    if data.startswith("comp:all:"):
        try:
            page = int(data.rsplit(":", 1)[1])
        except ValueError:
            page = 0
        await show_compost_page(update, page)
        return
    if data == "comp:file":
        await send_compost_file(update)
        return
    if data == "comp:add":
        context.user_data["flow"] = "compadd_date"
        context.user_data["draft"] = {"items": [], "containers": []}
        await edit_or_send(update, "Kompost işlem tarihi seç:", date_choice_menu("compadd"))
        return
    if data == "comp:date":
        context.user_data["flow"] = "compost_date"
        await edit_or_send(update, "Tarih yaz. Örn: 14-06-2026 veya 2026-06-14", back_cancel("m:compost"))
        return
    if data == "comp:delete":
        context.user_data["flow"] = "compost_delete"
        await edit_or_send(update, "Silmek istediğin Kompost işlem ID numarasını yaz.", back_cancel("m:compost"))
        return
    if data.startswith("compadd:date:"):
        choice = data.rsplit(":", 1)[1]
        if choice == "custom":
            context.user_data["flow"] = "compadd_custom_date"
            await edit_or_send(update, "Özel tarihi yaz. Örn: 14-06-2026", back_cancel("comp:add"))
            return
        context.user_data.setdefault("draft", {"items": [], "containers": []})["date"] = today_str() if choice == "today" else (now() - timedelta(days=1)).strftime(DATE_FMT)
        await edit_or_send(update, "Konteyner seç. Birden fazla seçebilirsin:", compost_container_menu(context.user_data["draft"].get("containers", [])))
        return
    if data.startswith("compadd:container:"):
        container = data.split(":", 2)[2]
        draft = context.user_data.setdefault("draft", {"items": [], "containers": []})
        containers = draft.setdefault("containers", [])
        if container in containers:
            containers.remove(container)
        else:
            containers.append(container)
        await edit_or_send(update, "Konteyner seç. Birden fazla seçebilirsin:", compost_container_menu(containers))
        return
    if data == "compadd:containers_done":
        containers = context.user_data.get("draft", {}).get("containers", [])
        if not containers:
            await edit_or_send(update, "Devam etmek için en az bir konteyner seçmelisin.", compost_container_menu([]))
            return
        await edit_or_send(update, "Kompost işlem türü seç:", compost_type_menu())
        return
    if data.startswith("compadd:tur:"):
        context.user_data.setdefault("draft", {"items": [], "containers": []})["type"] = data.split(":", 2)[2]
        await edit_or_send(update, "Malzeme seç:", inventory_buttons("compadd"))
        return
    if data == "compadd:more":
        await edit_or_send(update, "Eklemek istediğin diğer malzemeyi seç:", inventory_buttons("compadd"))
        return
    if data == "compadd:done":
        await edit_or_send(update, "pH seç:", ph_choice_menu("compadd"))
        return
    if data == "compadd:ph_custom":
        context.user_data["flow"] = "compadd_custom_ph"
        await edit_or_send(update, "pH değerini yaz. Örn: 6.8", back_cancel("m:compost"))
        return
    if data.startswith("compadd:ph:"):
        context.user_data.setdefault("draft", {})["ph"] = data.split(":", 2)[2]
        context.user_data["flow"] = "compadd_note"
        await edit_or_send(update, "Not yaz. Not yoksa '-' yaz.", back_cancel("m:compost"))
        return


async def handle_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    if data == "plan:add":
        context.user_data["flow"] = "planadd_date"
        context.user_data["draft"] = {"items": []}
        await edit_or_send(update, "Plan tarihi seç:", date_choice_menu("planadd"))
        return
    if data == "plan:upcoming":
        await show_plans(update)
        return
    if data == "plan:date":
        context.user_data["flow"] = "plan_date"
        await edit_or_send(update, "Plan tarihini yaz. Örn: 14-06-2026 veya 2026-06-14", back_cancel("m:plan"))
        return
    if data == "plan:delete":
        context.user_data["flow"] = "plan_delete"
        await edit_or_send(update, "Silmek istediğin plan ID numarasını yaz.", back_cancel("m:plan"))
        return
    if data == "plan:complete":
        context.user_data["flow"] = "plan_complete"
        await edit_or_send(update, "Tamamlanan plan ID numarasını yaz.", back_cancel("m:plan"))
        return
    if data.startswith("planadd:date:"):
        choice = data.rsplit(":", 1)[1]
        if choice == "custom":
            context.user_data["flow"] = "planadd_custom_date"
            await edit_or_send(update, "Özel tarihi yaz. Örn: 14-06-2026", back_cancel("plan:add"))
            return
        context.user_data.setdefault("draft", {"items": []})["date"] = today_str() if choice == "today" else (now() - timedelta(days=1)).strftime(DATE_FMT)
        await edit_or_send(update, "Plan işlem türü seç:", operation_type_menu("planadd"))
        return
    if data.startswith("planadd:tur:"):
        context.user_data.setdefault("draft", {"items": []})["type"] = data.split(":", 2)[2]
        await edit_or_send(update, "Hedef/alan seç veya yaz:", area_buttons("planadd", "m:plan"))
        return
    if data == "planadd:more":
        await edit_or_send(update, "Plan için başka malzeme seç:", inventory_buttons("planadd"))
        return
    if data == "planadd:done":
        await edit_or_send(update, "pH seç:", ph_choice_menu("planadd"))
        return
    if data == "planadd:ph_custom":
        context.user_data["flow"] = "planadd_custom_ph"
        await edit_or_send(update, "pH değerini yaz. Örn: 6.3", back_cancel("m:plan"))
        return
    if data.startswith("planadd:ph:"):
        context.user_data.setdefault("draft", {})["ph"] = data.split(":", 2)[2]
        context.user_data["flow"] = "planadd_note"
        await edit_or_send(update, "Plan notu yaz. Not yoksa '-' yaz.", back_cancel("m:plan"))
        return


async def handle_area_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    if data == "area:list":
        rows = [r for r in records("areas") if str(r.get("Durum", "aktif")).strip().casefold() != "pasif"]
        if not rows:
            await edit_or_send(update, "Kayıtlı alan yok.", area_menu())
            return
        text = "Alan Listesi\n\n"
        for row in rows:
            text += f"ID {row_id_text(row)} - {row.get('Alan', '-')}"
            if row.get("Not"):
                text += f"\nNot: {row.get('Not')}"
            text += "\n\n"
        await edit_or_send(update, text[:MSG_LIMIT], area_menu())
        return
    if data == "area:add":
        context.user_data["flow"] = "area_add_name"
        context.user_data["draft"] = {}
        await edit_or_send(update, "Alan adını yaz. Örn: Sera 1, Çelik Alanı, Kompost Alanı", back_cancel("m:areas"))
        return
    if data == "area:delete":
        context.user_data["flow"] = "area_delete"
        await edit_or_send(update, "Silmek istediğin alan ID numarasını yaz.", back_cancel("m:areas"))
        return
    if data.startswith("area_select:"):
        _, action, row_s = data.split(":", 2)
        if action == "planadd":
            if row_s == "custom":
                context.user_data["flow"] = "planadd_target"
                await edit_or_send(update, "Hedef/alan yaz. Örn: Teneke 4, Sera 1, Kompost Alanı. Yoksa '-' yaz.", back_cancel("m:plan"))
                return
            area = next((r for r in records("areas") if str(r.get("_row")) == row_s), None)
            if not area:
                await edit_or_send(update, "Alan bulunamadı.", area_buttons("planadd", "m:plan"))
                return
            context.user_data.setdefault("draft", {})["target"] = area.get("Alan", "")
            await edit_or_send(update, "Plan için malzeme seç veya malzeme kullanmayacaksan devam et:", inventory_buttons("planadd"))


async def handle_recipe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    if data == "recipe:list":
        await show_recipes(update)
        return
    if data == "recipe:add":
        context.user_data["flow"] = "recipeadd_name"
        context.user_data["draft"] = {"items": []}
        await edit_or_send(update, "Reçete adını yaz. Örn: Çelik Sisleme Karışımı", back_cancel("m:recipes"))
        return
    if data == "recipe:ai":
        context.user_data["flow"] = "recipe_ai_prompt"
        context.user_data["draft"] = {}
        await edit_or_send(update, "Nasıl bir reçete istiyorsun? Örn: çelikler için hafif sisleme karışımı, orkide besin reçetesi...", back_cancel("m:recipes"))
        return
    if data == "recipe:ai_save":
        d = context.user_data.get("draft", {})
        if not d.get("ai_recipe"):
            await edit_or_send(update, "Kaydedilecek AI reçete taslağı yok.", recipe_menu())
            return
        item_id = next_id("recipes")
        append_record("recipes", RECIPE_HEADERS, {
            "ID": item_id,
            "Ad": d.get("ai_recipe_name", f"AI Reçete {today_str()}"),
            "Islem": "AI Reçete",
            "Malzeme_Miktar": "",
            "pH": "",
            "Not": d["ai_recipe"],
            "Durum": "aktif",
            "CreatedAt": now().isoformat(timespec="seconds"),
        })
        context.user_data.clear()
        await edit_or_send(update, f"AI reçete kaydedildi. ID {item_id}", recipe_menu())
        return
    if data == "recipe:apply":
        context.user_data["flow"] = "recipe_apply"
        await edit_or_send(update, "Uygulamak istediğin reçete ID numarasını yaz.", back_cancel("m:recipes"))
        return
    if data == "recipe:delete":
        context.user_data["flow"] = "recipe_delete"
        await edit_or_send(update, "Silmek istediğin reçete ID numarasını yaz.", back_cancel("m:recipes"))
        return
    if data.startswith("recipeadd:tur:"):
        context.user_data.setdefault("draft", {"items": []})["type"] = data.split(":", 2)[2]
        await edit_or_send(update, "Reçete malzemelerini seç:", inventory_buttons("recipeadd"))
        return
    if data == "recipeadd:more":
        await edit_or_send(update, "Reçete için başka malzeme seç:", inventory_buttons("recipeadd"))
        return
    if data == "recipeadd:done":
        items = context.user_data.get("draft", {}).get("items", [])
        if not items:
            await edit_or_send(update, "Reçete için en az bir malzeme eklemelisin.", inventory_buttons("recipeadd"))
            return
        await edit_or_send(update, "Reçete pH değeri seç:", ph_choice_menu("recipeadd"))
        return
    if data == "recipeadd:ph_custom":
        context.user_data["flow"] = "recipeadd_custom_ph"
        await edit_or_send(update, "pH değerini yaz. Örn: 6.3", back_cancel("m:recipes"))
        return
    if data.startswith("recipeadd:ph:"):
        context.user_data.setdefault("draft", {})["ph"] = data.split(":", 2)[2]
        context.user_data["flow"] = "recipeadd_note"
        await edit_or_send(update, "Reçete notu yaz. Not yoksa '-' yaz.", back_cancel("m:recipes"))


async def handle_issue_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    if data == "issue:add":
        context.user_data["flow"] = "issue_add_area"
        context.user_data["draft"] = {}
        await edit_or_send(update, "Sorun hangi alanda? Alan adını yaz. Örn: Sera 1", back_cancel("m:issues"))
        return
    if data == "issue:list":
        await show_issues(update, open_only=True)
        return
    if data == "issue:history":
        await show_issues(update, open_only=False)
        return
    if data == "issue:note":
        context.user_data["flow"] = "issue_note_id"
        await edit_or_send(update, "İşlem/not eklenecek sorun ID numarasını yaz.", back_cancel("m:issues"))
        return
    if data == "issue:close":
        context.user_data["flow"] = "issue_close_id"
        await edit_or_send(update, "Kapatılacak sorun ID numarasını yaz.", back_cancel("m:issues"))


async def handle_diary_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    if data == "diary:add":
        context.user_data["flow"] = "diary_date"
        context.user_data["draft"] = {}
        await edit_or_send(update, "Günlük tarihi seç:", date_choice_menu("diary"))
        return
    if data == "diary:list":
        await show_diary(update)
        return
    if data == "diary:date":
        context.user_data["flow"] = "diary_find_date"
        await edit_or_send(update, "Günlük tarihini yaz. Örn: 14-06-2026", back_cancel("m:diary"))
        return
    if data == "diary:ai":
        context.user_data["flow"] = "diary_ai_date"
        await edit_or_send(update, "Özetlenecek tarihi yaz. Örn: bugün veya 14-06-2026", back_cancel("m:diary"))
        return
    if data == "diary:delete":
        context.user_data["flow"] = "diary_delete"
        await edit_or_send(update, "Silmek istediğin günlük ID numarasını yaz.", back_cancel("m:diary"))
        return
    if data.startswith("diary:date:"):
        choice = data.rsplit(":", 1)[1]
        if choice == "custom":
            context.user_data["flow"] = "diary_custom_date"
            await edit_or_send(update, "Özel tarihi yaz. Örn: 14-06-2026", back_cancel("diary:add"))
            return
        context.user_data.setdefault("draft", {})["date"] = today_str() if choice == "today" else (now() - timedelta(days=1)).strftime(DATE_FMT)
        context.user_data["flow"] = "diary_note"
        await edit_or_send(update, "Günlük notunu yaz.", back_cancel("m:diary"))


async def handle_essence_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    if data == "ess:add":
        context.user_data["flow"] = "ess_flower"
        context.user_data["draft"] = {"date": today_str()}
        await edit_or_send(update, "Esansa yatırılan çiçeği yaz.", back_cancel("m:essence"))
        return
    if data == "ess:list":
        await show_essences(update, due_only=False)
        return
    if data == "ess:due":
        await show_essences(update, due_only=True)
        return
    if data == "ess:close":
        context.user_data["flow"] = "ess_close"
        await edit_or_send(update, "Bitirilecek esans ID numarasını yaz.", back_cancel("m:essence"))
        return
    if data == "ess:delete":
        context.user_data["flow"] = "ess_delete"
        await edit_or_send(update, "Silinecek esans ID numarasını yaz.", back_cancel("m:essence"))


async def show_history(update: Update, count: int) -> None:
    rows = records("history")
    if not rows:
        await edit_or_send(update, "Geçmiş kaydı yok.", history_menu())
        return
    text = f"Son {count} İşlem\n\n"
    for row in rows[-count:][::-1]:
        text += f"ID {row_id_text(row)} - {row.get('Tarih', '-')}: {row.get('Islem', '-')}\n"
        text += f"{history_material(row) or '-'} {history_amount(row)} {history_unit(row)}"
        if row.get("pH"):
            text += f" | pH {row.get('pH')}"
        if row.get("Not"):
            text += f"\nNot: {row.get('Not')}"
        text += "\n\n"
    await edit_or_send(update, text[:MSG_LIMIT], history_menu())
    if len(text) > MSG_LIMIT and update.effective_message:
        for part in chunks(text)[1:]:
            await update.effective_message.reply_text(part)


async def show_history_page(update: Update, page: int = 0, page_size: int = 10) -> None:
    rows = records("history")
    if not rows:
        await edit_or_send(update, "Geçmiş kaydı yok.", history_menu())
        return

    total = len(rows)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    reversed_rows = rows[::-1]
    start = page * page_size
    page_rows = reversed_rows[start:start + page_size]

    text = f"Tüm Geçmiş\nSayfa {page + 1}/{total_pages} - Toplam {total} kayıt\n\n"
    for row in page_rows:
        text += f"ID {row_id_text(row)} - {row.get('Tarih', '-')}: {row.get('Islem', '-')}\n"
        text += f"{history_material(row) or '-'} {history_amount(row)} {history_unit(row)}"
        if row.get("pH"):
            text += f" | pH {row.get('pH')}"
        if row.get("Not"):
            text += f"\nNot: {row.get('Not')}"
        text += "\n\n"

    nav: list[tuple[str, str]] = []
    if page > 0:
        nav.append(("Önceki", f"hist:all:{page - 1}"))
    if page < total_pages - 1:
        nav.append(("Sonraki", f"hist:all:{page + 1}"))
    rows_kb = []
    if nav:
        rows_kb.append(nav)
    rows_kb.append([("Tam Geçmişi TXT İndir", "hist:file")])
    rows_kb.append([("Geri", "m:history"), ("Ana Menü", "m:main")])
    await edit_or_send(update, text, kb(rows_kb))


async def send_history_file(update: Update) -> None:
    message = update.effective_message
    if not message:
        return
    rows = records("history")
    if not rows:
        await message.reply_text("Geçmiş kaydı yok.", reply_markup=history_menu())
        return
    text = f"Tüm Geçmiş - Toplam {len(rows)} kayıt\n\n"
    for row in rows[::-1]:
        text += f"ID {row_id_text(row)} - {row.get('Tarih', '-')}: {row.get('Islem', '-')}\n"
        text += f"{history_material(row) or '-'} {history_amount(row)} {history_unit(row)}"
        if row.get("pH"):
            text += f" | pH {row.get('pH')}"
        if row.get("Not"):
            text += f"\nNot: {row.get('Not')}"
        text += "\n\n"
    buffer = io.BytesIO(text.encode("utf-8-sig"))
    await message.reply_document(InputFile(buffer, filename=f"tum_gecmis_{today_str()}.txt"), caption="Tüm geçmiş dosyası hazır.")


def compost_row_text(row: dict[str, Any]) -> str:
    text = f"ID {row_id_text(row)} - {row.get('Tarih', '-')}: {row.get('Islem', '-')}\n"
    text += f"{history_material(row) or '-'}"
    if row.get("pH"):
        text += f" | pH {row.get('pH')}"
    if row.get("Not"):
        text += f"\nNot: {row.get('Not')}"
    return text


async def show_compost_page(update: Update, page: int = 0, page_size: int = 10) -> None:
    rows = records("Kompost")
    if not rows:
        await edit_or_send(update, "Kompost kaydı yok.", compost_menu())
        return
    total = len(rows)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    page_rows = rows[::-1][page * page_size:(page + 1) * page_size]
    text = f"Kompost İşlem Geçmişi\nSayfa {page + 1}/{total_pages} - Toplam {total} kayıt\n\n"
    for row in page_rows:
        text += compost_row_text(row) + "\n\n"
    nav: list[tuple[str, str]] = []
    if page > 0:
        nav.append(("Önceki", f"comp:all:{page - 1}"))
    if page < total_pages - 1:
        nav.append(("Sonraki", f"comp:all:{page + 1}"))
    rows_kb = []
    if nav:
        rows_kb.append(nav)
    rows_kb.append([("Tam Kompost Geçmişi TXT", "comp:file")])
    rows_kb.append([("Geri", "m:compost"), ("Ana Menü", "m:main")])
    await edit_or_send(update, text, kb(rows_kb))


async def send_compost_file(update: Update) -> None:
    message = update.effective_message
    if not message:
        return
    rows = records("Kompost")
    if not rows:
        await message.reply_text("Kompost kaydı yok.", reply_markup=compost_menu())
        return
    text = f"Kompost Tüm Geçmiş - Toplam {len(rows)} kayıt\n\n"
    for row in rows[::-1]:
        text += compost_row_text(row) + "\n\n"
    buffer = io.BytesIO(text.encode("utf-8-sig"))
    await message.reply_document(InputFile(buffer, filename=f"kompost_gecmis_{today_str()}.txt"), caption="Kompost geçmiş dosyası hazır.")


def plan_row_text(row: dict[str, Any]) -> str:
    text = f"ID {row_id_text(row)} - {row.get('Tarih', '-')}: {row.get('Islem', '-')}"
    if row.get("Durum"):
        text += f" ({row.get('Durum')})"
    text += "\n"
    if row.get("Hedef"):
        text += f"Hedef: {row.get('Hedef')}\n"
    if row.get("Malzeme_Miktar"):
        text += f"Malzeme: {row.get('Malzeme_Miktar')}\n"
    if row.get("pH"):
        text += f"pH: {row.get('pH')}\n"
    if row.get("Not"):
        text += f"Not: {row.get('Not')}\n"
    return text.rstrip()


async def show_plans(update: Update, *, date: str | None = None) -> None:
    rows = [r for r in records("plans") if str(r.get("Durum", "bekliyor")).strip().casefold() == "bekliyor"]
    if date:
        rows = [r for r in rows if parse_date(str(r.get("Tarih", ""))) == date]
    rows = sorted(rows, key=lambda r: datetime.strptime(parse_date(str(r.get("Tarih", ""))) or "31-12-9999", DATE_FMT))
    if not rows:
        await edit_or_send(update, f"{date} için plan yok." if date else "Yaklaşan plan yok.", plan_menu())
        return
    title = f"{date} Planları" if date else "Yaklaşan Planlar"
    text = f"{title}\n\n"
    for row in rows[:30]:
        text += plan_row_text(row) + "\n\n"
    await edit_or_send(update, text[:MSG_LIMIT], plan_menu())
    if len(text) > MSG_LIMIT and update.effective_message:
        for part in chunks(text)[1:]:
            await update.effective_message.reply_text(part)


async def complete_plan(update: Update, plan_id: str) -> None:
    wanted = plan_id.strip()
    for row in records("plans"):
        if row_id_text(row) != wanted:
            continue
        if str(row.get("Durum", "bekliyor")).strip().casefold() == "tamamlandı":
            await update.effective_message.reply_text("Bu plan zaten tamamlanmış.", reply_markup=plan_menu())
            return
        items = parse_material_summary(row.get("Malzeme_Miktar"))
        for item in items:
            ok, error = check_stock_available(item["material"], item["amount"])
            if not ok:
                await update.effective_message.reply_text(error, reply_markup=plan_menu())
                return
        results = []
        for item in items:
            ok, result, _undo = use_stock(
                item["material"],
                item["amount"],
                item["unit"],
                str(row.get("Islem", "Plan")),
                f"Plan ID {wanted} tamamlandı. {row.get('Not', '')}".strip(),
                today_str(),
                str(row.get("pH", "")),
                record_history=False,
            )
            if not ok:
                await update.effective_message.reply_text(result, reply_markup=plan_menu())
                return
            results.append(f"{format_decimal(item['amount'])} {item['unit']} {item['material']} (Kalan: {result})")
        add_history(
            str(row.get("Islem", "Plan")),
            str(row.get("Malzeme_Miktar", "")),
            "-",
            "",
            str(row.get("pH", "")),
            f"Plan tamamlandı. Hedef: {row.get('Hedef', '-')}. {row.get('Not', '')}".strip(),
            today_str(),
        )
        set_cell_by_header("plans", int(row["_row"]), "Durum", "tamamlandı")
        set_cell_by_header("plans", int(row["_row"]), "CompletedAt", now().isoformat(timespec="seconds"))
        result_text = "\n".join(results) if results else "Stoktan düşülecek malzeme yoktu."
        await update.effective_message.reply_text(f"Plan tamamlandı ve geçmişe işlendi.\n\n{result_text}", reply_markup=plan_menu())
        return
    await update.effective_message.reply_text("Bu plan ID bulunamadı.", reply_markup=plan_menu())


def observation_row_text(row: dict[str, Any]) -> str:
    text = f"ID {row_id_text(row)} - {row.get('Tarih', '-')}: {row.get('Kategori', 'Gözlem')}\n"
    if row.get("Not"):
        text += f"Not: {row.get('Not')}\n"
    if row.get("AI_Yorum"):
        text += f"AI: {str(row.get('AI_Yorum'))[:250]}"
        if len(str(row.get("AI_Yorum"))) > 250:
            text += "..."
        text += "\n"
    return text.rstrip()


def recipe_row_text(row: dict[str, Any]) -> str:
    text = f"ID {row_id_text(row)} - {row.get('Ad', '-')}: {row.get('Islem', '-')}\n"
    text += f"Malzemeler: {row.get('Malzeme_Miktar', '-')}"
    if row.get("pH"):
        text += f"\npH: {row.get('pH')}"
    if row.get("Not"):
        text += f"\nNot: {row.get('Not')}"
    return text


async def show_recipes(update: Update) -> None:
    rows = [r for r in records("recipes") if str(r.get("Durum", "aktif")).strip().casefold() != "pasif"]
    if not rows:
        await edit_or_send(update, "Kayıtlı reçete yok.", recipe_menu())
        return
    text = "Reçete Listesi\n\n"
    for row in rows:
        text += recipe_row_text(row) + "\n\n"
    await edit_or_send(update, text[:MSG_LIMIT], recipe_menu())
    if len(text) > MSG_LIMIT and update.effective_message:
        for part in chunks(text)[1:]:
            await update.effective_message.reply_text(part)


async def apply_recipe(update: Update, recipe_id: str) -> None:
    wanted = recipe_id.strip()
    for row in records("recipes"):
        if row_id_text(row) != wanted:
            continue
        items = parse_material_summary(row.get("Malzeme_Miktar"))
        if not items:
            await update.effective_message.reply_text("Bu reçetede uygulanacak malzeme yok.", reply_markup=recipe_menu())
            return
        for item in items:
            ok, error = check_stock_available(item["material"], item["amount"])
            if not ok:
                await update.effective_message.reply_text(error, reply_markup=recipe_menu())
                return
        results = []
        for item in items:
            ok, result, _undo = use_stock(
                item["material"],
                item["amount"],
                item["unit"],
                str(row.get("Islem", "Reçete")),
                f"Reçete uygulandı: {row.get('Ad', '-')}. {row.get('Not', '')}".strip(),
                today_str(),
                str(row.get("pH", "")),
                record_history=False,
            )
            if not ok:
                await update.effective_message.reply_text(result, reply_markup=recipe_menu())
                return
            results.append(f"{format_decimal(item['amount'])} {item['unit']} {item['material']} (Kalan: {result})")
        add_history(
            str(row.get("Islem", "Reçete")),
            str(row.get("Malzeme_Miktar", "")),
            "-",
            "",
            str(row.get("pH", "")),
            f"Reçete uygulandı: {row.get('Ad', '-')}. {row.get('Not', '')}".strip(),
            today_str(),
        )
        await update.effective_message.reply_text("Reçete uygulandı ve geçmişe işlendi.\n\n" + "\n".join(results), reply_markup=recipe_menu())
        return
    await update.effective_message.reply_text("Bu reçete ID bulunamadı.", reply_markup=recipe_menu())


def issue_text(row: dict[str, Any]) -> str:
    return f"ID {row_id_text(row)} - {row.get('Tarih', '-')}: {row.get('Baslik', '-')}\nAlan: {row.get('Alan', '-')}\nDurum: {row.get('Durum', '-')}\nNot: {row.get('Not', '-')}"


async def show_issues(update: Update, *, open_only: bool) -> None:
    rows = records("issues")
    if open_only:
        rows = [r for r in rows if str(r.get("Durum", "açık")).casefold() == "açık"]
    if not rows:
        await edit_or_send(update, "Sorun kaydı yok.", issue_menu())
        return
    text = ("Açık Sorunlar" if open_only else "Sorun Geçmişi") + "\n\n"
    for row in rows[::-1][:30]:
        text += issue_text(row) + "\n\n"
    await edit_or_send(update, text[:MSG_LIMIT], issue_menu())


async def show_diary(update: Update, date: str | None = None) -> None:
    rows = records("diary")
    if date:
        rows = [r for r in rows if parse_date(str(r.get("Tarih", ""))) == date]
    if not rows:
        await edit_or_send(update, "Günlük kaydı yok.", diary_menu())
        return
    text = ("Günlükler" if not date else f"{date} Günlüğü") + "\n\n"
    for row in rows[-10:][::-1]:
        text += f"ID {row_id_text(row)} - {row.get('Tarih', '-')}\n{row.get('Not', '-')}\n\n"
    await edit_or_send(update, text[:MSG_LIMIT], diary_menu())


async def diary_ai_summary(update: Update, context: ContextTypes.DEFAULT_TYPE, date: str) -> None:
    parts = [f"{date} günü için kısa bahçe özeti çıkar."]
    parts += [f"İşlem: {r.get('Islem')} {history_material(r)} {r.get('Not','')}" for r in operational_records() if parse_date(str(r.get("Tarih", ""))) == date]
    parts += [f"Günlük: {r.get('Not')}" for r in records("diary") if parse_date(str(r.get("Tarih", ""))) == date]
    parts += [f"Gözlem: {r.get('Not')}" for r in records("observations") if parse_date(str(r.get("Tarih", ""))) == date]
    answer = await ask_gemini("\n".join(parts), context)
    await update.effective_message.reply_text("AI Gün Özeti\n\n" + answer, reply_markup=diary_menu())


def essence_due(row: dict[str, Any]) -> bool:
    date = parse_date(str(row.get("Baslangic", "")))
    try:
        days = int(float(str(row.get("Gun", "0")).replace(",", ".")))
    except Exception:
        days = 0
    if not date or not days:
        return False
    return datetime.strptime(date, DATE_FMT) + timedelta(days=days) <= now()


async def show_essences(update: Update, *, due_only: bool) -> None:
    rows = [r for r in records("essences") if str(r.get("Durum", "aktif")).casefold() == "aktif"]
    if due_only:
        rows = [r for r in rows if essence_due(r)]
    if not rows:
        await edit_or_send(update, "Esans kaydı yok.", essence_menu())
        return
    text = ("Süresi Gelen Esanslar" if due_only else "Aktif Esanslar") + "\n\n"
    for row in rows[::-1][:30]:
        text += f"ID {row_id_text(row)} - {row.get('Baslangic','-')}: {row.get('Cicek','-')} + {row.get('Yag','-')}\nKap: {row.get('Kap','-')} | Gün: {row.get('Gun','-')}\nNot: {row.get('Not','-')}\n\n"
    await edit_or_send(update, text[:MSG_LIMIT], essence_menu())


async def show_observation_page(update: Update, page: int = 0, page_size: int = 6) -> None:
    rows = records("observations")
    if not rows:
        await edit_or_send(update, "Gözlem kaydı yok.", observation_menu())
        return
    total = len(rows)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    page_rows = rows[::-1][page * page_size:(page + 1) * page_size]
    text = f"Gözlem Geçmişi\nSayfa {page + 1}/{total_pages} - Toplam {total} kayıt\n\n"
    for row in page_rows:
        text += observation_row_text(row) + "\n\n"
    nav: list[tuple[str, str]] = []
    if page > 0:
        nav.append(("Önceki", f"obs:all:{page - 1}"))
    if page < total_pages - 1:
        nav.append(("Sonraki", f"obs:all:{page + 1}"))
    rows_kb = []
    if nav:
        rows_kb.append(nav)
    rows_kb.append([("Geri", "m:observation"), ("Ana Menü", "m:main")])
    await edit_or_send(update, text, kb(rows_kb))


async def handle_report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    if data == "report:daily":
        rows = [r for r in operational_records() if parse_date(str(r.get("Tarih", ""))) == today_str()]
        if not rows:
            await edit_or_send(update, f"{today_str()} için işlem yok.", report_menu())
            return
        text = f"Günlük Rapor - {today_str()}\n\nToplam işlem: {len(rows)}\n\n"
        for row in rows:
            source = row.get("_source", "Geçmiş")
            text += f"[{source}] ID {row_id_text(row)} - {row.get('Islem', '-')}: {history_material(row) or '-'} {history_amount(row)} {history_unit(row)}\n"
        await edit_or_send(update, text, report_menu())
        return
    if data == "report:stats":
        rows = operational_records()
        if not rows:
            await edit_or_send(update, "İstatistik için kayıt yok.", report_menu())
            return
        types = Counter(r.get("Islem", "Bilinmiyor") for r in rows)
        mats = Counter(history_material(r) for r in rows if history_material(r))
        text = f"Genel İstatistik\n\nToplam işlem: {len(rows)}\n\nİşlem türleri:\n"
        for name, count in types.most_common():
            text += f"- {name}: {count}\n"
        text += "\nEn çok kullanılan malzemeler:\n"
        for name, count in mats.most_common(10):
            text += f"- {name}: {count} işlem\n"
        await edit_or_send(update, text, report_menu())
        return
    if data == "report:season":
        year = now().year
        rows = [r for r in operational_records() if (parse_date(str(r.get("Tarih", ""))) or "").endswith(str(year))]
        issues_open = [r for r in records("issues") if str(r.get("Durum", "açık")).casefold() == "açık"]
        ess_active = [r for r in records("essences") if str(r.get("Durum", "aktif")).casefold() == "aktif"]
        text = f"Sezon Özeti - {year}\n\nToplam işlem: {len(rows)}\nAçık sorun: {len(issues_open)}\nAktif esans: {len(ess_active)}\nGözlem: {len(records('observations'))}\nPlan: {len(records('plans'))}\n\nİşlem türleri:\n"
        for name, count in Counter(r.get("Islem", "Bilinmiyor") for r in rows).most_common(12):
            text += f"- {name}: {count}\n"
        await edit_or_send(update, text, report_menu())
        return
    if data == "report:month":
        context.user_data["flow"] = "report_month"
        await edit_or_send(update, "Ay ve yıl yaz. Örn: 06-2026", back_cancel("m:report"))
        return
    if data == "report:stock":
        context.user_data["flow"] = "report_stock"
        await edit_or_send(update, "Malzeme adını yaz veya seç:", inventory_buttons("reportstock"))
        return
    if data == "report:ph_chart":
        await edit_or_send(update, "Hangi tenekenin pH grafiğini görmek istersin?", ph_chart_menu())
        return
    if data.startswith("report:ph_chart:"):
        teneke = data.split(":", 2)[2]
        await send_ph_chart(update, teneke)


async def send_ph_chart(update: Update, teneke: str) -> None:
    message = update.effective_message
    if not message:
        return
    if plt is None:
        await edit_or_send(update, "Grafik kütüphanesi bu sunucuda yüklü değil.", report_menu())
        return
    rows = records("ph_records")
    if teneke != "all":
        rows = [r for r in rows if str(r.get("Teneke_No", "")).strip() == teneke]
    if not rows:
        await edit_or_send(update, f"{'Grafik için pH kaydı yok.' if teneke == 'all' else f'Teneke {teneke} için pH kaydı yok.'}", report_menu())
        return
    series: dict[str, list[tuple[str, float]]] = {}
    for row in rows:
        key = str(row.get("Teneke_No", "-")) if teneke == "all" else teneke
        date_str = parse_date(str(row.get("Tarih", "")))
        if not date_str:
            continue
        try:
            value = parse_decimal(row.get("pH", ""))
        except Exception:
            continue
        series.setdefault(key, []).append((date_str, value))
    title = "Tüm Tenekeler pH Trendi" if teneke == "all" else f"Teneke {teneke} pH Trendi"
    try:
        buffer = render_line_chart(title, series, "pH")
    except Exception as exc:
        log.exception("pH grafiği oluşturulamadı")
        await edit_or_send(update, f"Grafik oluşturulamadı: {exc}", report_menu())
        return
    await message.chat.send_action(ChatAction.UPLOAD_PHOTO)
    await message.reply_photo(InputFile(buffer, filename="ph_grafik.png"), caption=title, reply_markup=report_menu())


async def prompt_reminder_next_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    draft = context.user_data.setdefault("draft", {})
    repeat = str(draft.get("repeat", "tek")).strip().casefold()
    if repeat in {"tek", ""}:
        context.user_data["flow"] = "rem_text"
        await edit_or_send(update, "Hatırlatma metnini yaz:", back_cancel("rem:add"))
        return
    context.user_data.pop("flow", None)
    await edit_or_send(update, "Bu tekrarlı hatırlatma için bir sınır belirlemek ister misin?", reminder_limit_menu())


async def handle_reminder_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    if data == "rem:add":
        context.user_data["flow"] = "rem_date"
        context.user_data["draft"] = {}
        await edit_or_send(update, "Hatırlatma tarihi seç:", date_choice_menu("rem"))
        return
    if data == "rem:list":
        rows = [r for r in records("reminders") if str(r.get("Durum", "bekliyor")).lower() == "bekliyor"]
        if not rows:
            await edit_or_send(update, "Bekleyen hatırlatma yok.", reminder_menu())
            return
        text = "Bekleyen Hatırlatmalar\n\n"
        for row in rows:
            text += f"ID {row_id_text(row)} - {row.get('Tarih', '-')} {row.get('Saat', '-')} ({repeat_label(row)}{reminder_limit_suffix(row)}): {row.get('Metin', '-')}\n"
        await edit_or_send(update, text, reminder_menu())
        return
    if data == "rem:delete":
        context.user_data["flow"] = "rem_delete"
        await edit_or_send(update, "Silmek istediğin hatırlatma ID numarasını yaz.", back_cancel("m:reminder"))
        return
    if data.startswith("rem:date:"):
        choice = data.rsplit(":", 1)[1]
        if choice == "custom":
            await edit_or_send(update, "Tarih seç veya elle yaz:", reminder_calendar_menu())
            return
        if choice == "custom_text":
            context.user_data["flow"] = "rem_custom_date"
            await edit_or_send(update, "Özel tarihi yaz. Örn: 14-06-2026", back_cancel("rem:add"))
            return
        if choice == "weekly":
            await edit_or_send(update, "Haftanın hangi günü hatırlatayım?", weekday_menu())
            return
        if choice == "monthly":
            await edit_or_send(update, "Her ayın kaçıncı günü hatırlatayım?", monthday_menu())
            return
        if choice == "interval":
            context.user_data["flow"] = "rem_interval_days"
            await edit_or_send(update, "Kaç günde bir hatırlatayım? Örn: 3", back_cancel("rem:add"))
            return
        if choice == "yearly":
            context.user_data["flow"] = "rem_yearly_date"
            await edit_or_send(update, "Her yıl hangi tarihte tekrarlansın? Gün-Ay olarak yaz. Örn: 15-03 (15 Mart)", back_cancel("rem:add"))
            return
        draft = context.user_data.setdefault("draft", {})
        if choice == "daily":
            draft["date"] = today_str()
            draft["repeat"] = "günlük"
        else:
            draft["date"] = today_str() if choice == "today" else (now() - timedelta(days=1)).strftime(DATE_FMT)
            draft["repeat"] = "tek"
        await edit_or_send(update, "Saat seç:", time_choice_menu())
        return
    if data.startswith("rem:time:"):
        choice = data.split(":", 2)[2]
        if choice == "custom":
            context.user_data["flow"] = "rem_custom_time"
            await edit_or_send(update, "Saati yaz. Örn: 17:30", back_cancel("rem:add"))
            return
        context.user_data.setdefault("draft", {})["time"] = choice
        await prompt_reminder_next_step(update, context)
        return
    if data.startswith("rem:limit:"):
        choice = data.rsplit(":", 1)[1]
        if choice == "none":
            context.user_data["flow"] = "rem_text"
            await edit_or_send(update, "Hatırlatma metnini yaz:", back_cancel("rem:add"))
            return
        if choice == "enddate":
            context.user_data["flow"] = "rem_limit_enddate"
            await edit_or_send(update, "Hangi tarihe kadar tekrarlansın? Örn: 30-09-2026", back_cancel("rem:add"))
            return
        if choice == "count":
            context.user_data["flow"] = "rem_limit_count"
            await edit_or_send(update, "Kaç kere tekrarlansın? Örn: 5", back_cancel("rem:add"))
            return
        return
    if data.startswith("rem:cal:"):
        _, _, year_s, month_s = data.split(":")
        await edit_or_send(update, "Tarih seç veya elle yaz:", reminder_calendar_menu(int(year_s), int(month_s)))
        return
    if data.startswith("rem:calday:"):
        date = data.split(":", 2)[2]
        draft = context.user_data.setdefault("draft", {})
        draft["date"] = date
        draft["repeat"] = "tek"
        await edit_or_send(update, "Saat seç:", time_choice_menu())
        return
    if data.startswith("rem:weekday:"):
        weekday = int(data.rsplit(":", 1)[1])
        draft = context.user_data.setdefault("draft", {})
        draft["date"] = next_weekday_date(weekday)
        draft["repeat"] = "haftalık"
        draft["weekday"] = weekday
        await edit_or_send(update, "Saat seç:", time_choice_menu())
        return
    if data.startswith("rem:monthday:"):
        monthday = int(data.rsplit(":", 1)[1])
        draft = context.user_data.setdefault("draft", {})
        draft["date"] = next_monthday_date(monthday)
        draft["repeat"] = "aylık"
        draft["monthday"] = monthday
        await edit_or_send(update, "Saat seç:", time_choice_menu())


async def handle_weather_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    if data == "weather:now":
        await edit_or_send(update, "Şehir seç veya yaz:", city_menu("weathernow"))
        return
    if data == "weather:month":
        await edit_or_send(update, "Şehir seç veya yaz:", city_menu("weathermonth"))
        return
    if data.startswith("weathernow:city:") or data.startswith("weathermonth:city:"):
        prefix, _, city = data.partition(":city:")
        if city == "custom":
            context.user_data["flow"] = "weather_now" if prefix == "weathernow" else "weather_month"
            await edit_or_send(update, "Şehir adını yaz:", back_cancel("m:weather"))
            return
        await show_weather(update, city, monthly=prefix == "weathermonth")


async def handle_observation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    if data == "obs:add":
        context.user_data["flow"] = "obs_note"
        context.user_data["draft"] = {"ai": False, "category": "Gözlem"}
        await edit_or_send(update, "Gözlem notunu yaz. Kısa da olabilir. Sonra fotoğraf isteyeceğim.", back_cancel("m:observation"))
        return
    if data == "obs:ai":
        context.user_data["flow"] = "obs_note"
        context.user_data["draft"] = {"ai": True, "category": "AI Gözlem"}
        await edit_or_send(update, "Fotoğrafla birlikte yorumlatmak istediğin şeyi yaz. Sonra fotoğraf isteyeceğim.", back_cancel("m:observation"))
        return
    if data.startswith("obs:all:"):
        try:
            page = int(data.rsplit(":", 1)[1])
        except ValueError:
            page = 0
        await show_observation_page(update, page)
        return
    if data == "obs:date":
        context.user_data["flow"] = "obs_date"
        await edit_or_send(update, "Gözlem tarihini yaz. Örn: 14-06-2026 veya 2026-06-14", back_cancel("m:observation"))
        return
    if data == "obs:delete":
        context.user_data["flow"] = "obs_delete"
        await edit_or_send(update, "Silmek istediğin gözlem ID numarasını yaz.", back_cancel("m:observation"))


def render_line_chart(title: str, series: dict[str, list[tuple[str, float]]], ylabel: str) -> io.BytesIO:
    """series: {seri_adi: [(tarih_str DD-MM-YYYY, deger), ...]}. Her seriyi tarihe göre sıralayıp çizer."""
    if plt is None:
        raise RuntimeError("matplotlib yüklü değil")
    fig, ax = plt.subplots(figsize=(8, 4.5))
    has_data = False
    for name, points in series.items():
        parsed: list[tuple[datetime, float]] = []
        for date_str, value in points:
            try:
                parsed.append((datetime.strptime(date_str, DATE_FMT), float(value)))
            except Exception:
                continue
        parsed.sort(key=lambda x: x[0])
        if not parsed:
            continue
        has_data = True
        xs = [p[0] for p in parsed]
        ys = [p[1] for p in parsed]
        ax.plot(xs, ys, marker="o", label=name)
    if not has_data:
        plt.close(fig)
        raise ValueError("Çizilecek geçerli veri yok")
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    if len(series) > 1:
        ax.legend(loc="best", fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    buffer = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buffer, format="png", dpi=140)
    plt.close(fig)
    buffer.seek(0)
    return buffer


def build_backup_zip() -> io.BytesIO:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, sheet_name in [
            ("inventory.csv", "inventory"),
            ("history.csv", "history"),
            ("kompost.csv", "Kompost"),
            ("ph_records.csv", "ph_records"),
            ("reminders.csv", "reminders"),
            ("observations.csv", "observations"),
            ("plans.csv", "plans"),
            ("areas.csv", "areas"),
            ("recipes.csv", "recipes"),
            ("issues.csv", "issues"),
            ("diary.csv", "diary"),
            ("essences.csv", "essences"),
            ("alerts.csv", "alerts"),
        ]:
            out = io.StringIO()
            writer = csv.writer(out)
            writer.writerows(SHEET[sheet_name].get_all_values())
            zf.writestr(filename, out.getvalue().encode("utf-8-sig"))
    buffer.seek(0)
    return buffer


async def send_backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return
    await message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)
    buffer = build_backup_zip()
    await message.reply_document(InputFile(buffer, filename=f"yasemin_yedek_{today_str()}.zip"), caption="Yedek hazır.")


async def weekly_backup_worker(app: Application) -> None:
    """Her Pazartesi 08:00-08:29 arasında (TR saati) otomatik olarak zip yedeği gönderir.
    Aynı hafta içinde tekrar göndermemek için alerts sayfasında son gönderilen hafta izlenir."""
    while True:
        try:
            chat_id = alert_value("stock_chat_id")
            current = now()
            if chat_id and current.weekday() == 0 and current.hour == 8:
                week_key = current.strftime("%Y-%W")
                if alert_value("last_backup_week") != week_key:
                    buffer = build_backup_zip()
                    await app.bot.send_document(
                        chat_id=int(chat_id),
                        document=InputFile(buffer, filename=f"yasemin_yedek_{today_str()}.zip"),
                        caption="Haftalık otomatik yedek.",
                    )
                    set_alert_value("last_backup_week", week_key)
        except Exception as exc:
            log.exception("Haftalık otomatik yedekleme hatası")
            await notify_admin_error(app.bot, "weekly_backup_worker", exc)
        await asyncio.sleep(1800)


def schedule_next_reminder(row: dict[str, Any], next_due: datetime) -> None:
    """Tekrarlı bir hatırlatma gönderildikten sonra bir sonraki tarihi ayarlar; Bitis_Tarihi
    veya Kalan_Tekrar sınırına ulaşıldıysa tekrarı durdurup Durum'u gönderildi yapar."""
    row_num = int(row["_row"])
    remaining_raw = str(row.get("Kalan_Tekrar") or "").strip()
    if remaining_raw:
        try:
            remaining = int(float(remaining_raw.replace(",", "."))) - 1
        except Exception:
            remaining = None
        if remaining is not None:
            if remaining <= 0:
                set_cells_by_header("reminders", row_num, {"Durum": "gönderildi", "Kalan_Tekrar": "0"})
                return
            end_date_check = parse_date(str(row.get("Bitis_Tarihi") or ""), allow_words=False)
            if end_date_check:
                try:
                    end_dt = datetime.strptime(end_date_check, DATE_FMT)
                except Exception:
                    end_dt = None
                if end_dt and next_due.date() > end_dt.date():
                    set_cells_by_header("reminders", row_num, {"Durum": "gönderildi", "Kalan_Tekrar": str(remaining)})
                    return
            set_cells_by_header("reminders", row_num, {"Tarih": next_due.strftime(DATE_FMT), "Durum": "bekliyor", "Kalan_Tekrar": str(remaining)})
            return
    end_date = parse_date(str(row.get("Bitis_Tarihi") or ""), allow_words=False)
    if end_date:
        try:
            end_dt = datetime.strptime(end_date, DATE_FMT)
        except Exception:
            end_dt = None
        if end_dt and next_due.date() > end_dt.date():
            set_cells_by_header("reminders", row_num, {"Durum": "gönderildi"})
            return
    set_cells_by_header("reminders", row_num, {"Tarih": next_due.strftime(DATE_FMT), "Durum": "bekliyor"})


async def reminder_worker(app: Application) -> None:
    while True:
        try:
            rows = records("reminders")
            current = now().replace(second=0, microsecond=0)
            for row in rows:
                try:
                    if str(row.get("Durum", "bekliyor")).strip().casefold() != "bekliyor":
                        continue
                    due = parse_datetime(row.get("Tarih"), row.get("Saat"))
                    chat_id = str(row.get("Chat_ID") or "").strip()
                    if not due or not chat_id or due > current:
                        continue
                    weather_note = ""
                    try:
                        metin = str(row.get("Metin", ""))
                        if "sula" in metin.casefold():
                            garden_city = alert_value("garden_city")
                            if garden_city and await is_rain_forecast_today(garden_city):
                                weather_note = "\n\n(Not: Bugün için yağmur bekleniyor, sulamayı erteleyebilirsin.)"
                    except Exception:
                        log.exception("Hava durumu kontrolü başarısız, hatırlatma yine de gönderilecek")
                    await app.bot.send_message(chat_id=int(chat_id), text=f"Hatırlatma\n\nID {row_id_text(row)} - {row.get('Metin', '-')}{weather_note}")
                    repeat = str(row.get("Tekrar", "")).strip().casefold()
                    if repeat in {"günlük", "gunluk", "her gün", "hergun", "daily"}:
                        next_due = due
                        while next_due <= current:
                            next_due += timedelta(days=1)
                        schedule_next_reminder(row, next_due)
                    elif repeat in {"haftalık", "haftalik", "weekly"}:
                        next_due = due
                        while next_due <= current:
                            next_due += timedelta(days=7)
                        schedule_next_reminder(row, next_due)
                    elif repeat in {"aylık", "aylik", "monthly"}:
                        try:
                            monthday = int(row.get("Ay_Gunu") or due.day)
                        except Exception:
                            monthday = due.day
                        next_due = next_monthly_after(due, monthday, current)
                        schedule_next_reminder(row, next_due)
                    elif repeat in {"aralık", "aralik", "gunde_bir", "interval"}:
                        try:
                            interval_days = int(float(str(row.get("Gun_Araligi") or "0").replace(",", ".")))
                        except Exception:
                            interval_days = 0
                        if interval_days <= 0:
                            set_cell_by_header("reminders", int(row["_row"]), "Durum", "gönderildi")
                        else:
                            next_due = due
                            while next_due <= current:
                                next_due += timedelta(days=interval_days)
                            schedule_next_reminder(row, next_due)
                    elif repeat in {"yıllık", "yillik", "yearly"}:
                        try:
                            yday = int(row.get("Ay_Gunu") or due.day)
                        except Exception:
                            yday = due.day
                        try:
                            ymonth = int(row.get("Yil_Ay") or due.month)
                        except Exception:
                            ymonth = due.month
                        next_due = next_yearly_after(due, yday, ymonth, current)
                        schedule_next_reminder(row, next_due)
                    else:
                        set_cell_by_header("reminders", int(row["_row"]), "Durum", "gönderildi")
                    log.info("Hatırlatma gönderildi: ID %s", row_id_text(row))
                except Exception:
                    log.exception("Hatırlatma satırı işlenemedi: ID %s", row_id_text(row))
        except Exception as exc:
            log.exception("Hatırlatma kontrolünde hata")
            await notify_admin_error(app.bot, "reminder_worker", exc)
        await asyncio.sleep(30)


async def stock_alert_worker(app: Application) -> None:
    while True:
        try:
            chat_id = alert_value("stock_chat_id")
            if chat_id:
                sent = {x for x in alert_value("stock_sent_v2").split(",") if x}
                expiry_sent = {x for x in alert_value("expiry_sent_v1").split(",") if x}
                current_critical: set[str] = set()
                for item in records("inventory"):
                    item_id = row_id_text(item)
                    category = str(item.get("Kategori", "")).strip().casefold()

                    expiry = str(item.get("Son_Kullanma", "")).strip()
                    if expiry and item_id not in expiry_sent:
                        try:
                            exp_date = datetime.strptime(expiry, DATE_FMT)
                            days_left = (exp_date.date() - now().date()).days
                        except Exception:
                            days_left = None
                        if days_left is not None and days_left <= 14:
                            expiry_sent.add(item_id)
                            set_alert_value("expiry_sent_v1", ",".join(sorted(expiry_sent)))
                            durum = "süresi geçmiş" if days_left < 0 else f"{days_left} gün kaldı"
                            await app.bot.send_message(
                                chat_id=int(chat_id),
                                text=f"⏳ Son kullanma tarihi yaklaşıyor\n\nID {item_id} - {item.get('Malzeme / Alet','-')}: {durum} ({expiry})",
                            )

                    raw = str(item.get("Kalan Miktar", "")).strip()
                    if not raw or raw.casefold() == "stok bol":
                        continue
                    try:
                        remaining = parse_decimal(raw)
                    except Exception:
                        continue
                    threshold = 0 if category in {"cihaz", "mekanik", "alet"} else 1
                    if remaining <= threshold:
                        current_critical.add(item_id)
                    if remaining <= threshold and item_id not in sent:
                        sent.add(item_id)
                        set_alert_value("stock_sent_v2", ",".join(sorted(sent)))
                        await app.bot.send_message(
                            chat_id=int(chat_id),
                            text=f"Kritik stok uyarısı\n\nID {item_id} - {item.get('Malzeme / Alet','-')}: {format_decimal(remaining)} {item.get('Birim','')}",
                        )
                new_sent = sent.intersection(current_critical)
                if new_sent != sent:
                    set_alert_value("stock_sent_v2", ",".join(sorted(new_sent)))
        except Exception as exc:
            log.exception("Kritik stok kontrolünde hata")
            await notify_admin_error(app.bot, "stock_alert_worker", exc)
        await asyncio.sleep(60)


async def post_init(app: Application) -> None:
    app.create_task(reminder_worker(app))
    app.create_task(stock_alert_worker(app))
    app.create_task(weekly_backup_worker(app))


async def ask_ai(question: str, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> str:
    if not AI_CLIENT:
        return "Agnes AI ayarı eksik. AGNES_API_KEY tanımlanmalı ve openai paketi kurulmalı."
    history = context.user_data.setdefault("ai_history", [])
    messages = [{"role": "system", "content": "Türkçe cevap veren, tarım/stok kayıtlarında yardımcı bir asistansın. Kısa ve uygulanabilir cevap ver."}]
    messages.extend(history[-8:])
    messages.append({"role": "user", "content": question})
    try:
        response = await asyncio.to_thread(
            AI_CLIENT.chat.completions.create,
            model=AGNES_MODEL,
            messages=messages,
            max_tokens=1200,
        )
        answer = response.choices[0].message.content
        history.extend([{"role": "user", "content": question}, {"role": "assistant", "content": answer}])
        context.user_data["ai_history"] = history[-12:]
        return answer
    except Exception as exc:
        return f"Agnes AI hatası: {exc}"


async def ask_groq(question: str, context: ContextTypes.DEFAULT_TYPE) -> str:
    if not GROQ_CLIENT:
        return "Groq ayarı eksik. Render Variables içine GROQ_API_KEY eklenmeli."
    history = context.user_data.setdefault("groq_history", [])
    messages = [{"role": "system", "content": "Türkçe cevap veren, hızlı ve pratik bir bahçecilik asistanısın. Kısa, net ve uygulanabilir cevap ver."}]
    messages.extend(history[-8:])
    messages.append({"role": "user", "content": question})
    try:
        response = await asyncio.to_thread(
            GROQ_CLIENT.chat.completions.create,
            model=GROQ_MODEL,
            messages=messages,
            max_tokens=1200,
        )
        answer = response.choices[0].message.content or "Groq cevap döndürmedi."
        history.extend([{"role": "user", "content": question}, {"role": "assistant", "content": answer}])
        context.user_data["groq_history"] = history[-12:]
        return answer
    except Exception as exc:
        return f"Groq hatası: {exc}"


async def ask_web_search(question: str, context: ContextTypes.DEFAULT_TYPE) -> str:
    if not TAVILY_API_KEY:
        return "Tavily ayarı eksik. Render Variables içine TAVILY_API_KEY eklenmeli."
    try:
        response = await asyncio.to_thread(
            lambda: requests.post(
                "https://api.tavily.com/search",
                json={"api_key": TAVILY_API_KEY, "query": question, "search_depth": "advanced", "max_results": 5, "include_answer": True},
                timeout=45,
            )
        )
        response.raise_for_status()
        data = response.json()
        items = []
        if data.get("answer"):
            items.append(f"Ön cevap: {data['answer']}")
        for result in data.get("results", [])[:5]:
            items.append(f"- {result.get('title','Kaynak')}: {result.get('content','')} ({result.get('url','')})")
        clean = "\n".join(items) or "Arama sonucu bulunamadı."
        prompt = f"Bu güncel arama sonuçlarını Türkçe, düzenli ve kısa özetle. En sonda kaynak linklerini koru.\n\nSoru: {question}\n\nSonuçlar:\n{clean}"
        if GEMINI_API_KEY:
            return await ask_gemini(prompt, context)
        return await ask_groq(prompt, context)
    except Exception as exc:
        return f"Tavily arama hatası: {exc}"


def extract_document_text(filename: str, data: bytes) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        except Exception as exc:
            return f"PDF okunamadı: {exc}"
    try:
        return data.decode("utf-8", errors="ignore").strip()
    except Exception as exc:
        return f"Dosya okunamadı: {exc}"


async def pinecone_store_doc(doc_id: int, filename: str, text: str) -> str:
    if not (PINECONE_API_KEY and PINECONE_HOST and GEMINI_API_KEY):
        return "kapalı"
    try:
        emb = await asyncio.to_thread(
            lambda: requests.post(
                "https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent",
                params={"key": GEMINI_API_KEY},
                json={"content": {"parts": [{"text": text[:8000]}]}},
                timeout=45,
            )
        )
        emb.raise_for_status()
        values = emb.json()["embedding"]["values"]
        up = await asyncio.to_thread(
            lambda: requests.post(
                f"{PINECONE_HOST.rstrip('/')}/vectors/upsert",
                headers={"Api-Key": PINECONE_API_KEY, "Content-Type": "application/json"},
                json={"vectors": [{"id": f"doc-{doc_id}", "values": values, "metadata": {"filename": filename, "text": text[:3000]}}]},
                timeout=45,
            )
        )
        up.raise_for_status()
        return "kaydedildi"
    except Exception as exc:
        log.warning("Pinecone kaydı olmadı: %s", exc)
        return "hata"


async def answer_from_docs(question: str, context: ContextTypes.DEFAULT_TYPE) -> str:
    docs = records("ai_docs")[-8:]
    if not docs:
        return "Henüz AI dosya hafızasına kayıtlı doküman yok."
    context_text = "\n\n".join(f"Dosya: {d.get('Dosya','-')}\nÖzet: {d.get('Ozet','')}\nMetin: {str(d.get('Metin',''))[:1500]}" for d in docs)
    prompt = f"Kaydedilmiş dokümanlardan yararlanarak Türkçe cevap ver. Bilgi yoksa açıkça söyle.\n\nSoru: {question}\n\nDokümanlar:\n{context_text}"
    if GEMINI_API_KEY:
        return await ask_gemini(prompt, context)
    return await ask_groq(prompt, context)


def build_records_context() -> str:
    parts: list[str] = []

    inv = records("inventory")
    parts.append("STOK (ID - Malzeme: Kalan Miktar Birim | Kategori):")
    for item in inv[:250]:
        parts.append(f"{row_id_text(item)} - {item.get('Malzeme / Alet','-')}: {item.get('Kalan Miktar','-')} {item.get('Birim','')} | {item.get('Kategori','-')}")

    hist = records("history")[-150:]
    parts.append("\nSON GEÇMİŞ İŞLEMLER (Tarih - İşlem - Malzeme Miktar Birim - pH - Not):")
    for row in hist:
        parts.append(f"{row.get('Tarih','-')} - {row.get('Islem','-')} - {history_material(row)} {history_amount(row)} {history_unit(row)} - pH {row.get('pH','-')} - {row.get('Not','')}")

    comp = records("Kompost")[-80:]
    parts.append("\nKOMPOST İŞLEMLERİ:")
    for row in comp:
        parts.append(compost_row_text(row).replace("\n", " | "))

    ph = records("ph_records")[-150:]
    parts.append("\npH KAYITLARI (Teneke - Tarih - pH - Not):")
    for row in ph:
        parts.append(f"{row.get('Teneke_No','-')} - {row.get('Tarih','-')} - pH {row.get('pH','-')} - {row.get('Not','')}")

    plans = [r for r in records("plans") if str(r.get("Durum", "bekliyor")).strip().casefold() == "bekliyor"]
    parts.append("\nBEKLEYEN PLANLAR:")
    for row in plans:
        parts.append(plan_row_text(row).replace("\n", " | "))

    issues = [r for r in records("issues") if str(r.get("Durum", "açık")).strip().casefold() == "açık"]
    parts.append("\nAÇIK SORUNLAR:")
    for row in issues:
        parts.append(issue_text(row).replace("\n", " | "))

    ess = [r for r in records("essences") if str(r.get("Durum", "aktif")).strip().casefold() == "aktif"]
    parts.append("\nAKTİF ESANSLAR:")
    for row in ess:
        parts.append(f"{row.get('Baslangic','-')}: {row.get('Cicek','-')} + {row.get('Yag','-')} | Kap {row.get('Kap','-')} | Gün {row.get('Gun','-')}")

    diary = records("diary")[-40:]
    parts.append("\nSON GÜNLÜK NOTLARI:")
    for row in diary:
        parts.append(f"{row.get('Tarih','-')}: {row.get('Not','')}")

    reminders = [r for r in records("reminders") if str(r.get("Durum", "bekliyor")).strip().casefold() == "bekliyor"]
    parts.append("\nBEKLEYEN HATIRLATMALAR:")
    for row in reminders:
        parts.append(f"{row.get('Tarih','-')} {row.get('Saat','-')} ({repeat_label(row)}{reminder_limit_suffix(row)}): {row.get('Metin','-')}")

    return "\n".join(parts)


async def ask_about_records(question: str, context: ContextTypes.DEFAULT_TYPE) -> str:
    data_text = build_records_context()[:14000]
    prompt = (
        "Aşağıda bir bahçe/tarım takip sisteminin güncel kayıtları var. Bu kayıtlara dayanarak Türkçe, "
        "net ve kısa cevap ver. Kayıtlarda olmayan bir bilgiyi uydurma; bulamadıysan açıkça söyle.\n\n"
        f"Soru: {question}\n\nKayıtlar:\n{data_text}"
    )
    if GEMINI_API_KEY:
        return await ask_gemini(prompt, context)
    return await ask_groq(prompt, context)


QUICK_LOG_ACTIONS = {"stok_kullan", "stok_ekle", "ph_ekle"}


async def parse_quick_log(text: str, context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any] | None:
    """Menüsüz, serbest bir cümleyi (ör. 'bugün 3 litre su ile sulama yaptım') yapısal bir
    işlem taslağına çevirir. Emin değilse veya AI yoksa None döner (hiçbir şey otomatik yazılmaz)."""
    if not (GEMINI_API_KEY or GROQ_API_KEY):
        return None
    prompt = (
        "Kullanıcı bir bahçe/tarım takip botuna serbest bir cümleyle bir işlem bildirdi. "
        "Bunu aşağıdaki JSON şemalarından TAM OLARAK birine dönüştür. SADECE geçerli JSON döndür, "
        "başka hiçbir açıklama, markdown veya kod bloğu ekleme.\n\n"
        "Stoktan malzeme kullanıldıysa (sulama, gübreleme, ilaçlama, hasat, toprak işlemi vb.):\n"
        '{"action": "stok_kullan", "malzeme": "...", "miktar": sayı, "birim": "gr|ml|L|adet", '
        '"islem_turu": "Sulama|Gübreleme|İlaçlama|Hasat|Toprak İşlemi|Çelik Alma|Çelik Kontrol|Sisleme|Diğer", "not": "..."}\n\n'
        "Yeni malzeme stoğa eklendiyse (satın alındı, getirildi vb.):\n"
        '{"action": "stok_ekle", "malzeme": "...", "miktar": sayı, "birim": "gr|ml|L|adet", "not": "..."}\n\n'
        "Bir teneke/konteynerin pH'ı ölçüldüyse:\n"
        '{"action": "ph_ekle", "teneke": "...", "ph": sayı, "not": "..."}\n\n'
        "Bunlardan hiçbiri değilse, emin değilsen, ya da sadece sohbet/soru ise:\n"
        '{"action": "bilinmiyor"}\n\n'
        f"Kullanıcının mesajı: {text}"
    )
    try:
        raw = await ask_gemini(prompt, context) if GEMINI_API_KEY else await ask_groq(prompt, context)
    except Exception:
        return None
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.casefold().startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        data = json.loads(cleaned[start:end + 1])
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("action") not in QUICK_LOG_ACTIONS:
        return None
    return data


def quick_log_summary(data: dict[str, Any]) -> str:
    action = data.get("action")
    note = str(data.get("not") or "").strip() or "-"
    if action == "stok_kullan":
        return (
            "Şunu kaydedeyim mi?\n\n"
            f"İşlem: {data.get('islem_turu', '-')}\n"
            f"Malzeme: {data.get('malzeme', '-')}\n"
            f"Miktar: {data.get('miktar', '-')} {data.get('birim', '')}\n"
            f"Not: {note}"
        )
    if action == "stok_ekle":
        return (
            "Şunu stoğa ekleyeyim mi?\n\n"
            f"Malzeme: {data.get('malzeme', '-')}\n"
            f"Miktar: {data.get('miktar', '-')} {data.get('birim', '')}\n"
            f"Not: {note}"
        )
    if action == "ph_ekle":
        return (
            "Şunu kaydedeyim mi?\n\n"
            f"Teneke: {data.get('teneke', '-')}\n"
            f"pH: {data.get('ph', '-')}\n"
            f"Not: {note}"
        )
    return "Anlayamadım."


def quick_log_confirm_kb() -> InlineKeyboardMarkup:
    return kb([[("✅ Onayla", "qlog:confirm"), ("❌ İptal", "qlog:cancel")]])


async def execute_quick_log(update: Update, data: dict[str, Any]) -> None:
    action = data.get("action")
    try:
        if action == "stok_kullan":
            material = str(data.get("malzeme", "")).strip()
            amount = parse_decimal(data.get("miktar"))
            unit = str(data.get("birim") or "").strip()
            op_type = str(data.get("islem_turu") or "Diğer").strip()
            note = str(data.get("not") or "").strip()
            ok, error = check_stock_available(material, amount)
            if not ok:
                await edit_or_send(update, error, main_menu())
                return
            ok, result, undo = use_stock(material, amount, unit, op_type, note)
            if not ok:
                await edit_or_send(update, result, main_menu())
                return
            await edit_or_send(update, f"Kaydedildi.\n{format_decimal(amount)} {unit} {material} - {op_type}\nKalan: {result}", main_menu())
            return
        if action == "stok_ekle":
            material = str(data.get("malzeme", "")).strip()
            if find_inventory_by_name(material):
                await edit_or_send(update, f"{material} zaten stokta var. Miktarı artırmak için Stok menüsünü kullan.", main_menu())
                return
            amount = parse_decimal(data.get("miktar"))
            unit = str(data.get("birim") or "").strip()
            note = str(data.get("not") or "").strip()
            item_id = next_id("inventory")
            append_record("inventory", INVENTORY_HEADERS, {
                "ID": item_id,
                "Kategori": "Diğer",
                "Malzeme / Alet": material,
                "Başlangıç Miktarı": format_decimal(amount),
                "Kullanılan": "0",
                "Kalan Miktar": format_decimal(amount),
                "Birim": unit,
                "Görevi / Not": note,
                "CreatedAt": now().isoformat(timespec="seconds"),
            })
            add_history("ENVANTERE EKLENDİ", material, format_decimal(amount), unit, "", note)
            await edit_or_send(update, f"Stoğa eklendi: {material} ({format_decimal(amount)} {unit})", main_menu())
            return
        if action == "ph_ekle":
            teneke = str(data.get("teneke", "")).strip()
            ph_value = parse_decimal(data.get("ph"))
            note = str(data.get("not") or "").strip()
            item_id = next_id("ph_records")
            append_record("ph_records", PH_HEADERS, {
                "ID": item_id,
                "Tarih": today_str(),
                "Teneke_No": teneke,
                "pH": format_decimal(ph_value),
                "Not": note,
                "CreatedAt": now().isoformat(timespec="seconds"),
            })
            await edit_or_send(update, f"pH kaydedildi: Teneke {teneke} - pH {format_decimal(ph_value)}", main_menu())
            return
        await edit_or_send(update, "Bu işlemi anlayamadım.", main_menu())
    except Exception as exc:
        log.exception("Hızlı kayıt uygulanamadı")
        await edit_or_send(update, f"Kayıt sırasında hata oluştu: {exc}", main_menu())


async def perenual_get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    if not PERENUAL_API_KEY:
        raise RuntimeError("Perenual API anahtarı eksik. Render Variables içine PERENUAL_API_KEY eklenmeli.")
    url = f"https://perenual.com/api/{path.lstrip('/')}"
    full_params = {"key": PERENUAL_API_KEY, **params}
    response = await asyncio.to_thread(lambda: requests.get(url, params=full_params, timeout=45))
    response.raise_for_status()
    return response.json()


def plant_summary(item: dict[str, Any]) -> str:
    name = item.get("common_name") or item.get("scientific_name") or "-"
    sci = item.get("scientific_name")
    if isinstance(sci, list):
        sci = ", ".join(str(x) for x in sci[:2])
    return (
        f"Bitki: {name}\n"
        f"Bilimsel ad: {sci or '-'}\n"
        f"Sulama: {item.get('watering', '-')}\n"
        f"Güneş: {', '.join(item.get('sunlight', [])) if isinstance(item.get('sunlight'), list) else item.get('sunlight', '-')}\n"
        f"Bakım seviyesi: {item.get('maintenance', '-')}\n"
        f"Zehirli mi: {item.get('poisonous_to_humans', '-')}\n"
    )


async def search_plant(query: str, context: ContextTypes.DEFAULT_TYPE) -> str:
    data = await perenual_get("species-list", {"q": query})
    results = data.get("data", [])[:5]
    if not results:
        return "Bitki bulunamadı."
    text = "Bulunan bitkiler\n\n"
    for item in results:
        text += f"ID {item.get('id')} - {item.get('common_name') or '-'}\n"
        sci = item.get("scientific_name")
        text += f"Bilimsel: {', '.join(sci) if isinstance(sci, list) else sci or '-'}\n\n"
    return text


async def plant_care(query: str, context: ContextTypes.DEFAULT_TYPE) -> str:
    data = await perenual_get("species-list", {"q": query})
    results = data.get("data", [])
    if not results:
        return "Bitki bulunamadı."
    plant_id = results[0].get("id")
    detail = await perenual_get(f"species/details/{plant_id}", {})
    raw = plant_summary(detail)
    prompt = f"Bu Perenual bitki verisini Türkçe, pratik bakım tavsiyesine çevir. Bahçeciye kısa öneriler ver.\n\n{json.dumps(detail, ensure_ascii=False)[:8000]}"
    ai = await ask_gemini(prompt, context) if GEMINI_API_KEY else await ask_groq(prompt, context)
    return f"{raw}\nAI Bakım Tavsiyesi:\n{ai}"


async def identify_plant(image_bytes: bytes, note: str, context: ContextTypes.DEFAULT_TYPE) -> str:
    if not PLANTNET_API_KEY:
        return "PlantNet API anahtarı eksik. Render Variables içine PLANTNET_API_KEY eklenince çalışır."
    url = f"https://my-api.plantnet.org/v2/identify/{PLANTNET_PROJECT}"
    try:
        response = await asyncio.to_thread(
            lambda: requests.post(
                url,
                params={"api-key": PLANTNET_API_KEY},
                files=[("images", ("photo.jpg", image_bytes, "image/jpeg"))],
                data={"organs": "auto"},
                timeout=60,
            )
        )
        if response.status_code == 404:
            return "PlantNet bu fotoğrafta bitki bulamadı. Daha net, yakından ve iyi ışıklı bir fotoğraf dene (yaprak veya çiçek yakın çekimi en iyi sonucu verir)."
        if response.status_code in (400, 401, 403):
            return f"PlantNet API hatası ({response.status_code}): API anahtarını kontrol et. Detay: {response.text[:300]}"
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        return f"PlantNet API hatası: {exc}"

    results = data.get("results", [])[:5]
    if not results:
        return "Bitki tanınamadı. Farklı bir fotoğraf dene (yaprak/çiçek yakın çekimi daha iyi sonuç verir)."

    lines = ["Bitki Tanıma Sonuçları (PlantNet)\n"]
    for i, item in enumerate(results, start=1):
        species = item.get("species", {}) or {}
        score = (item.get("score") or 0) * 100
        sci_name = species.get("scientificNameWithoutAuthor") or "-"
        common_names = species.get("commonNames") or []
        common = ", ".join(common_names[:3]) if common_names else "-"
        family = (species.get("family") or {}).get("scientificNameWithoutAuthor", "-")
        lines.append(f"{i}. {sci_name} (%{score:.0f} eşleşme)\n   Yaygın adlar: {common}\n   Familya: {family}")
    raw_text = "\n".join(lines)

    top_species = (results[0].get("species") or {})
    top_name = top_species.get("scientificNameWithoutAuthor") or "-"
    top_common = ", ".join((top_species.get("commonNames") or [])[:3]) or top_name

    if GEMINI_API_KEY or GROQ_API_KEY:
        prompt = (
            f"Bir bitki tanıma API'sinden (PlantNet) şu sonuç çıktı. En olası tür: {top_name} ({top_common}). "
            f"Kullanıcının notu: {note or '-'}. "
            "Bu bitki için Türkçe, kısa ve pratik bakım tavsiyesi ver (sulama, ışık, toprak, dikkat edilmesi gerekenler). "
            "Tanı kesin değilse (skor düşükse) bunu belirt, kesin teşhis gibi konuşma."
        )
        ai_note = await ask_gemini(prompt, context) if GEMINI_API_KEY else await ask_groq(prompt, context)
        return f"{raw_text}\n\nAI Bakım Tavsiyesi:\n{ai_note}"
    return raw_text


async def identify_plant_disease(image_bytes: bytes) -> str:
    """PlantNet'in hastalık/zararlı tespit API'sine bakar. Anahtar yoksa veya sonuç
    gelmezse sessizce boş string döner (bu bir ek/opsiyonel tarama, ana akışı bozmamalı)."""
    if not PLANTNET_API_KEY:
        return ""
    url = "https://my-api.plantnet.org/v2/diseases/identify"
    try:
        response = await asyncio.to_thread(
            lambda: requests.post(
                url,
                params={"api-key": PLANTNET_API_KEY, "lang": "en", "nb-results": 3},
                files=[("images", ("photo.jpg", image_bytes, "image/jpeg"))],
                data={"organs": "auto"},
                timeout=60,
            )
        )
        if not response.ok:
            return ""
        data = response.json()
    except Exception:
        log.exception("PlantNet hastalık taraması hatası")
        return ""

    results = data.get("results", [])[:3]
    if not results:
        return ""
    lines = ["Hastalık/Zararlı Taraması (PlantNet):"]
    for item in results:
        score = (item.get("score") or 0) * 100
        if score < 5:
            continue
        desc = item.get("description") or item.get("name") or "-"
        lines.append(f"- {desc} (%{score:.0f} olasılık)")
    if len(lines) == 1:
        return ""
    lines.append("Not: Bu bir olasılık taramasıdır, kesin teşhis değildir.")
    return "\n".join(lines)


async def ask_gemini(question: str, context: ContextTypes.DEFAULT_TYPE) -> str:
    if not GEMINI_API_KEY:
        return "Gemini API anahtarı eksik. Railway Variables içine GEMINI_API_KEY eklenmeli."
    history = context.user_data.setdefault("gemini_history", [])
    parts = [{"text": "Türkçe cevap veren, bahçecilik ve kayıt yönetiminde pratik öneriler sunan bir asistansın. Kısa, net ve uygulanabilir cevap ver."}]
    for item in history[-8:]:
        role = "Kullanıcı" if item.get("role") == "user" else "Asistan"
        parts.append({"text": f"{role}: {item.get('content', '')}"})
    parts.append({"text": f"Kullanıcı: {question}"})
    payload = {"contents": [{"parts": parts}]}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    try:
        response = await asyncio.to_thread(
            lambda: requests.post(url, params={"key": GEMINI_API_KEY}, json=payload, timeout=45)
        )
        if response.status_code == 403:
            return "Gemini 403 hatası: API key yanlış olabilir, Google AI Studio'da Gemini API açık olmayabilir veya seçilen modele erişimin olmayabilir. GEMINI_API_KEY'i yeni Google AI Studio key'i ile değiştir ve GEMINI_MODEL=gemini-2.5-flash yap."
        if response.status_code == 404:
            return "Gemini model hatası: model bulunamadı. GEMINI_MODEL=gemini-2.5-flash yapıp tekrar dene."
        response.raise_for_status()
        data = response.json()
        response_parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        answer = "\n".join(str(part.get("text", "")).strip() for part in response_parts if part.get("text")).strip()
        if not answer:
            answer = "Gemini cevap döndürmedi."
        history.extend([{"role": "user", "content": question}, {"role": "assistant", "content": answer}])
        context.user_data["gemini_history"] = history[-12:]
        return answer
    except Exception as exc:
        return f"Gemini hatası: {exc}"


async def analyze_image_with_gemini(image_bytes: bytes, note: str) -> str:
    if not GEMINI_API_KEY:
        return "Gemini API anahtarı eksik. Railway Variables içine GEMINI_API_KEY eklenince fotoğraf yorumlama çalışır."
    prompt = (
        "Bu fotoğrafı bahçecilik ve bitki bakımı açısından Türkçe yorumla. "
        "Kısa, pratik ve temkinli ol. Hastalık/zararlı belirtisi varsa olasılık olarak yaz, kesin teşhis gibi konuşma. "
        "Gözlem notu: "
        f"{note or '-'}"
    )
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": base64.b64encode(image_bytes).decode("ascii"),
                    }
                },
            ]
        }]
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    try:
        response = await asyncio.to_thread(
            lambda: requests.post(url, params={"key": GEMINI_API_KEY}, json=payload, timeout=45)
        )
        if response.status_code == 403:
            return "Gemini 403 hatası: API key yanlış olabilir, Gemini API açık olmayabilir veya seçilen modele erişimin olmayabilir. GEMINI_MODEL=gemini-2.5-flash yapıp yeni Google AI Studio key'i gir."
        if response.status_code == 404:
            return "Gemini model hatası: model bulunamadı. GEMINI_MODEL=gemini-2.5-flash yapıp tekrar dene."
        response.raise_for_status()
        data = response.json()
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        text = "\n".join(str(part.get("text", "")).strip() for part in parts if part.get("text")).strip()
        return text or "Gemini fotoğrafı yorumladı ama metin döndürmedi."
    except Exception as exc:
        return f"Gemini fotoğraf yorumlama hatası: {exc}"


def translate_weather(text: str) -> str:
    replacements = {
        "Sunny": "Güneşli",
        "Clear": "Açık",
        "Partly cloudy": "Parçalı bulutlu",
        "Cloudy": "Bulutlu",
        "Overcast": "Kapalı",
        "Rain": "Yağmur",
        "Light rain": "Hafif yağmur",
        "Heavy rain": "Şiddetli yağmur",
        "Mist": "Puslu",
        "Fog": "Sisli",
        "Snow": "Kar",
        "Thunderstorm": "Gök gürültülü",
    }
    for en, tr in replacements.items():
        text = text.replace(en, tr)
    return text


async def is_rain_forecast_today(city: str) -> bool:
    """Bugün için yağmur ihtimali yüksek mi? Hata durumunda sessizce False döner
    (bu bir bonus kontrol, hatırlatmanın gönderilmesini asla engellememeli)."""
    try:
        url = f"https://wttr.in/{city}?format=j1&m"
        data = await asyncio.to_thread(lambda: requests.get(url, timeout=10).json())
        today = (data.get("weather") or [{}])[0]
        chance = 0
        precip = 0.0
        for hour in today.get("hourly", []):
            try:
                chance = max(chance, int(hour.get("chanceofrain", 0)))
            except Exception:
                pass
            try:
                precip += float(hour.get("precipMM", 0))
            except Exception:
                pass
        return chance >= 50 or precip >= 1.0
    except Exception:
        return False


async def show_weather(update: Update, city: str, *, monthly: bool = False) -> None:
    try:
        set_alert_value("garden_city", city)
    except Exception:
        log.exception("Bahçe şehri kaydedilemedi")
    try:
        if monthly:
            url = f"https://wttr.in/{city}?format=j1&lang=tr&m"
            data = await asyncio.to_thread(lambda: requests.get(url, timeout=12).json())
            days = data.get("weather", [])
            text = f"{city} Hava Özeti\n\n"
            text += "Not: Ücretsiz kaynak en yakın günleri verir; aylık özet yerine kısa dönem eğilimi gösteriliyor.\n\n"
            for day in days:
                hourly = day.get("hourly", [{}])
                desc = hourly[0].get("lang_tr", [{}])[0].get("value") or hourly[0].get("weatherDesc", [{}])[0].get("value", "")
                text += f"{parse_date(day.get('date'), allow_words=False) or day.get('date')}: {translate_weather(desc)}, {day.get('mintempC')} / {day.get('maxtempC')} °C\n"
        else:
            url = f"https://wttr.in/{city}?format=j1&lang=tr&m"
            data = await asyncio.to_thread(lambda: requests.get(url, timeout=12).json())
            cur = data["current_condition"][0]
            desc = cur.get("lang_tr", [{}])[0].get("value") or cur.get("weatherDesc", [{}])[0].get("value", "")
            text = (
                f"{city} Anlık Hava\n\n"
                f"Durum: {translate_weather(desc)}\n"
                f"Sıcaklık: {cur.get('temp_C')} °C\n"
                f"Hissedilen: {cur.get('FeelsLikeC')} °C\n"
                f"Nem: %{cur.get('humidity')}\n"
                f"Rüzgar: {cur.get('windspeedKmph')} km/s\n"
            )
        await edit_or_send(update, text, weather_menu())
    except Exception as exc:
        await edit_or_send(update, f"Hava durumu alınamadı: {exc}", weather_menu())


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.effective_message.text or "").strip()
    if text == MENU_BUTTON_TEXT:
        context.user_data.clear()
        await show_home(update)
        return
    flow = context.user_data.get("flow")
    if not flow:
        if text and (GEMINI_API_KEY or GROQ_API_KEY):
            await update.effective_message.chat.send_action(ChatAction.TYPING)
            parsed = await parse_quick_log(text, context)
            if parsed:
                context.user_data["quick_log_pending"] = parsed
                await update.effective_message.reply_text(quick_log_summary(parsed), reply_markup=quick_log_confirm_kb())
                return
        await update.effective_message.reply_text("Lütfen menüden bir buton seç.", reply_markup=main_menu())
        return

    if text.casefold() in {"iptal", "/iptal"}:
        await cancel(update, context)
        return

    if flow == "ai_agnes":
        await update.effective_message.chat.send_action(ChatAction.TYPING)
        if not context.user_data.get("ai_history") and not context.user_data.get("ai_memory_cleared"):
            context.user_data["ai_history"] = load_persistent_ai_history("ai_agnes_logs", update.effective_user.id)
        answer = await ask_ai(text, update.effective_user.id, context)
        log_ai("ai_agnes_logs", update.effective_user.id, "metin", text, answer)
        for part in chunks(f"Agnes AI:\n\n{answer}"):
            await update.effective_message.reply_text(part)
        await update.effective_message.reply_text("Başka bir soru yazabilir veya geri dönebilirsin.", reply_markup=back_cancel("m:ai"))
        return
    if flow == "ai_gemini":
        await update.effective_message.chat.send_action(ChatAction.TYPING)
        if not context.user_data.get("gemini_history") and not context.user_data.get("ai_memory_cleared"):
            context.user_data["gemini_history"] = load_persistent_ai_history("ai_gemini_logs", update.effective_user.id)
        answer = await ask_gemini(text, context)
        log_ai("ai_gemini_logs", update.effective_user.id, "metin", text, answer)
        for part in chunks(f"Gemini:\n\n{answer}"):
            await update.effective_message.reply_text(part)
        await update.effective_message.reply_text("Başka bir soru yazabilir veya geri dönebilirsin.", reply_markup=back_cancel("m:ai"))
        return
    if flow == "ai_groq":
        await update.effective_message.chat.send_action(ChatAction.TYPING)
        if not context.user_data.get("groq_history") and not context.user_data.get("ai_memory_cleared"):
            context.user_data["groq_history"] = load_persistent_ai_history("ai_groq_logs", update.effective_user.id)
        answer = await ask_groq(text, context)
        log_ai("ai_groq_logs", update.effective_user.id, "metin", text, answer)
        for part in chunks(f"Groq:\n\n{answer}"):
            await update.effective_message.reply_text(part)
        context.user_data["flow"] = "ai_groq"
        await update.effective_message.reply_text("Başka bir soru yazabilir veya AI menüsüne dönebilirsin.", reply_markup=back_cancel("m:ai"))
        return
    if flow == "ai_web":
        await update.effective_message.chat.send_action(ChatAction.TYPING)
        answer = await ask_web_search(text, context)
        log_ai("ai_web_logs", update.effective_user.id, "arama", text, answer)
        for part in chunks(f"Güncel Arama:\n\n{answer}"):
            await update.effective_message.reply_text(part)
        context.user_data["flow"] = "ai_web"
        await update.effective_message.reply_text("Başka bir arama yazabilir veya AI menüsüne dönebilirsin.", reply_markup=back_cancel("m:ai"))
        return
    if flow == "ai_docq":
        await update.effective_message.chat.send_action(ChatAction.TYPING)
        answer = await answer_from_docs(text, context)
        log_ai("ai_file_logs", update.effective_user.id, "dosya_soru", text, answer)
        for part in chunks(f"Dosya Hafızası:\n\n{answer}"):
            await update.effective_message.reply_text(part)
        await update.effective_message.reply_text("Başka bir dosya sorusu yazabilir veya geri dönebilirsin.", reply_markup=back_cancel("m:ai"))
        return
    if flow == "ai_records":
        await update.effective_message.chat.send_action(ChatAction.TYPING)
        answer = await ask_about_records(text, context)
        log_ai("ai_gemini_logs" if GEMINI_API_KEY else "ai_groq_logs", update.effective_user.id, "kayit_sorgu", text, answer)
        for part in chunks(f"Kayıtlara Göre:\n\n{answer}"):
            await update.effective_message.reply_text(part)
        context.user_data["flow"] = "ai_records"
        await update.effective_message.reply_text("Başka bir soru yazabilir veya AI menüsüne dönebilirsin.", reply_markup=back_cancel("m:ai"))
        return
    if flow == "ai_both":
        await update.effective_message.chat.send_action(ChatAction.TYPING)
        if not context.user_data.get("ai_history") and not context.user_data.get("ai_memory_cleared"):
            context.user_data["ai_history"] = load_persistent_ai_history("ai_agnes_logs", update.effective_user.id)
        if not context.user_data.get("gemini_history") and not context.user_data.get("ai_memory_cleared"):
            context.user_data["gemini_history"] = load_persistent_ai_history("ai_gemini_logs", update.effective_user.id)
        agnes_answer, gemini_answer = await asyncio.gather(
            ask_ai(text, update.effective_user.id, context),
            ask_gemini(text, context),
        )
        combined = f"Agnes AI:\n\n{agnes_answer}\n\nGemini:\n\n{gemini_answer}"
        log_ai("ai_agnes_logs", update.effective_user.id, "ikisine_sor", text, agnes_answer)
        log_ai("ai_gemini_logs", update.effective_user.id, "ikisine_sor", text, gemini_answer)
        for part in chunks(combined):
            await update.effective_message.reply_text(part)
        await update.effective_message.reply_text("Başka bir soru yazabilir veya geri dönebilirsin.", reply_markup=back_cancel("m:ai"))
        return

    if flow == "recipe_ai_prompt":
        await update.effective_message.chat.send_action(ChatAction.TYPING)
        prompt = (
            "Bahçecilik için güvenli, pratik bir reçete tasarla. Türkçe yaz. "
            "Başlık, amaç, malzemeler, uygulama adımları, pH önerisi, uyarılar şeklinde düzenle. "
            f"Kullanıcının istediği reçete: {text}"
        )
        answer = await ask_gemini(prompt, context) if GEMINI_API_KEY else await ask_groq(prompt, context)
        context.user_data["draft"] = {"ai_recipe_name": f"AI Reçete - {text[:40]}", "ai_recipe": answer}
        log_ai("ai_gemini_logs" if GEMINI_API_KEY else "ai_groq_logs", update.effective_user.id, "reçete", text, answer)
        for part in chunks(f"AI Reçete Taslağı:\n\n{answer}"):
            await update.effective_message.reply_text(part)
        await update.effective_message.reply_text("Beğendiysen kaydedebilirsin.", reply_markup=kb([[("Kaydet", "recipe:ai_save"), ("Vazgeç", "m:recipes")], [("Ana Menü", "m:main")]]))
        return

    if flow == "ailog_delete":
        mapping = {"agnes": "ai_agnes_logs", "gemini": "ai_gemini_logs", "groq": "ai_groq_logs", "arama": "ai_web_logs", "ses": "ai_voice_logs", "dosya": "ai_file_logs", "gorsel": "ai_image_logs", "görsel": "ai_image_logs"}
        parts = text.split()
        if len(parts) != 2 or parts[0].casefold() not in mapping:
            await update.effective_message.reply_text("Format: sayfa ID\nÖrnek: groq 12", reply_markup=back_cancel("ai:logs"))
            return
        await delete_by_id(update, mapping[parts[0].casefold()], parts[1], "AI kaydı silindi.", ai_logs_menu())
        context.user_data.clear()
        return

    if flow == "plant_search":
        await update.effective_message.chat.send_action(ChatAction.TYPING)
        try:
            answer = await search_plant(text, context)
        except Exception as exc:
            answer = f"Bitki arama hatası: {exc}"
        await send_chunks(update, answer, plant_ai_menu())
        return

    if flow == "plant_care":
        await update.effective_message.chat.send_action(ChatAction.TYPING)
        try:
            answer = await plant_care(text, context)
        except Exception as exc:
            answer = f"Bitki bakım hatası: {exc}"
        log_ai("ai_gemini_logs" if GEMINI_API_KEY else "ai_groq_logs", update.effective_user.id, "bitki_bakim", text, answer)
        await send_chunks(update, answer, plant_ai_menu())
        return

    if flow == "plant_advice":
        await update.effective_message.chat.send_action(ChatAction.TYPING)
        prompt = f"Bitki bakım sorusuna Türkçe, pratik ve temkinli cevap ver. Soru: {text}"
        answer = await ask_gemini(prompt, context) if GEMINI_API_KEY else await ask_groq(prompt, context)
        log_ai("ai_gemini_logs" if GEMINI_API_KEY else "ai_groq_logs", update.effective_user.id, "bitki_ai", text, answer)
        await send_chunks(update, answer, plant_ai_menu())
        return

    if flow == "quick_search":
        result = build_search_results(text)
        await send_chunks(update, result)
        context.user_data["flow"] = "quick_search"
        await update.effective_message.reply_text("Başka bir kelime yazabilir veya menüye dönebilirsin.", reply_markup=back_cancel("g:system"))
        return
    if flow == "stock_search":
        item = find_inventory_by_name(text)
        if not item:
            await update.effective_message.reply_text("Malzeme bulunamadı.", reply_markup=stock_menu())
            return
        fake_update = update
        await send_chunks(fake_update, f"{item.get('Malzeme / Alet')}\nKalan: {item.get('Kalan Miktar')} {item.get('Birim', '')}\nGörev/Not: {item.get('Görevi / Not', '-')}", stock_menu())
        return

    if flow == "stock_add_name":
        if find_inventory_by_name(text):
            await update.effective_message.reply_text("Bu malzeme zaten var. Başka bir ad yaz.", reply_markup=back_cancel("stock:add"))
            return
        context.user_data["draft"]["name"] = text
        context.user_data["flow"] = "stock_add_amount"
        await update.effective_message.reply_text("Miktar yaz. Örn: 1000", reply_markup=back_cancel("stock:add"))
        return
    if flow == "stock_add_amount":
        try:
            amount = parse_decimal(text)
        except Exception:
            await update.effective_message.reply_text("Miktar sayı olmalı. Örn: 1000 veya 12,5", reply_markup=back_cancel("stock:add"))
            return
        context.user_data["draft"]["amount"] = format_decimal(amount)
        await update.effective_message.reply_text("Birim seç:", reply_markup=unit_menu("stock:add"))
        return
    if flow == "stock_add_note":
        context.user_data["draft"]["note"] = "" if text == "-" else text
        context.user_data["flow"] = "stock_add_expiry"
        await update.effective_message.reply_text("Son kullanma tarihi var mı? Yaz (ör. 31-12-2026) ya da yoksa '-' yaz.", reply_markup=back_cancel("stock:add"))
        return
    if flow == "stock_add_expiry":
        d = context.user_data["draft"]
        expiry = ""
        if text.strip() != "-":
            parsed_expiry = parse_date(text)
            if not parsed_expiry:
                await update.effective_message.reply_text("Tarih anlaşılamadı. Örn: 31-12-2026 ya da yoksa '-' yaz.", reply_markup=back_cancel("stock:add"))
                return
            expiry = parsed_expiry
        item_id = next_id("inventory")
        append_record("inventory", INVENTORY_HEADERS, {
            "ID": item_id,
            "Kategori": d["category"],
            "Malzeme / Alet": d["name"],
            "Başlangıç Miktarı": d["amount"],
            "Kullanılan": "0",
            "Kalan Miktar": d["amount"],
            "Birim": d["unit"],
            "Görevi / Not": d.get("note", ""),
            "Son_Kullanma": expiry,
            "CreatedAt": now().isoformat(timespec="seconds"),
        })
        add_history("ENVANTERE EKLENDİ", d["name"], d["amount"], d["unit"], "", d.get("note", ""))
        context.user_data.clear()
        await update.effective_message.reply_text(f"Malzeme eklendi: {d['name']} ({d['amount']} {d['unit']})", reply_markup=stock_menu())
        return

    if flow == "stock_use_amount":
        try:
            amount = parse_decimal(text)
        except Exception:
            await update.effective_message.reply_text("Miktar sayı olmalı.", reply_markup=back_cancel("stock:use"))
            return
        context.user_data["draft"]["amount"] = amount
        await update.effective_message.reply_text("İşlem türü seç:", reply_markup=operation_type_menu("use"))
        return
    if flow == "stock_use_note":
        d = context.user_data["draft"]
        ok, result, undo = use_stock(d["material"], d["amount"], d["unit"], d.get("type", "Kullanım"), "" if text == "-" else text)
        if ok and undo:
            context.user_data["last_stock_use"] = undo
        context.user_data.pop("flow", None)
        context.user_data.pop("draft", None)
        await update.effective_message.reply_text(("Stoktan düşüldü. Kalan: " + result) if ok else result, reply_markup=stock_menu())
        return

    if flow.startswith("ph_") and flow.endswith("_custom"):
        action = flow.removeprefix("ph_").removesuffix("_custom")
        context.user_data.pop("flow", None)
        if action == "add":
            context.user_data["draft"] = {"teneke": text}
            context.user_data["flow"] = "ph_add_value"
            await update.effective_message.reply_text(f"{text}\n\npH değerini yaz. Örn: 6.5", reply_markup=back_cancel("m:ph"))
            return
        if action == "delete_last":
            await delete_last_ph_for_teneke(update, text)
            return
        await show_ph_for_teneke(update, text, action)
        return
    if flow == "ph_add_teneke":
        context.user_data["draft"]["teneke"] = text
        context.user_data["flow"] = "ph_add_value"
        await update.effective_message.reply_text("pH değerini yaz. Örn: 6.5", reply_markup=back_cancel("m:ph"))
        return
    if flow == "ph_add_value":
        try:
            value = parse_decimal(text)
            if not 0 <= value <= 14:
                raise ValueError
        except Exception:
            await update.effective_message.reply_text("pH 0 ile 14 arasında sayı olmalı.", reply_markup=back_cancel("m:ph"))
            return
        context.user_data["draft"]["ph"] = str(text).replace(",", ".")
        context.user_data["flow"] = "ph_add_note"
        await update.effective_message.reply_text("Not yaz. Not yoksa '-' yaz.", reply_markup=back_cancel("m:ph"))
        return
    if flow == "ph_add_note":
        d = context.user_data["draft"]
        item_id = next_id("ph_records")
        append_record("ph_records", PH_HEADERS, {
            "ID": item_id,
            "Tarih": today_str(),
            "Teneke_No": d["teneke"],
            "pH": d["ph"],
            "Not": "" if text == "-" else text,
            "CreatedAt": now().isoformat(timespec="seconds"),
        })
        context.user_data.clear()
        await update.effective_message.reply_text(f"pH kaydedildi. ID {item_id} - Teneke {d['teneke']} pH {d['ph']}", reply_markup=ph_menu())
        return
    if flow == "ph_delete":
        await delete_by_id(update, "ph_records", text, "pH kaydı silindi.", ph_menu())
        context.user_data.clear()
        return

    if flow == "history_date":
        date = parse_date(text)
        if not date:
            await update.effective_message.reply_text("Tarih anlaşılamadı. Örn: 14-06-2026", reply_markup=back_cancel("m:history"))
            return
        rows = [r for r in records("history") if r.get("Tarih") == date]
        if not rows:
            await update.effective_message.reply_text(f"{date} tarihinde işlem yok.", reply_markup=history_menu())
            return
        out = f"{date} İşlemleri\n\n"
        for row in rows:
            out += f"ID {row_id_text(row)} - {row.get('Islem', '-')}: {history_material(row) or '-'} {history_amount(row)} {history_unit(row)}\n"
        await send_chunks(update, out, history_menu())
        return
    if flow == "history_delete":
        await delete_by_id(update, "history", text, "İşlem silindi.", history_menu())
        context.user_data.clear()
        return
    if flow == "histadd_custom_date":
        date = parse_date(text)
        if not date:
            await update.effective_message.reply_text("Tarih anlaşılamadı. Örn: 14-06-2026", reply_markup=back_cancel("hist:add"))
            return
        context.user_data["draft"]["date"] = date
        await update.effective_message.reply_text("İşlem türü seç:", reply_markup=operation_type_menu("histadd"))
        return
    if flow == "histadd_amount":
        try:
            amount = parse_decimal(text)
        except Exception:
            await update.effective_message.reply_text("Miktar sayı olmalı.", reply_markup=back_cancel("m:history"))
            return
        d = context.user_data["draft"]
        item = {
            "material": d["current_material"],
            "unit": d.get("current_unit", ""),
            "amount": amount,
        }
        d.setdefault("items", []).append(item)
        d.pop("current_material", None)
        d.pop("current_unit", None)
        summary = "\n".join(
            f"- {format_decimal(i['amount'])} {i['unit']} {i['material']}" for i in d["items"]
        )
        await update.effective_message.reply_text(
            f"Malzeme eklendi.\n\nSeçilenler:\n{summary}\n\nBaşka malzeme ekleyebilir veya devam edebilirsin.",
            reply_markup=histadd_continue_menu(),
        )
        return
    if flow == "histadd_custom_ph":
        try:
            ph_value = parse_decimal(text)
            if not 0 <= ph_value <= 14:
                raise ValueError
        except Exception:
            await update.effective_message.reply_text("pH 0 ile 14 arasında sayı olmalı. Örn: 6.3", reply_markup=back_cancel("m:history"))
            return
        context.user_data.setdefault("draft", {})["ph"] = str(text).replace(",", ".")
        context.user_data["flow"] = "histadd_note"
        await update.effective_message.reply_text("Not yaz. Ne için yaptığını buraya yazabilirsin. Not yoksa '-' yaz.", reply_markup=back_cancel("m:history"))
        return
    if flow == "histadd_note":
        d = context.user_data["draft"]
        note = "" if text == "-" else text
        items = d.get("items", [])
        if not items:
            await update.effective_message.reply_text("Kaydedilecek malzeme yok.", reply_markup=history_menu())
            context.user_data.clear()
            return
        for item in items:
            ok, error = check_stock_available(item["material"], item["amount"])
            if not ok:
                await update.effective_message.reply_text(error, reply_markup=history_menu())
                return
        results = []
        undo_items = []
        for item in items:
            ok, result, undo = use_stock(
                item["material"],
                item["amount"],
                item["unit"],
                d["type"],
                note,
                d["date"],
                d.get("ph", ""),
                record_history=False,
            )
            if not ok:
                await update.effective_message.reply_text(result, reply_markup=history_menu())
                return
            results.append(f"{format_decimal(item['amount'])} {item['unit']} {item['material']} (Kalan: {result})")
            if undo:
                undo_items.append(undo)
        material_summary = "; ".join(f"{format_decimal(i['amount'])} {i['unit']} {i['material']}" for i in items)
        add_history(d["type"], material_summary, "-", "", d.get("ph", ""), note, d["date"])
        if undo_items:
            context.user_data["last_stock_use"] = undo_items[-1]
        context.user_data.pop("flow", None)
        context.user_data.pop("draft", None)
        await update.effective_message.reply_text(
            "İşlem kaydedildi ve stoktan düşüldü.\n\n" + "\n".join(results),
            reply_markup=history_menu(),
        )
        return

    if flow == "compost_date":
        date = parse_date(text)
        if not date:
            await update.effective_message.reply_text("Tarih anlaşılamadı. Örn: 14-06-2026", reply_markup=back_cancel("m:compost"))
            return
        rows = [r for r in records("Kompost") if parse_date(str(r.get("Tarih", ""))) == date]
        if not rows:
            await update.effective_message.reply_text(f"{date} tarihinde Kompost işlemi yok.", reply_markup=compost_menu())
            return
        out = f"{date} Kompost İşlemleri\n\n"
        for row in rows:
            out += compost_row_text(row) + "\n\n"
        await send_chunks(update, out, compost_menu())
        return
    if flow == "compost_delete":
        await delete_by_id(update, "Kompost", text, "Kompost işlemi silindi.", compost_menu())
        context.user_data.clear()
        return
    if flow == "compadd_custom_date":
        date = parse_date(text)
        if not date:
            await update.effective_message.reply_text("Tarih anlaşılamadı. Örn: 14-06-2026", reply_markup=back_cancel("comp:add"))
            return
        context.user_data["draft"]["date"] = date
        await update.effective_message.reply_text("Konteyner seç. Birden fazla seçebilirsin:", reply_markup=compost_container_menu(context.user_data["draft"].get("containers", [])))
        return
    if flow == "compadd_amount":
        try:
            amount = parse_decimal(text)
        except Exception:
            await update.effective_message.reply_text("Miktar sayı olmalı.", reply_markup=back_cancel("m:compost"))
            return
        d = context.user_data["draft"]
        item = {
            "material": d["current_material"],
            "unit": d.get("current_unit", ""),
            "amount": amount,
        }
        d.setdefault("items", []).append(item)
        d.pop("current_material", None)
        d.pop("current_unit", None)
        summary = "\n".join(f"- {format_decimal(i['amount'])} {i['unit']} {i['material']}" for i in d["items"])
        await update.effective_message.reply_text(
            f"Malzeme eklendi.\n\nSeçilenler:\n{summary}\n\nBaşka malzeme ekleyebilir veya devam edebilirsin.",
            reply_markup=kb([
                [("Başka Malzeme Ekle", "compadd:more")],
                [("Devam Et", "compadd:done")],
                [("Geri", "m:compost"), ("İptal", "cancel"), ("Ana Menü", "m:main")],
            ]),
        )
        return
    if flow == "compadd_custom_ph":
        try:
            ph_value = parse_decimal(text)
            if not 0 <= ph_value <= 14:
                raise ValueError
        except Exception:
            await update.effective_message.reply_text("pH 0 ile 14 arasında sayı olmalı. Örn: 6.8", reply_markup=back_cancel("m:compost"))
            return
        context.user_data.setdefault("draft", {})["ph"] = str(text).replace(",", ".")
        context.user_data["flow"] = "compadd_note"
        await update.effective_message.reply_text("Not yaz. Not yoksa '-' yaz.", reply_markup=back_cancel("m:compost"))
        return
    if flow == "compadd_note":
        d = context.user_data["draft"]
        note = "" if text == "-" else text
        items = d.get("items", [])
        containers = d.get("containers", [])
        for item in items:
            ok, error = check_stock_available(item["material"], item["amount"])
            if not ok:
                await update.effective_message.reply_text(error, reply_markup=compost_menu())
                return
        results = []
        undo_items = []
        for item in items:
            ok, result, undo = use_stock(
                item["material"],
                item["amount"],
                item["unit"],
                d["type"],
                note,
                d["date"],
                d.get("ph", ""),
                record_history=False,
            )
            if not ok:
                await update.effective_message.reply_text(result, reply_markup=compost_menu())
                return
            results.append(f"{format_decimal(item['amount'])} {item['unit']} {item['material']} (Kalan: {result})")
            if undo:
                undo_items.append(undo)
        material_summary = "; ".join(f"{format_decimal(i['amount'])} {i['unit']} {i['material']}" for i in items) if items else "Malzeme kullanılmadı"
        container_summary = ", ".join(containers)
        full_note = f"Konteyner: {container_summary}"
        if note:
            full_note += f"\n{note}"
        item_id = next_id("Kompost")
        append_record("Kompost", KOMPOST_HEADERS, {
            "Tarih": d["date"],
            "Islem": d["type"],
            "Kullanilan_Malzeme_Miktar": material_summary,
            "pH": d.get("ph", ""),
            "Not": full_note,
            "ID": item_id,
        })
        if d.get("ph"):
            for container in containers:
                append_record("ph_records", PH_HEADERS, {
                    "ID": next_id("ph_records"),
                    "Tarih": d["date"],
                    "Teneke_No": container,
                    "pH": d.get("ph", ""),
                    "Not": f"Kompost ID {item_id} - {d['type']}",
                    "CreatedAt": now().isoformat(timespec="seconds"),
                })
        if undo_items:
            context.user_data["last_stock_use"] = undo_items[-1]
        context.user_data.pop("flow", None)
        context.user_data.pop("draft", None)
        result_text = "\n".join(results) if results else "Stoktan düşülen malzeme yok."
        await update.effective_message.reply_text(
            f"Kompost işlemi kaydedildi. ID {item_id}\n\n" + result_text,
            reply_markup=compost_menu(),
        )
        return

    if flow == "planadd_custom_date":
        date = parse_date(text)
        if not date:
            await update.effective_message.reply_text("Tarih anlaşılamadı. Örn: 14-06-2026", reply_markup=back_cancel("plan:add"))
            return
        context.user_data["draft"]["date"] = date
        await update.effective_message.reply_text("Plan işlem türü seç:", reply_markup=operation_type_menu("planadd"))
        return
    if flow == "planadd_target":
        context.user_data.setdefault("draft", {})["target"] = "" if text == "-" else text
        await update.effective_message.reply_text("Plan için malzeme seç veya malzeme kullanmayacaksan devam et:", reply_markup=inventory_buttons("planadd"))
        return
    if flow == "planadd_amount":
        try:
            amount = parse_decimal(text)
        except Exception:
            await update.effective_message.reply_text("Miktar sayı olmalı.", reply_markup=back_cancel("m:plan"))
            return
        d = context.user_data["draft"]
        item = {
            "material": d["current_material"],
            "unit": d.get("current_unit", ""),
            "amount": amount,
        }
        d.setdefault("items", []).append(item)
        d.pop("current_material", None)
        d.pop("current_unit", None)
        summary = "\n".join(f"- {format_decimal(i['amount'])} {i['unit']} {i['material']}" for i in d["items"])
        await update.effective_message.reply_text(
            f"Malzeme plana eklendi.\n\nSeçilenler:\n{summary}\n\nBaşka malzeme ekleyebilir veya devam edebilirsin.",
            reply_markup=planadd_continue_menu(),
        )
        return
    if flow == "planadd_custom_ph":
        try:
            ph_value = parse_decimal(text)
            if not 0 <= ph_value <= 14:
                raise ValueError
        except Exception:
            await update.effective_message.reply_text("pH 0 ile 14 arasında sayı olmalı. Örn: 6.3", reply_markup=back_cancel("m:plan"))
            return
        context.user_data.setdefault("draft", {})["ph"] = str(text).replace(",", ".")
        context.user_data["flow"] = "planadd_note"
        await update.effective_message.reply_text("Plan notu yaz. Not yoksa '-' yaz.", reply_markup=back_cancel("m:plan"))
        return
    if flow == "planadd_note":
        d = context.user_data["draft"]
        items = d.get("items", [])
        material_summary = "; ".join(f"{format_decimal(i['amount'])} {i['unit']} {i['material']}" for i in items) if items else "Malzeme kullanılmadı"
        item_id = next_id("plans")
        append_record("plans", PLAN_HEADERS, {
            "ID": item_id,
            "Tarih": d["date"],
            "Islem": d["type"],
            "Hedef": d.get("target", ""),
            "Malzeme_Miktar": material_summary,
            "pH": d.get("ph", ""),
            "Not": "" if text == "-" else text,
            "Durum": "bekliyor",
            "CreatedAt": now().isoformat(timespec="seconds"),
            "CompletedAt": "",
        })
        context.user_data.clear()
        await update.effective_message.reply_text(f"Plan kaydedildi. ID {item_id}", reply_markup=plan_menu())
        return
    if flow == "plan_date":
        date = parse_date(text)
        if not date:
            await update.effective_message.reply_text("Tarih anlaşılamadı. Örn: 14-06-2026", reply_markup=back_cancel("m:plan"))
            return
        await show_plans(update, date=date)
        return
    if flow == "plan_delete":
        await delete_by_id(update, "plans", text, "Plan silindi.", plan_menu())
        context.user_data.clear()
        return
    if flow == "plan_complete":
        await complete_plan(update, text)
        context.user_data.clear()
        return

    if flow == "area_add_name":
        name = text.strip()
        if not name:
            await update.effective_message.reply_text("Alan adı boş olamaz.", reply_markup=back_cancel("m:areas"))
            return
        for row in records("areas"):
            if normalize_name(row.get("Alan")) == normalize_name(name):
                await update.effective_message.reply_text("Bu alan zaten kayıtlı. Başka bir ad yaz.", reply_markup=back_cancel("m:areas"))
                return
        context.user_data["draft"] = {"name": name}
        context.user_data["flow"] = "area_add_note"
        await update.effective_message.reply_text("Alan notu yaz. Not yoksa '-' yaz.", reply_markup=back_cancel("m:areas"))
        return
    if flow == "area_add_note":
        d = context.user_data["draft"]
        item_id = next_id("areas")
        append_record("areas", AREA_HEADERS, {
            "ID": item_id,
            "Alan": d["name"],
            "Not": "" if text == "-" else text,
            "Durum": "aktif",
            "CreatedAt": now().isoformat(timespec="seconds"),
        })
        context.user_data.clear()
        await update.effective_message.reply_text(f"Alan eklendi. ID {item_id} - {d['name']}", reply_markup=area_menu())
        return
    if flow == "area_delete":
        await delete_by_id(update, "areas", text, "Alan silindi.", area_menu())
        context.user_data.clear()
        return

    if flow == "recipeadd_name":
        name = text.strip()
        if not name:
            await update.effective_message.reply_text("Reçete adı boş olamaz.", reply_markup=back_cancel("m:recipes"))
            return
        context.user_data.setdefault("draft", {"items": []})["name"] = name
        await update.effective_message.reply_text("Reçetenin işlem türünü seç:", reply_markup=operation_type_menu("recipeadd"))
        return
    if flow == "recipeadd_amount":
        try:
            amount = parse_decimal(text)
        except Exception:
            await update.effective_message.reply_text("Miktar sayı olmalı.", reply_markup=back_cancel("m:recipes"))
            return
        d = context.user_data["draft"]
        d.setdefault("items", []).append({
            "material": d["current_material"],
            "unit": d.get("current_unit", ""),
            "amount": amount,
        })
        d.pop("current_material", None)
        d.pop("current_unit", None)
        summary = "\n".join(f"- {format_decimal(i['amount'])} {i['unit']} {i['material']}" for i in d["items"])
        await update.effective_message.reply_text(
            f"Malzeme reçeteye eklendi.\n\n{summary}\n\nBaşka malzeme ekleyebilir veya devam edebilirsin.",
            reply_markup=recipeadd_continue_menu(),
        )
        return
    if flow == "recipeadd_custom_ph":
        try:
            ph_value = parse_decimal(text)
            if not 0 <= ph_value <= 14:
                raise ValueError
        except Exception:
            await update.effective_message.reply_text("pH 0 ile 14 arasında sayı olmalı. Örn: 6.3", reply_markup=back_cancel("m:recipes"))
            return
        context.user_data.setdefault("draft", {})["ph"] = str(text).replace(",", ".")
        context.user_data["flow"] = "recipeadd_note"
        await update.effective_message.reply_text("Reçete notu yaz. Not yoksa '-' yaz.", reply_markup=back_cancel("m:recipes"))
        return
    if flow == "recipeadd_note":
        d = context.user_data["draft"]
        items = d.get("items", [])
        material_summary = "; ".join(f"{format_decimal(i['amount'])} {i['unit']} {i['material']}" for i in items)
        item_id = next_id("recipes")
        append_record("recipes", RECIPE_HEADERS, {
            "ID": item_id,
            "Ad": d["name"],
            "Islem": d.get("type", "Reçete"),
            "Malzeme_Miktar": material_summary,
            "pH": d.get("ph", ""),
            "Not": "" if text == "-" else text,
            "Durum": "aktif",
            "CreatedAt": now().isoformat(timespec="seconds"),
        })
        context.user_data.clear()
        await update.effective_message.reply_text(f"Reçete kaydedildi. ID {item_id}", reply_markup=recipe_menu())
        return
    if flow == "recipe_apply":
        await apply_recipe(update, text)
        context.user_data.clear()
        return
    if flow == "recipe_delete":
        await delete_by_id(update, "recipes", text, "Reçete silindi.", recipe_menu())
        context.user_data.clear()
        return

    if flow == "issue_add_area":
        context.user_data["draft"] = {"area": "" if text == "-" else text}
        context.user_data["flow"] = "issue_add_title"
        await update.effective_message.reply_text("Sorun başlığını yaz.", reply_markup=back_cancel("m:issues"))
        return
    if flow == "issue_add_title":
        context.user_data["draft"]["title"] = text
        context.user_data["flow"] = "issue_add_note"
        await update.effective_message.reply_text("Sorun notunu yaz.", reply_markup=back_cancel("m:issues"))
        return
    if flow == "issue_add_note":
        d = context.user_data["draft"]
        item_id = next_id("issues")
        append_record("issues", ISSUE_HEADERS, {"ID": item_id, "Tarih": today_str(), "Alan": d.get("area", ""), "Baslik": d["title"], "Not": text, "Durum": "açık", "CreatedAt": now().isoformat(timespec="seconds"), "ClosedAt": ""})
        context.user_data.clear()
        await update.effective_message.reply_text(f"Sorun açıldı. ID {item_id}", reply_markup=issue_menu())
        return
    if flow == "issue_note_id":
        context.user_data["draft"] = {"id": text.strip()}
        context.user_data["flow"] = "issue_note_text"
        await update.effective_message.reply_text("Eklenecek işlem/notu yaz.", reply_markup=back_cancel("m:issues"))
        return
    if flow == "issue_note_text":
        wanted = context.user_data["draft"]["id"]
        for row in records("issues"):
            if row_id_text(row) == wanted:
                set_cell_by_header("issues", int(row["_row"]), "Not", f"{row.get('Not','')}\n[{today_str()}] {text}".strip())
                context.user_data.clear()
                await update.effective_message.reply_text("Soruna not eklendi.", reply_markup=issue_menu())
                return
        await update.effective_message.reply_text("Sorun ID bulunamadı.", reply_markup=issue_menu())
        context.user_data.clear()
        return
    if flow == "issue_close_id":
        context.user_data["draft"] = {"id": text.strip()}
        context.user_data["flow"] = "issue_close_note"
        await update.effective_message.reply_text("Kapanış notu yaz.", reply_markup=back_cancel("m:issues"))
        return
    if flow == "issue_close_note":
        wanted = context.user_data["draft"]["id"]
        for row in records("issues"):
            if row_id_text(row) == wanted:
                set_cells_by_header("issues", int(row["_row"]), {
                    "Durum": "kapalı",
                    "ClosedAt": now().isoformat(timespec="seconds"),
                    "Not": f"{row.get('Not','')}\n[KAPANIŞ {today_str()}] {text}".strip(),
                })
                context.user_data.clear()
                await update.effective_message.reply_text("Sorun kapatıldı.", reply_markup=issue_menu())
                return
        await update.effective_message.reply_text("Sorun ID bulunamadı.", reply_markup=issue_menu())
        context.user_data.clear()
        return

    if flow == "diary_custom_date":
        date = parse_date(text)
        if not date:
            await update.effective_message.reply_text("Tarih anlaşılamadı.", reply_markup=back_cancel("m:diary"))
            return
        context.user_data["draft"]["date"] = date
        context.user_data["flow"] = "diary_note"
        await update.effective_message.reply_text("Günlük notunu yaz.", reply_markup=back_cancel("m:diary"))
        return
    if flow == "diary_note":
        item_id = next_id("diary")
        append_record("diary", DIARY_HEADERS, {"ID": item_id, "Tarih": context.user_data["draft"]["date"], "Not": text, "CreatedAt": now().isoformat(timespec="seconds")})
        context.user_data.clear()
        await update.effective_message.reply_text(f"Günlük kaydedildi. ID {item_id}", reply_markup=diary_menu())
        return
    if flow == "diary_find_date":
        date = parse_date(text)
        if not date:
            await update.effective_message.reply_text("Tarih anlaşılamadı.", reply_markup=back_cancel("m:diary"))
            return
        await show_diary(update, date)
        return
    if flow == "diary_ai_date":
        date = parse_date(text)
        if not date:
            await update.effective_message.reply_text("Tarih anlaşılamadı.", reply_markup=back_cancel("m:diary"))
            return
        await diary_ai_summary(update, context, date)
        return
    if flow == "diary_delete":
        await delete_by_id(update, "diary", text, "Günlük silindi.", diary_menu())
        context.user_data.clear()
        return

    if flow == "ess_flower":
        context.user_data["draft"]["flower"] = text
        await update.effective_message.reply_text("Yağı stoktan seç:", reply_markup=inventory_buttons("essoil"))
        return
    if flow == "ess_oil_amount":
        try:
            amount = parse_decimal(text)
        except Exception:
            await update.effective_message.reply_text("Miktar sayı olmalı.", reply_markup=back_cancel("m:essence"))
            return
        context.user_data["draft"]["oil_amount"] = amount
        context.user_data["flow"] = "ess_jar"
        await update.effective_message.reply_text("Kap/kavanoz adını yaz.", reply_markup=back_cancel("m:essence"))
        return
    if flow == "ess_jar":
        context.user_data["draft"]["jar"] = text
        context.user_data["flow"] = "ess_days"
        await update.effective_message.reply_text("Kaç gün bekleyecek?", reply_markup=back_cancel("m:essence"))
        return
    if flow == "ess_days":
        try:
            int(text)
        except Exception:
            await update.effective_message.reply_text("Gün sayı olmalı.", reply_markup=back_cancel("m:essence"))
            return
        context.user_data["draft"]["days"] = text
        context.user_data["flow"] = "ess_note"
        await update.effective_message.reply_text("Not yaz. Yoksa '-' yaz.", reply_markup=back_cancel("m:essence"))
        return
    if flow == "ess_note":
        d = context.user_data["draft"]
        ok, result, _undo = use_stock(d["oil_material"], d["oil_amount"], d.get("oil_unit", ""), "Esans", "" if text == "-" else text, d["date"], "", record_history=True)
        if not ok:
            await update.effective_message.reply_text(result, reply_markup=essence_menu())
            return
        item_id = next_id("essences")
        oil_text = f"{format_decimal(d['oil_amount'])} {d.get('oil_unit','')} {d['oil_material']}"
        append_record("essences", ESSENCE_HEADERS, {"ID": item_id, "Baslangic": d["date"], "Cicek": d["flower"], "Yag": oil_text, "Kap": d["jar"], "Gun": d["days"], "Not": "" if text == "-" else text, "Durum": "aktif", "CreatedAt": now().isoformat(timespec="seconds"), "ClosedAt": ""})
        context.user_data.clear()
        await update.effective_message.reply_text(f"Esans başlatıldı. ID {item_id}", reply_markup=essence_menu())
        return
    if flow == "ess_close":
        for row in records("essences"):
            if row_id_text(row) == text.strip():
                set_cell_by_header("essences", int(row["_row"]), "Durum", "bitti")
                set_cell_by_header("essences", int(row["_row"]), "ClosedAt", now().isoformat(timespec="seconds"))
                await update.effective_message.reply_text("Esans bitirildi.", reply_markup=essence_menu())
                context.user_data.clear()
                return
        await update.effective_message.reply_text("Esans ID bulunamadı.", reply_markup=essence_menu())
        context.user_data.clear()
        return
    if flow == "ess_delete":
        await delete_by_id(update, "essences", text, "Esans silindi.", essence_menu())
        context.user_data.clear()
        return

    if flow == "report_month":
        parsed = parse_month(text)
        if not parsed:
            await update.effective_message.reply_text("Ay-yıl anlaşılamadı. Örn: 06-2026", reply_markup=back_cancel("m:report"))
            return
        month, year = parsed
        await show_month_report(update, month, year)
        return
    if flow == "report_stock":
        await show_stock_report(update, text)
        return

    if flow == "rem_custom_date":
        date = parse_date(text)
        if not date:
            await update.effective_message.reply_text("Tarih anlaşılamadı. Örn: 14-06-2026", reply_markup=back_cancel("rem:add"))
            return
        context.user_data["draft"]["date"] = date
        context.user_data["draft"]["repeat"] = "tek"
        await update.effective_message.reply_text("Saat seç:", reply_markup=time_choice_menu())
        return
    if flow == "rem_interval_days":
        try:
            interval_days = int(text.strip())
            if interval_days <= 0:
                raise ValueError
        except Exception:
            await update.effective_message.reply_text("Gün sayısı pozitif bir tam sayı olmalı. Örn: 3", reply_markup=back_cancel("rem:add"))
            return
        draft = context.user_data.setdefault("draft", {})
        draft["date"] = today_str()
        draft["repeat"] = "aralik"
        draft["interval_days"] = interval_days
        await update.effective_message.reply_text("Saat seç:", reply_markup=time_choice_menu())
        return
    if flow == "rem_yearly_date":
        cleaned = text.strip().replace(".", "-").replace("/", "-")
        parts = cleaned.split("-")
        if len(parts) != 2:
            await update.effective_message.reply_text("Format anlaşılamadı. Gün-Ay olarak yaz. Örn: 15-03", reply_markup=back_cancel("rem:add"))
            return
        try:
            day, month = int(parts[0]), int(parts[1])
            if not (1 <= month <= 12) or not (1 <= day <= calendar.monthrange(2024, month)[1]):
                raise ValueError
        except Exception:
            await update.effective_message.reply_text("Geçersiz gün/ay. Gün-Ay olarak yaz. Örn: 15-03", reply_markup=back_cancel("rem:add"))
            return
        draft = context.user_data.setdefault("draft", {})
        draft["date"] = next_yearly_date(day, month)
        draft["repeat"] = "yıllık"
        draft["yearly_day"] = day
        draft["yearly_month"] = month
        await update.effective_message.reply_text("Saat seç:", reply_markup=time_choice_menu())
        return
    if flow == "rem_custom_time":
        time = parse_time(text)
        if not time:
            await update.effective_message.reply_text("Saat anlaşılamadı. Örn: 17:30", reply_markup=back_cancel("rem:add"))
            return
        context.user_data["draft"]["time"] = time
        await prompt_reminder_next_step(update, context)
        return
    if flow == "rem_limit_enddate":
        date = parse_date(text)
        if not date:
            await update.effective_message.reply_text("Tarih anlaşılamadı. Örn: 30-09-2026", reply_markup=back_cancel("rem:add"))
            return
        context.user_data["draft"]["end_date"] = date
        context.user_data["flow"] = "rem_text"
        await update.effective_message.reply_text("Hatırlatma metnini yaz:", reply_markup=back_cancel("rem:add"))
        return
    if flow == "rem_limit_count":
        try:
            count = int(text.strip())
            if count <= 0:
                raise ValueError
        except Exception:
            await update.effective_message.reply_text("Tekrar sayısı pozitif bir tam sayı olmalı. Örn: 5", reply_markup=back_cancel("rem:add"))
            return
        context.user_data["draft"]["repeat_count"] = count
        context.user_data["flow"] = "rem_text"
        await update.effective_message.reply_text("Hatırlatma metnini yaz:", reply_markup=back_cancel("rem:add"))
        return
    if flow == "rem_text":
        d = context.user_data["draft"]
        item_id = next_id("reminders")
        payload = {
            "ID": item_id,
            "Tarih": d["date"],
            "Saat": d["time"],
            "Metin": text,
            "Durum": "bekliyor",
            "Chat_ID": update.effective_chat.id,
            "Tekrar": d.get("repeat", "tek"),
            "Hafta_Gunu": d.get("weekday", ""),
            "Ay_Gunu": d.get("monthday", "") or d.get("yearly_day", ""),
            "Gun_Araligi": d.get("interval_days", ""),
            "Bitis_Tarihi": d.get("end_date", ""),
            "Kalan_Tekrar": d.get("repeat_count", ""),
            "Yil_Ay": d.get("yearly_month", ""),
            "CreatedAt": now().isoformat(timespec="seconds"),
        }
        append_record("reminders", REMINDER_HEADERS, payload)
        context.user_data.clear()
        tekrar = repeat_label(payload)
        await update.effective_message.reply_text(f"Hatırlatma eklendi. ID {item_id} - {d['date']} {d['time']} ({tekrar})", reply_markup=reminder_menu())
        return
    if flow == "rem_delete":
        await delete_by_id(update, "reminders", text, "Hatırlatma silindi.", reminder_menu())
        context.user_data.clear()
        return

    if flow == "obs_note":
        context.user_data.setdefault("draft", {})["note"] = "" if text == "-" else text
        context.user_data["flow"] = "obs_photo"
        await update.effective_message.reply_text("Şimdi fotoğrafı gönder.", reply_markup=back_cancel("m:observation"))
        return
    if flow == "obs_date":
        date = parse_date(text)
        if not date:
            await update.effective_message.reply_text("Tarih anlaşılamadı. Örn: 14-06-2026", reply_markup=back_cancel("m:observation"))
            return
        rows = [r for r in records("observations") if parse_date(str(r.get("Tarih", ""))) == date]
        if not rows:
            await update.effective_message.reply_text(f"{date} tarihinde gözlem kaydı yok.", reply_markup=observation_menu())
            return
        out = f"{date} Gözlemleri\n\n"
        for row in rows[::-1]:
            out += observation_row_text(row) + "\n\n"
        await send_chunks(update, out, observation_menu())
        return
    if flow == "obs_delete":
        await delete_by_id(update, "observations", text, "Gözlem silindi.", observation_menu())
        context.user_data.clear()
        return

    if flow == "weather_now":
        context.user_data.clear()
        await show_weather(update, text, monthly=False)
        return
    if flow == "weather_month":
        context.user_data.clear()
        await show_weather(update, text, monthly=True)
        return


async def photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    flow = context.user_data.get("flow")
    message = update.effective_message
    if not message or not message.photo:
        return
    if flow == "plant_identify":
        await message.chat.send_action(ChatAction.TYPING)
        try:
            photo = message.photo[-1]
            tg_file = await context.bot.get_file(photo.file_id)
            image_bytes = bytes(await tg_file.download_as_bytearray())
            answer = await identify_plant(image_bytes, "", context)
            log_ai("ai_image_logs", update.effective_user.id if update.effective_user else "", "bitki_tani", "Bitki fotoğrafı", answer, photo.file_id)
            await send_chunks(update, answer, plant_ai_menu())
        except Exception as exc:
            await message.reply_text(f"Bitki tanıma hatası: {exc}", reply_markup=plant_ai_menu())
        return
    if flow != "obs_photo":
        await message.reply_text("Fotoğrafı kaydetmek veya yorumlatmak için önce Gözlem menüsünden bir seçenek seç.", reply_markup=observation_menu())
        return

    d = context.user_data.get("draft", {})
    photo = message.photo[-1]
    file_id = photo.file_id
    ai_comment = ""

    if d.get("ai"):
        await message.chat.send_action(ChatAction.TYPING)
        try:
            tg_file = await context.bot.get_file(file_id)
            image_bytes = bytes(await tg_file.download_as_bytearray())
            ai_comment = await analyze_image_with_gemini(image_bytes, d.get("note", ""))
            try:
                disease_note = await identify_plant_disease(image_bytes)
            except Exception:
                disease_note = ""
            if disease_note:
                ai_comment = f"{ai_comment}\n\n{disease_note}"
            log_ai("ai_image_logs", update.effective_user.id if update.effective_user else "", "görsel", d.get("note", ""), ai_comment, file_id)
        except Exception as exc:
            ai_comment = f"Fotoğraf indirilemedi veya yorumlanamadı: {exc}"

    item_id = next_id("observations")
    append_record("observations", OBSERVATION_HEADERS, {
        "ID": item_id,
        "Tarih": today_str(),
        "Kategori": d.get("category", "Gözlem"),
        "Not": d.get("note", ""),
        "Foto_File_ID": file_id,
        "AI_Yorum": ai_comment,
        "CreatedAt": now().isoformat(timespec="seconds"),
    })
    context.user_data.clear()

    text = f"Gözlem kaydedildi. ID {item_id}"
    if ai_comment:
        text += f"\n\nAI Yorumu:\n{ai_comment}"
    parts = chunks(text)
    for i, part in enumerate(parts):
        await message.reply_text(part, reply_markup=observation_menu() if i == len(parts) - 1 else None)


async def voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message or context.user_data.get("flow") != "ai_voice":
        return
    if not GROQ_CLIENT:
        await message.reply_text("Groq ayarı eksik. Render Variables içine GROQ_API_KEY eklenmeli.", reply_markup=ai_menu())
        return
    media = message.voice or message.audio
    if not media:
        return
    await message.chat.send_action(ChatAction.TYPING)
    try:
        tg_file = await media.get_file()
        buf = io.BytesIO()
        await tg_file.download_to_memory(buf)
        buf.seek(0)
        buf.name = "telegram_voice.ogg"
        transcript = await asyncio.to_thread(
            GROQ_CLIENT.audio.transcriptions.create,
            model=GROQ_WHISPER_MODEL,
            file=buf,
            language="tr",
        )
        text = getattr(transcript, "text", "").strip()
        if not text:
            await message.reply_text("Ses metne çevrilemedi.", reply_markup=back_cancel("m:ai"))
            return
        answer = await ask_gemini(text, context) if GEMINI_API_KEY else await ask_groq(text, context)
        log_ai("ai_voice_logs", update.effective_user.id if update.effective_user else "", "ses", text, answer)
        for part in chunks(f"Ses metni:\n{text}\n\nCevap:\n{answer}"):
            await message.reply_text(part)
        await message.reply_text("Başka ses gönderebilir veya geri dönebilirsin.", reply_markup=back_cancel("m:ai"))
    except Exception as exc:
        await message.reply_text(f"Ses işleme hatası: {exc}", reply_markup=back_cancel("m:ai"))


async def document_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message or context.user_data.get("flow") != "ai_file":
        return
    doc = message.document
    if not doc:
        return
    filename = doc.file_name or "dosya"
    await message.chat.send_action(ChatAction.TYPING)
    try:
        tg_file = await doc.get_file()
        buf = io.BytesIO()
        await tg_file.download_to_memory(buf)
        text = extract_document_text(filename, buf.getvalue())
        if not text or text.startswith(("PDF okunamadı", "Dosya okunamadı")):
            await message.reply_text(text or "Dosya boş görünüyor.", reply_markup=back_cancel("m:ai"))
            return
        summary_prompt = f"Bu dokümanı Türkçe, kısa ve kullanışlı şekilde özetle. Önemli maddeleri çıkar.\n\nDosya: {filename}\n\nMetin:\n{text[:12000]}"
        summary = await ask_gemini(summary_prompt, context) if GEMINI_API_KEY else await ask_groq(summary_prompt, context)
        log_ai("ai_file_logs", update.effective_user.id if update.effective_user else "", "dosya_ozet", filename, summary)
        item_id = next_id("ai_docs")
        pinecone_status = await pinecone_store_doc(item_id, filename, text)
        append_record("ai_docs", AI_DOC_HEADERS, {
            "ID": item_id,
            "Tarih": today_str(),
            "Dosya": filename,
            "Ozet": summary[:4000],
            "Metin": text[:45000],
            "Pinecone": pinecone_status,
            "CreatedAt": now().isoformat(timespec="seconds"),
        })
        for part in chunks(f"Dosya kaydedildi. ID {item_id}\nPinecone: {pinecone_status}\n\nÖzet:\n{summary}"):
            await message.reply_text(part)
        await message.reply_text("Bu dosyayla ilgili soru sormak için Dosyaya Sor'u kullan.", reply_markup=ai_menu())
    except Exception as exc:
        await message.reply_text(f"Dosya işleme hatası: {exc}", reply_markup=back_cancel("m:ai"))


async def delete_by_id(update: Update, sheet_name: str, id_text: str, success: str, menu: InlineKeyboardMarkup) -> None:
    wanted = id_text.strip()
    for row in records(sheet_name):
        if row_id_text(row) == wanted:
            SHEET[sheet_name].delete_rows(int(row["_row"]))
            RECORD_CACHE.pop(sheet_name, None)
            await update.effective_message.reply_text(success, reply_markup=menu)
            return
    await update.effective_message.reply_text("Bu ID bulunamadı.", reply_markup=menu)


async def show_month_report(update: Update, month: int, year: int) -> None:
    rows = []
    for row in operational_records():
        date = parse_date(str(row.get("Tarih", "")))
        if not date:
            continue
        dt = datetime.strptime(date, DATE_FMT)
        if dt.month == month and dt.year == year:
            rows.append(row)
    if not rows:
        await update.effective_message.reply_text(f"{month:02d}-{year} için işlem yok.", reply_markup=report_menu())
        return
    types = Counter(r.get("Islem", "Bilinmiyor") for r in rows)
    mats = Counter(history_material(r) for r in rows if history_material(r))
    text = f"Aylık Rapor - {month:02d}-{year}\n\nToplam işlem: {len(rows)}\n"
    if mats:
        top_mat, top_count = mats.most_common(1)[0]
        text += f"En çok kullanılan malzeme: {top_mat} ({top_count} işlem)\n"
    text += "\nİşlem türleri:\n"
    for name, count in types.most_common():
        text += f"- {name}: {count}\n"
    await update.effective_message.reply_text(text, reply_markup=report_menu())


async def show_stock_report(update: Update, name: str) -> None:
    item = find_inventory_by_name(name)
    material = item.get("Malzeme / Alet", name) if item else name
    rows = [r for r in operational_records() if normalize_name(material) in normalize_name(history_material(r))]
    if not rows:
        await update.effective_message.reply_text("Bu malzeme için kullanım geçmişi bulunamadı.", reply_markup=report_menu())
        return

    points: list[tuple[str, float]] = []
    for row in rows:
        date_str = parse_date(str(row.get("Tarih", "")))
        if not date_str:
            continue
        try:
            amount = parse_decimal(history_amount(row))
        except Exception:
            continue
        points.append((date_str, amount))

    if plt is not None and len(points) >= 2:
        try:
            buffer = render_line_chart(f"{material} Kullanım Grafiği", {material: points}, "Miktar")
            await update.effective_message.chat.send_action(ChatAction.UPLOAD_PHOTO)
            await update.effective_message.reply_photo(
                InputFile(buffer, filename="stok_grafik.png"),
                caption=f"{material} - {len(points)} kullanım kaydı",
                reply_markup=report_menu(),
            )
            return
        except Exception:
            log.exception("Stok grafiği oluşturulamadı, metne dönülüyor")

    text = f"{material} - Son 10 Kullanım\n\n"
    for row in rows[-10:][::-1]:
        source = row.get("_source", "Geçmiş")
        text += f"[{source}] ID {row_id_text(row)} - {row.get('Tarih', '-')}: {row.get('Islem', '-')} {history_material(row)}\n"
    await update.effective_message.reply_text(text, reply_markup=report_menu())


_LAST_ERROR_NOTIFY: dict[str, float] = {}


async def notify_admin_error(bot: Any, source: str, exc: BaseException) -> None:
    """Kritik bir hata olduğunda bot sahibine (stock_chat_id) kısa bir uyarı gönderir.
    Aynı kaynak+hata türü için 10 dakikada bir bildirim gönderir (spam olmasın diye)."""
    try:
        chat_id = alert_value("stock_chat_id")
        if not chat_id:
            return
        key = f"{source}:{type(exc).__name__}"
        last = _LAST_ERROR_NOTIFY.get(key, 0.0)
        if monotonic() - last < 600:
            return
        _LAST_ERROR_NOTIFY[key] = monotonic()
        await bot.send_message(
            chat_id=int(chat_id),
            text=f"⚠️ Bot hatası ({source})\n\n{type(exc).__name__}: {str(exc)[:300]}",
        )
    except Exception:
        log.exception("Admin hata bildirimi gönderilemedi")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Bot hatası", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("Bir hata oldu ama bot kapanmadı. Ana menüye dönebilirsin.", reply_markup=main_menu())
    if isinstance(context.error, Exception):
        await notify_admin_error(context.bot, "handler", context.error)


async def histadd_inventory_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, item: dict[str, Any]) -> None:
    draft = context.user_data.setdefault("draft", {"items": []})
    draft.setdefault("items", [])
    draft["current_material"] = item.get("Malzeme / Alet")
    draft["current_unit"] = item.get("Birim", "")
    context.user_data["flow"] = "histadd_amount"
    await edit_or_send(update, f"Malzeme: {item.get('Malzeme / Alet')}\nMiktar yaz:", back_cancel("m:history"))


async def compadd_inventory_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, item: dict[str, Any]) -> None:
    draft = context.user_data.setdefault("draft", {"items": [], "containers": []})
    draft.setdefault("items", [])
    draft.setdefault("containers", [])
    draft["current_material"] = item.get("Malzeme / Alet")
    draft["current_unit"] = item.get("Birim", "")
    context.user_data["flow"] = "compadd_amount"
    await edit_or_send(update, f"Malzeme: {item.get('Malzeme / Alet')}\nMiktar yaz:", back_cancel("m:compost"))


async def planadd_inventory_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, item: dict[str, Any]) -> None:
    draft = context.user_data.setdefault("draft", {"items": []})
    draft.setdefault("items", [])
    draft["current_material"] = item.get("Malzeme / Alet")
    draft["current_unit"] = item.get("Birim", "")
    context.user_data["flow"] = "planadd_amount"
    await edit_or_send(update, f"Malzeme: {item.get('Malzeme / Alet')}\nPlanlanan miktarı yaz:", back_cancel("m:plan"))


async def recipeadd_inventory_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, item: dict[str, Any]) -> None:
    draft = context.user_data.setdefault("draft", {"items": []})
    draft.setdefault("items", [])
    draft["current_material"] = item.get("Malzeme / Alet")
    draft["current_unit"] = item.get("Birim", "")
    context.user_data["flow"] = "recipeadd_amount"
    await edit_or_send(update, f"Malzeme: {item.get('Malzeme / Alet')}\nReçetedeki miktarı yaz:", back_cancel("m:recipes"))


async def essoil_inventory_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, item: dict[str, Any]) -> None:
    draft = context.user_data.setdefault("draft", {})
    draft["oil_material"] = item.get("Malzeme / Alet")
    draft["oil_unit"] = item.get("Birim", "")
    context.user_data["flow"] = "ess_oil_amount"
    await edit_or_send(update, f"Yağ: {item.get('Malzeme / Alet')}\nKullanılacak miktarı yaz:", back_cancel("m:essence"))


async def reportstock_inventory_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, item: dict[str, Any]) -> None:
    await show_stock_report(update, str(item.get("Malzeme / Alet", "")))


old_handle_inventory_callback = handle_inventory_callback


async def handle_inventory_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    if data.startswith("invpage:"):
        _, action, page = data.split(":")
        await edit_or_send(update, "Malzeme seç:", inventory_buttons(action, int(page)))
        return
    _, action, row_s = data.split(":")
    item = find_inventory_by_row(int(row_s))
    if not item:
        await edit_or_send(update, "Malzeme bulunamadı.", stock_menu())
        return
    if action == "histadd":
        await histadd_inventory_callback(update, context, item)
        return
    if action == "compadd":
        await compadd_inventory_callback(update, context, item)
        return
    if action == "planadd":
        await planadd_inventory_callback(update, context, item)
        return
    if action == "recipeadd":
        await recipeadd_inventory_callback(update, context, item)
        return
    if action == "essoil":
        await essoil_inventory_callback(update, context, item)
        return
    if action == "reportstock":
        await reportstock_inventory_callback(update, context, item)
        return
    await old_handle_inventory_callback(update, context, data)


def build_search_results(query: str) -> str:
    """AI kullanmadan, tüm sayfalarda anahtar kelime araması yapar. Hızlı ve kota harcamaz."""
    q = query.strip().casefold()
    results: list[str] = []

    def check(label: str, row: dict[str, Any], fields: list[str]) -> None:
        for field in fields:
            value = str(row.get(field, ""))
            if q in value.casefold():
                results.append(f"[{label}] ID {row_id_text(row)}: {value[:150]}")
                return

    sources: list[tuple[str, str, list[str]]] = [
        ("Stok", "inventory", ["Malzeme / Alet", "Görevi / Not"]),
        ("Geçmiş", "history", ["Malzeme", "Not", "Islem"]),
        ("Kompost", "Kompost", ["Kullanilan_Malzeme_Miktar", "Not", "Islem"]),
        ("Plan", "plans", ["Hedef", "Not", "Islem"]),
        ("Alan", "areas", ["Alan", "Not"]),
        ("Sorun", "issues", ["Baslik", "Not", "Alan"]),
        ("Günlük", "diary", ["Not"]),
        ("Reçete", "recipes", ["Ad", "Not", "Malzeme_Miktar"]),
        ("Esans", "essences", ["Cicek", "Yag", "Not"]),
        ("Gözlem", "observations", ["Not", "AI_Yorum"]),
        ("Hatırlatma", "reminders", ["Metin"]),
    ]
    for label, sheet_name, fields in sources:
        try:
            for row in records(sheet_name):
                check(label, row, fields)
        except Exception:
            log.exception("Arama sırasında %s sayfası okunamadı", sheet_name)

    if not results:
        return f"'{query}' için sonuç bulunamadı."
    text = f"'{query}' için {len(results)} sonuç:\n\n" + "\n".join(results[:40])
    if len(results) > 40:
        text += f"\n... ve {len(results) - 40} sonuç daha (aramayı daraltmayı dene)"
    return text


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/ara <kelime> - artık zorunlu değil, Sistem menüsündeki 🔍 Hızlı Arama butonu ile de aynı şey yapılabilir."""
    message = update.effective_message
    if not message:
        return
    query = " ".join(context.args) if context.args else ""
    if not query.strip():
        await message.reply_text("Kullanım: /ara aranacak kelime\n\nÖrn: /ara lavanta\n\nİstersen Sistem menüsündeki 🔍 Hızlı Arama butonunu da kullanabilirsin.")
        return
    await send_chunks(update, build_search_results(query))


def build_app() -> Application:
    init_sheets()
    init_ai()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler(["start", "menu"], start))
    app.add_handler(CommandHandler("iptal", cancel))
    app.add_handler(CommandHandler("ara", search_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.PHOTO, photo_message))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, voice_message))
    app.add_handler(MessageHandler(filters.Document.ALL, document_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    app.add_error_handler(error_handler)
    return app


if __name__ == "__main__":
    start_health_server()
    build_app().run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

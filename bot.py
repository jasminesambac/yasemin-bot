import asyncio
import csv
import io
import json
import logging
import os
import re
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

import gspread
import requests
from oauth2client.service_account import ServiceAccountCredentials
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("yasemin-bot")

TR_TZ_OFFSET = timedelta(hours=3)
DATE_FMT = "%d-%m-%Y"
MSG_LIMIT = 3900

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
SHEET_ID = os.getenv("SHEET_ID", "").strip()
CREDENTIALS_JSON = os.getenv("GOOGLE_SHEETS_CREDENTIALS", "").strip()
AGNES_API_KEY = os.getenv("AGNES_API_KEY", "").strip()
AGNES_BASE_URL = os.getenv("AGNES_BASE_URL", "https://apihub.agnes-ai.com/v1").strip()
AGNES_MODEL = os.getenv("AGNES_MODEL", "agnes-2.0-flash").strip()

INVENTORY_HEADERS = ["ID", "Kategori", "Malzeme / Alet", "Başlangıç Miktarı", "Kullanılan", "Kalan Miktar", "Birim", "Görevi / Not", "CreatedAt"]
HISTORY_HEADERS = ["ID", "Tarih", "Islem", "Malzeme", "Miktar", "Birim", "pH", "Not", "CreatedAt"]
PH_HEADERS = ["ID", "Tarih", "Teneke_No", "pH", "Not", "CreatedAt"]
REMINDER_HEADERS = ["ID", "Tarih", "Saat", "Metin", "Durum", "CreatedAt"]

SHEET: dict[str, gspread.Worksheet] = {}
AI_CLIENT = None


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
            if "message to edit not found" not in str(exc).lower():
                log.warning("edit failed: %s", exc)
        await query.message.reply_text(text, reply_markup=reply_markup)
        return
    await send_chunks(update, text, reply_markup)


def kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=data) for label, data in row] for row in rows])


def back_cancel(back_to: str) -> InlineKeyboardMarkup:
    return kb([[("Geri", back_to), ("İptal", "cancel")]])


def main_menu() -> InlineKeyboardMarkup:
    return kb([
        [("📦 Stok", "m:stock"), ("🔬 pH", "m:ph")],
        [("📜 Geçmiş", "m:history"), ("📊 Rapor", "m:report")],
        [("⏰ Hatırlatma", "m:reminder"), ("🌤️ Hava", "m:weather")],
        [("🤖 AI Sor", "m:ai"), ("💾 Yedekle", "backup")],
    ])


def stock_menu() -> InlineKeyboardMarkup:
    return kb([
        [("📋 Stok Listesi", "stock:list"), ("🔍 Stok Sorgula", "stock:search")],
        [("⬇️ Stoktan Düş", "stock:use"), ("➕ Yeni Malzeme Ekle", "stock:add")],
        [("❌ Malzeme Sil", "stock:delete"), ("↩️ Geri Al", "stock:undo")],
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
        [("📜 Son 10 İşlem", "hist:last10"), ("📋 Tüm Geçmiş", "hist:last30")],
        [("📅 Tarihli İşlemler", "hist:date"), ("❌ İşlem Sil", "hist:delete")],
        [("📝 İşlem Ekle", "hist:add")],
        [("🔙 Geri", "m:main")],
    ])


def report_menu() -> InlineKeyboardMarkup:
    return kb([
        [("📊 Aylık Rapor", "report:month"), ("📅 Günlük Rapor", "report:daily")],
        [("📈 İstatistik", "report:stats"), ("📉 Stok Grafiği", "report:stock")],
        [("🔙 Geri", "m:main")],
    ])


def reminder_menu() -> InlineKeyboardMarkup:
    return kb([
        [("➕ Hatırlatma Ekle", "rem:add"), ("📋 Bekleyen Hatırlatmalar", "rem:list")],
        [("❌ Hatırlatma Sil", "rem:delete")],
        [("🔙 Geri", "m:main")],
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
        [("Geri", "m:stock"), ("İptal", "cancel")],
    ])


def unit_menu(back_to: str = "stock:add") -> InlineKeyboardMarkup:
    return kb([
        [("gr", "unit:gr"), ("ml", "unit:ml"), ("L", "unit:L"), ("adet", "unit:adet")],
        [("Geri", back_to), ("İptal", "cancel")],
    ])


def operation_type_menu(prefix: str) -> InlineKeyboardMarkup:
    return kb([
        [("Sulama", f"{prefix}:tur:Sulama"), ("Gübreleme", f"{prefix}:tur:Gübreleme")],
        [("İlaçlama", f"{prefix}:tur:İlaçlama"), ("Hasat", f"{prefix}:tur:Hasat")],
        [("Toprak İşlemi", f"{prefix}:tur:Toprak İşlemi"), ("Diğer", f"{prefix}:tur:Diğer")],
        [("Geri", "m:stock" if prefix == "use" else "m:history"), ("İptal", "cancel")],
    ])


def date_choice_menu(prefix: str) -> InlineKeyboardMarkup:
    return kb([
        [("Bugün", f"{prefix}:date:today"), ("Dün", f"{prefix}:date:yesterday")],
        [("Özel Tarih", f"{prefix}:date:custom")],
        [("Geri", "m:history" if prefix == "histadd" else "m:reminder"), ("İptal", "cancel")],
    ])


def time_choice_menu() -> InlineKeyboardMarkup:
    return kb([
        [("09:00", "rem:time:09:00"), ("12:00", "rem:time:12:00"), ("15:00", "rem:time:15:00")],
        [("17:00", "rem:time:17:00"), ("20:00", "rem:time:20:00"), ("Özel", "rem:time:custom")],
        [("Geri", "rem:add"), ("İptal", "cancel")],
    ])


def ph_choice_menu() -> InlineKeyboardMarkup:
    return kb([
        [("5.0", "histadd:ph:5.0"), ("5.5", "histadd:ph:5.5"), ("6.0", "histadd:ph:6.0")],
        [("6.5", "histadd:ph:6.5"), ("7.0", "histadd:ph:7.0"), ("Ölçmedim", "histadd:ph:")],
        [("Geri", "m:history"), ("İptal", "cancel")],
    ])


def city_menu(prefix: str) -> InlineKeyboardMarkup:
    cities = ["İstanbul", "Ankara", "İzmir", "Bursa", "Antalya", "Adana", "Konya", "Trabzon"]
    rows = []
    for i in range(0, len(cities), 2):
        rows.append([(cities[i], f"{prefix}:city:{cities[i]}"), (cities[i + 1], f"{prefix}:city:{cities[i + 1]}")])
    rows.append([("Şehir Yaz", f"{prefix}:city:custom")])
    rows.append([("Geri", "m:weather"), ("İptal", "cancel")])
    return kb(rows)


def init_sheets() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN eksik.")
    if not SHEET_ID:
        raise RuntimeError("SHEET_ID eksik.")
    if not CREDENTIALS_JSON:
        raise RuntimeError("GOOGLE_SHEETS_CREDENTIALS eksik.")

    creds_dict = json.loads(CREDENTIALS_JSON)
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SHEET_ID)
    wanted = {
        "inventory": INVENTORY_HEADERS,
        "history": HISTORY_HEADERS,
        "ph_records": PH_HEADERS,
        "reminders": REMINDER_HEADERS,
    }
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
    global AI_CLIENT
    if AGNES_API_KEY and OpenAI:
        AI_CLIENT = OpenAI(base_url=AGNES_BASE_URL, api_key=AGNES_API_KEY)


def records(sheet_name: str) -> list[dict[str, Any]]:
    data = SHEET[sheet_name].get_all_records()
    for i, row in enumerate(data, start=2):
        row["_row"] = i
        if not row.get("ID"):
            row["_id"] = str(i - 1)
        else:
            row["_id"] = str(row.get("ID"))
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


def find_inventory_by_row(row_number: int) -> dict[str, Any] | None:
    for row in records("inventory"):
        if int(row["_row"]) == row_number:
            return row
    return None


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


def use_stock(name: str, amount: float, unit: str, op_type: str, note: str = "", date: str | None = None, ph: str = "") -> tuple[bool, str, dict[str, Any] | None]:
    item = find_inventory_by_name(name)
    if not item:
        return False, "Malzeme bulunamadı.", None
    row_number = int(item["_row"])
    remaining_raw = str(item.get("Kalan Miktar", "")).strip()
    used_raw = str(item.get("Kullanılan", "0")).strip() or "0"
    material = str(item.get("Malzeme / Alet", name))
    old_remaining = remaining_raw

    if remaining_raw.casefold() == "stok bol":
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
    set_cell_by_header("inventory", row_number, "Kalan Miktar", format_decimal(new_remaining))
    set_cell_by_header("inventory", row_number, "Kullanılan", format_decimal(new_used))
    add_history(op_type, material, format_decimal(amount), unit, ph, note, date)
    return True, f"{format_decimal(new_remaining)} {item.get('Birim', unit)}", {"material": material, "row": row_number, "old_remaining": old_remaining, "amount": amount, "unit": unit}


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
    rows.append([("Geri", "m:stock"), ("İptal", "cancel")])
    return kb(rows)


def teneke_buttons(action: str) -> InlineKeyboardMarkup:
    tenekeler = sorted({str(r.get("Teneke_No", "")).strip() for r in records("ph_records") if str(r.get("Teneke_No", "")).strip()}, key=lambda x: int(x) if x.isdigit() else 999999)
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
    rows.append([("Geri", "m:ph"), ("İptal", "cancel")])
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


async def show_home(update: Update) -> None:
    await edit_or_send(update, "Yasemin Asistan\n\nBir işlem seç:", main_menu())


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await show_home(update)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await edit_or_send(update, "İşlem iptal edildi.\n\nAna menü:", main_menu())


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data or ""

    if data == "cancel":
        await cancel(update, context)
        return
    if data == "m:main":
        context.user_data.clear()
        await show_home(update)
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
    if data == "m:report":
        context.user_data.clear()
        await edit_or_send(update, "Raporlar", report_menu())
        return
    if data == "m:reminder":
        context.user_data.clear()
        await edit_or_send(update, "Hatırlatmalar", reminder_menu())
        return
    if data == "m:weather":
        context.user_data.clear()
        await edit_or_send(update, "Hava Durumu", weather_menu())
        return
    if data == "m:ai":
        context.user_data["flow"] = "ai"
        await edit_or_send(update, "Agnes AI'ya sormak istediğin şeyi yaz.", back_cancel("m:main"))
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
    if data.startswith("report:"):
        await handle_report_callback(update, context, data)
        return
    if data.startswith("rem:"):
        await handle_reminder_callback(update, context, data)
        return
    if data.startswith("weather:") or data.startswith("weathernow:") or data.startswith("weathermonth:"):
        await handle_weather_callback(update, context, data)
        return
    if data == "backup":
        await send_backup(update, context)
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
        context.user_data["flow"] = "ph_add_teneke"
        context.user_data["draft"] = {}
        await edit_or_send(update, "Teneke numarasını yaz:", back_cancel("m:ph"))
        return
    if data == "ph:delete":
        await edit_or_send(update, "pH kaydı nasıl silinsin?", kb([
            [("ID ile sil", "ph:delete_id")],
            [("Teneke seçip son kaydı sil", "ph:delete_last")],
            [("Geri", "m:ph"), ("İptal", "cancel")],
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
    await edit_or_send(update, f"Silindi: Teneke {teneke}, ID {row_id_text(row)}, pH {row.get('pH', '-')}", ph_menu())


async def handle_history_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    if data == "hist:last10":
        await show_history(update, 10)
        return
    if data == "hist:last30":
        await show_history(update, 30)
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
        context.user_data["draft"] = {}
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
    if data.startswith("histadd:ph:"):
        context.user_data.setdefault("draft", {})["ph"] = data.split(":", 2)[2]
        context.user_data["flow"] = "histadd_note"
        await edit_or_send(update, "Not yaz. Ne için yaptığını buraya yazabilirsin. Not yoksa '-' yaz.", back_cancel("m:history"))
        return


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


async def handle_report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    if data == "report:daily":
        rows = [r for r in records("history") if r.get("Tarih") == today_str()]
        if not rows:
            await edit_or_send(update, f"{today_str()} için işlem yok.", report_menu())
            return
        text = f"Günlük Rapor - {today_str()}\n\nToplam işlem: {len(rows)}\n\n"
        for row in rows:
            text += f"ID {row_id_text(row)} - {row.get('Islem', '-')}: {history_material(row) or '-'} {history_amount(row)} {history_unit(row)}\n"
        await edit_or_send(update, text, report_menu())
        return
    if data == "report:stats":
        rows = records("history")
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
    if data == "report:month":
        context.user_data["flow"] = "report_month"
        await edit_or_send(update, "Ay ve yıl yaz. Örn: 06-2026", back_cancel("m:report"))
        return
    if data == "report:stock":
        context.user_data["flow"] = "report_stock"
        await edit_or_send(update, "Malzeme adını yaz veya seç:", inventory_buttons("reportstock"))


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
            text += f"ID {row_id_text(row)} - {row.get('Tarih', '-')} {row.get('Saat', '-')}: {row.get('Metin', '-')}\n"
        await edit_or_send(update, text, reminder_menu())
        return
    if data == "rem:delete":
        context.user_data["flow"] = "rem_delete"
        await edit_or_send(update, "Silmek istediğin hatırlatma ID numarasını yaz.", back_cancel("m:reminder"))
        return
    if data.startswith("rem:date:"):
        choice = data.rsplit(":", 1)[1]
        if choice == "custom":
            context.user_data["flow"] = "rem_custom_date"
            await edit_or_send(update, "Özel tarihi yaz. Örn: 14-06-2026", back_cancel("rem:add"))
            return
        context.user_data.setdefault("draft", {})["date"] = today_str() if choice == "today" else (now() - timedelta(days=1)).strftime(DATE_FMT)
        await edit_or_send(update, "Saat seç:", time_choice_menu())
        return
    if data.startswith("rem:time:"):
        choice = data.rsplit(":", 1)[1]
        if choice == "custom":
            context.user_data["flow"] = "rem_custom_time"
            await edit_or_send(update, "Saati yaz. Örn: 17:30", back_cancel("rem:add"))
            return
        context.user_data.setdefault("draft", {})["time"] = choice
        context.user_data["flow"] = "rem_text"
        await edit_or_send(update, "Hatırlatma metnini yaz:", back_cancel("rem:add"))


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


async def send_backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return
    await message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, sheet_name in [
            ("inventory.csv", "inventory"),
            ("history.csv", "history"),
            ("ph_records.csv", "ph_records"),
            ("reminders.csv", "reminders"),
        ]:
            out = io.StringIO()
            writer = csv.writer(out)
            writer.writerows(SHEET[sheet_name].get_all_values())
            zf.writestr(filename, out.getvalue().encode("utf-8-sig"))
    buffer.seek(0)
    await message.reply_document(InputFile(buffer, filename=f"yasemin_yedek_{today_str()}.zip"), caption="Yedek hazır.")


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


async def show_weather(update: Update, city: str, *, monthly: bool = False) -> None:
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
    flow = context.user_data.get("flow")
    if not flow:
        await update.effective_message.reply_text("Lütfen menüden bir buton seç.", reply_markup=main_menu())
        return

    if text.casefold() in {"iptal", "/iptal"}:
        await cancel(update, context)
        return

    if flow == "ai":
        await update.effective_message.chat.send_action(ChatAction.TYPING)
        answer = await ask_ai(text, update.effective_user.id, context)
        for part in chunks(f"Agnes AI:\n\n{answer}"):
            await update.effective_message.reply_text(part)
        await update.effective_message.reply_text("Başka bir soru yazabilir veya iptal edebilirsin.", reply_markup=back_cancel("m:main"))
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
        d = context.user_data["draft"]
        item_id = next_id("inventory")
        append_record("inventory", INVENTORY_HEADERS, {
            "ID": item_id,
            "Kategori": d["category"],
            "Malzeme / Alet": d["name"],
            "Başlangıç Miktarı": d["amount"],
            "Kullanılan": "0",
            "Kalan Miktar": d["amount"],
            "Birim": d["unit"],
            "Görevi / Not": "" if text == "-" else text,
            "CreatedAt": now().isoformat(timespec="seconds"),
        })
        add_history("ENVANTERE EKLENDİ", d["name"], d["amount"], d["unit"], "", text)
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
        context.user_data["draft"]["amount"] = amount
        await update.effective_message.reply_text("pH seç:", reply_markup=ph_choice_menu())
        return
    if flow == "histadd_note":
        d = context.user_data["draft"]
        ok, result, undo = use_stock(d["material"], d["amount"], d["unit"], d["type"], "" if text == "-" else text, d["date"], d.get("ph", ""))
        if ok and undo:
            context.user_data["last_stock_use"] = undo
        context.user_data.pop("flow", None)
        context.user_data.pop("draft", None)
        await update.effective_message.reply_text(("İşlem kaydedildi ve stoktan düşüldü. Kalan: " + result) if ok else result, reply_markup=history_menu())
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
        await update.effective_message.reply_text("Saat seç:", reply_markup=time_choice_menu())
        return
    if flow == "rem_custom_time":
        time = parse_time(text)
        if not time:
            await update.effective_message.reply_text("Saat anlaşılamadı. Örn: 17:30", reply_markup=back_cancel("rem:add"))
            return
        context.user_data["draft"]["time"] = time
        context.user_data["flow"] = "rem_text"
        await update.effective_message.reply_text("Hatırlatma metnini yaz:", reply_markup=back_cancel("rem:add"))
        return
    if flow == "rem_text":
        d = context.user_data["draft"]
        item_id = next_id("reminders")
        append_record("reminders", REMINDER_HEADERS, {
            "ID": item_id,
            "Tarih": d["date"],
            "Saat": d["time"],
            "Metin": text,
            "Durum": "bekliyor",
            "CreatedAt": now().isoformat(timespec="seconds"),
        })
        context.user_data.clear()
        await update.effective_message.reply_text(f"Hatırlatma eklendi. ID {item_id} - {d['date']} {d['time']}", reply_markup=reminder_menu())
        return
    if flow == "rem_delete":
        await delete_by_id(update, "reminders", text, "Hatırlatma silindi.", reminder_menu())
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


async def delete_by_id(update: Update, sheet_name: str, id_text: str, success: str, menu: InlineKeyboardMarkup) -> None:
    wanted = id_text.strip()
    for row in records(sheet_name):
        if row_id_text(row) == wanted:
            SHEET[sheet_name].delete_rows(int(row["_row"]))
            await update.effective_message.reply_text(success, reply_markup=menu)
            return
    await update.effective_message.reply_text("Bu ID bulunamadı.", reply_markup=menu)


async def show_month_report(update: Update, month: int, year: int) -> None:
    rows = []
    for row in records("history"):
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
    rows = [r for r in records("history") if normalize_name(history_material(r)) == normalize_name(material)]
    if not rows:
        await update.effective_message.reply_text("Bu malzeme için kullanım geçmişi bulunamadı.", reply_markup=report_menu())
        return
    text = f"{material} - Son 10 Kullanım\n\n"
    for row in rows[-10:][::-1]:
        text += f"ID {row_id_text(row)} - {row.get('Tarih', '-')}: {row.get('Islem', '-')} {history_amount(row)} {history_unit(row)}\n"
    await update.effective_message.reply_text(text, reply_markup=report_menu())


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Bot hatası", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("Bir hata oldu ama bot kapanmadı. Ana menüye dönebilirsin.", reply_markup=main_menu())


async def histadd_inventory_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, item: dict[str, Any]) -> None:
    context.user_data.setdefault("draft", {})["material"] = item.get("Malzeme / Alet")
    context.user_data["draft"]["unit"] = item.get("Birim", "")
    context.user_data["flow"] = "histadd_amount"
    await edit_or_send(update, f"Malzeme: {item.get('Malzeme / Alet')}\nMiktar yaz:", back_cancel("m:history"))


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
    if action == "reportstock":
        await reportstock_inventory_callback(update, context, item)
        return
    await old_handle_inventory_callback(update, context, data)


def build_app() -> Application:
    init_sheets()
    init_ai()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler(["start", "menu"], start))
    app.add_handler(CommandHandler("iptal", cancel))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    app.add_error_handler(error_handler)
    return app


if __name__ == "__main__":
    build_app().run_polling(allowed_updates=Update.ALL_TYPES)

        "reminders": REMINDER_HEADERS,
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

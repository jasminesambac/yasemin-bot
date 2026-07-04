        try:
            tg_file = await context.bot.get_file(file_id)
            image_bytes = bytes(await tg_file.download_as_bytearray())
            ai_comment = await analyze_image_with_gemini(image_bytes, d.get("note", ""))
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
    text = f"{material} - Son 10 Kullanım\n\n"
    for row in rows[-10:][::-1]:
        source = row.get("_source", "Geçmiş")
        text += f"[{source}] ID {row_id_text(row)} - {row.get('Tarih', '-')}: {row.get('Islem', '-')} {history_material(row)}\n"
    await update.effective_message.reply_text(text, reply_markup=report_menu())


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Bot hatası", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("Bir hata oldu ama bot kapanmadı. Ana menüye dönebilirsin.", reply_markup=main_menu())


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


def build_app() -> Application:
    init_sheets()
    init_ai()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler(["start", "menu"], start))
    app.add_handler(CommandHandler("iptal", cancel))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.PHOTO, photo_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    app.add_error_handler(error_handler)
    return app


if __name__ == "__main__":
    start_health_server()
    build_app().run_polling(allowed_updates=Update.ALL_TYPES)

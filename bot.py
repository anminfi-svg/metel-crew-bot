import os
import warnings
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# In-memory storage
published_crews: list[dict] = []
profiles: dict[int, dict] = {}   # keyed by Telegram user ID
join_requests: list[dict] = []
_crew_counter = 0
_req_counter = 0

# Conversation states
CREW_SIZE, LOOKING_FOR, VIBE, AREA, MESSAGE, CONFIRM = range(6)

MAIN_MENU_TEXT = (
    "🎒 *METEL Crew Finder*\n\n"
    "Going to METEL but need people to go with?\n"
    "Find a crew, join a pregame, or create your own."
)

MAIN_MENU_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("👯 Find a crew", callback_data="find_crew")],
    [InlineKeyboardButton("➕ Create a crew", callback_data="create_crew")],
    [InlineKeyboardButton("🔥 My crew", callback_data="my_crew")],
])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        MAIN_MENU_TEXT,
        parse_mode="Markdown",
        reply_markup=MAIN_MENU_KEYBOARD,
    )


# ── Create a crew flow ──────────────────────────────────────────────────────

async def create_crew_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("1", callback_data="size_1"),
        InlineKeyboardButton("2", callback_data="size_2"),
        InlineKeyboardButton("3", callback_data="size_3"),
        InlineKeyboardButton("4+", callback_data="size_4+"),
    ]])
    await query.edit_message_text(
        "➕ *Create a crew*\n\nHow many people are already in your crew?",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    return CREW_SIZE


async def crew_size(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["crew_size"] = query.data.removeprefix("size_")

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("1", callback_data="looking_1"),
        InlineKeyboardButton("2", callback_data="looking_2"),
        InlineKeyboardButton("3", callback_data="looking_3"),
        InlineKeyboardButton("4+", callback_data="looking_4+"),
    ]])
    await query.edit_message_text(
        "How many more people are you looking for?",
        reply_markup=keyboard,
    )
    return LOOKING_FOR


async def looking_for(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["looking_for"] = query.data.removeprefix("looking_")

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🍸 Chill / drinks",      callback_data="vibe_chill")],
        [InlineKeyboardButton("💃 Dance all night",     callback_data="vibe_dance")],
        [InlineKeyboardButton("🔥 Full send",           callback_data="vibe_fullsend")],
        [InlineKeyboardButton("🫂 Social / meet people", callback_data="vibe_social")],
    ])
    await query.edit_message_text("What's the vibe?", reply_markup=keyboard)
    return VIBE


VIBE_LABELS = {
    "vibe_chill":    "🍸 Chill / drinks",
    "vibe_dance":    "💃 Dance all night",
    "vibe_fullsend": "🔥 Full send",
    "vibe_social":   "🫂 Social / meet people",
}


async def vibe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["vibe"] = VIBE_LABELS[query.data]

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Downtown", callback_data="area_Downtown")],
        [InlineKeyboardButton("Burnaby",  callback_data="area_Burnaby")],
        [InlineKeyboardButton("Richmond", callback_data="area_Richmond")],
        [InlineKeyboardButton("Surrey",   callback_data="area_Surrey")],
        [InlineKeyboardButton("Other",    callback_data="area_Other")],
    ])
    await query.edit_message_text("📍 Where are you meeting?", reply_markup=keyboard)
    return AREA


async def area(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["area"] = query.data.removeprefix("area_")

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Skip", callback_data="msg_skip"),
    ]])
    await query.edit_message_text(
        "💬 Got a one-line message for your crew? _(optional)_\n\n"
        "e.g. _Pregaming around 9 before METEL_\n\n"
        "Type it below or tap Skip.",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    return MESSAGE


def _build_preview(context: ContextTypes.DEFAULT_TYPE) -> tuple[str, InlineKeyboardMarkup]:
    d = context.user_data
    text = (
        "👯 *CREW*\n\n"
        f"👥 {d['crew_size']} people already\n"
        f"➕ Looking for {d['looking_for']} more\n"
        f"{d['vibe']}\n"
        f"📍 {d['area']}\n"
    )
    if d.get("message"):
        text += f'"{d["message"]}"'

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Publish", callback_data="confirm_publish"),
        InlineKeyboardButton("❌ Cancel",  callback_data="confirm_cancel"),
    ]])
    return text, keyboard


async def message_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["message"] = update.message.text.strip()
    text, keyboard = _build_preview(context)
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
    return CONFIRM


async def message_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["message"] = None
    text, keyboard = _build_preview(context)
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
    return CONFIRM


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_publish":
        global _crew_counter
        _crew_counter += 1
        d = context.user_data
        uid = update.effective_user.id
        profiles[uid] = {
            "first_name": update.effective_user.first_name,
            "username":   update.effective_user.username,
        }
        published_crews.append({
            "id":         _crew_counter,
            "creator_id": uid,
            "members":    [uid],
            "user_id":    uid,
            "username":   update.effective_user.username,
            "crew_size":  d["crew_size"],
            "looking_for": d["looking_for"],
            "vibe":       d["vibe"],
            "area":       d["area"],
            "message":    d.get("message"),
        })
        await query.edit_message_text(
            "✅ *Crew published!*\n\nYour crew is now live. Good luck finding your people! 🎉\n\n"
            "Use /start to return to the menu.",
            parse_mode="Markdown",
        )
    else:
        await query.edit_message_text(
            "❌ Cancelled.\n\nUse /start to return to the menu."
        )

    context.user_data.clear()
    return ConversationHandler.END


# ── Crew detail & member profile ────────────────────────────────────────────

async def view_crew(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    crew_id = int(query.data.removeprefix("view_crew_"))
    crew = next((c for c in published_crews if c["id"] == crew_id), None)
    if not crew:
        await query.edit_message_text("Crew not found. Use /start to go back.")
        return

    p = profiles.get(crew["creator_id"], {})
    creator_line = f"👑 {p.get('first_name', 'Unknown')}"
    if p.get("username"):
        creator_line += f" — @{p['username']}"

    text = (
        f"👯 *CREW #{crew['id']}*\n\n"
        f"📍 {crew['area']}\n"
        f"{crew['vibe']}\n"
        f"👥 {crew['crew_size']} already · looking for {crew['looking_for']} more\n"
    )
    if crew.get("message"):
        text += f'\n_"{crew["message"]}"_\n'
    text += f"\n{creator_line}\n"

    viewer_uid = update.effective_user.id
    buttons = []
    for uid in crew["members"]:
        name = profiles.get(uid, {}).get("first_name", str(uid))
        buttons.append([InlineKeyboardButton(f"👤 {name}", callback_data=f"member_{uid}_{crew_id}")])
    is_own    = crew["creator_id"] == viewer_uid
    is_member = viewer_uid in crew["members"]
    has_pending = any(
        r["crew_id"] == crew_id and r["requester_id"] == viewer_uid and r["status"] == "pending"
        for r in join_requests
    )
    if not is_own and not is_member and not has_pending:
        buttons.append([InlineKeyboardButton("🙋 Request to join", callback_data=f"join_{crew_id}")])
    buttons.append([
        InlineKeyboardButton("⬅️ Back to crews", callback_data="find_crew"),
        InlineKeyboardButton("🏠 Main menu",      callback_data="main_menu"),
    ])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))


async def member_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    # callback_data: "member_<uid>_<crew_id>"
    _, uid_str, crew_id_str = query.data.split("_", 2)
    uid = int(uid_str)
    crew_id = int(crew_id_str)

    p = profiles.get(uid, {})
    name = p.get("first_name", "Unknown")
    username = p.get("username")

    text = f"👤 *{name}*"
    if username:
        text += f"\n\nTelegram: @{username}"

    buttons = []
    if username:
        buttons.append([InlineKeyboardButton("💬 Open Telegram", url=f"https://t.me/{username}")])
    buttons.append([
        InlineKeyboardButton(f"⬅️ Back to crew", callback_data=f"view_crew_{crew_id}"),
        InlineKeyboardButton("🏠 Main menu",      callback_data="main_menu"),
    ])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))


# ── Join request flow ───────────────────────────────────────────────────────

async def request_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    crew_id = int(query.data.removeprefix("join_"))
    uid = update.effective_user.id

    crew = next((c for c in published_crews if c["id"] == crew_id), None)
    if not crew:
        await query.answer("Crew not found.", show_alert=True)
        return
    if crew["creator_id"] == uid:
        await query.answer("That's your own crew!", show_alert=True)
        return
    if any(r["crew_id"] == crew_id and r["requester_id"] == uid and r["status"] == "pending"
           for r in join_requests):
        await query.answer("You already sent a request to this crew.", show_alert=True)
        return

    await query.answer()
    global _req_counter
    _req_counter += 1
    req = {
        "id":           _req_counter,
        "crew_id":      crew_id,
        "requester_id": uid,
        "first_name":   update.effective_user.first_name,
        "username":     update.effective_user.username,
        "status":       "pending",
    }
    join_requests.append(req)

    await query.edit_message_text(
        "✅ *Join request sent to the crew creator.*\n\nYou'll be notified when they respond.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main menu", callback_data="main_menu")]]),
    )

    uname_line = f"\n@{req['username']}" if req["username"] else ""
    notif_text = f"🙋 *New join request for Crew #{crew_id}*\n\n{req['first_name']}{uname_line}"
    notif_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 View requester", callback_data=f"jview_{req['id']}")],
        [
            InlineKeyboardButton("✅ Accept",  callback_data=f"jaccept_{req['id']}"),
            InlineKeyboardButton("❌ Decline", callback_data=f"jdecline_{req['id']}"),
        ],
    ])
    try:
        await context.bot.send_message(
            chat_id=crew["creator_id"],
            text=notif_text,
            parse_mode="Markdown",
            reply_markup=notif_kb,
        )
    except Exception:
        pass


async def jview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    req_id = int(query.data.removeprefix("jview_"))
    req = next((r for r in join_requests if r["id"] == req_id), None)
    if not req:
        await query.edit_message_text("Request not found.")
        return

    text = f"👤 *{req['first_name']}*"
    if req["username"]:
        text += f"\n@{req['username']}"

    buttons = []
    if req["username"]:
        buttons.append([InlineKeyboardButton("💬 Open Telegram", url=f"https://t.me/{req['username']}")])
    buttons.append([
        InlineKeyboardButton("✅ Accept",  callback_data=f"jaccept_{req_id}"),
        InlineKeyboardButton("❌ Decline", callback_data=f"jdecline_{req_id}"),
    ])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))


async def jaccept(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    req_id = int(query.data.removeprefix("jaccept_"))
    req = next((r for r in join_requests if r["id"] == req_id), None)
    if not req or req["status"] != "pending":
        await query.edit_message_text("This request is no longer pending.")
        return

    req["status"] = "accepted"
    crew = next((c for c in published_crews if c["id"] == req["crew_id"]), None)
    if crew and req["requester_id"] not in crew["members"]:
        crew["members"].append(req["requester_id"])
        profiles.setdefault(req["requester_id"], {
            "first_name": req["first_name"],
            "username":   req["username"],
        })

    name = req["first_name"]
    r_uname = req["username"]
    host_uname = profiles.get(crew["creator_id"], {}).get("username") if crew else None

    # Confirm to creator
    creator_buttons = []
    if r_uname:
        creator_buttons.append([InlineKeyboardButton(f"💬 Message {name}", url=f"https://t.me/{r_uname}")])
    creator_buttons.append([InlineKeyboardButton("🏠 Main menu", callback_data="main_menu")])
    await query.edit_message_text(
        f"✅ *{name} joined your crew.*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(creator_buttons),
    )

    # Notify requester
    req_buttons = []
    if host_uname:
        req_buttons.append([InlineKeyboardButton("💬 Message host", url=f"https://t.me/{host_uname}")])
    req_buttons.append([InlineKeyboardButton("🏠 Main menu", callback_data="main_menu")])
    try:
        await context.bot.send_message(
            chat_id=req["requester_id"],
            text=f"🎉 *You've been accepted to Crew #{req['crew_id']}!*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(req_buttons),
        )
    except Exception:
        pass


async def jdecline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    req_id = int(query.data.removeprefix("jdecline_"))
    req = next((r for r in join_requests if r["id"] == req_id), None)
    if not req or req["status"] != "pending":
        await query.edit_message_text("This request is no longer pending.")
        return

    req["status"] = "declined"
    await query.edit_message_text(
        f"❌ Request from *{req['first_name']}* declined.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main menu", callback_data="main_menu")]]),
    )
    try:
        await context.bot.send_message(
            chat_id=req["requester_id"],
            text=f"Your request to Crew #{req['crew_id']} wasn't accepted.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main menu", callback_data="main_menu")]]),
        )
    except Exception:
        pass


# ── Other button handlers ────────────────────────────────────────────────────

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    uid = update.effective_user.id

    if query.data == "find_crew":
        visible = [c for c in published_crews if c["creator_id"] != uid]
        if not visible:
            await query.edit_message_text(
                "👯 *No crews yet.* Check back soon!",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main menu", callback_data="main_menu")]]),
            )
            return
        lines = ["👯 *Crews looking for people*\n"]
        buttons = []
        for c in visible:
            lines.append(f"*#{c['id']} — {c['area']}*\n👥 {c['crew_size']} people · +{c['looking_for']} wanted\n{c['vibe']}\n")
            buttons.append([InlineKeyboardButton(f"View crew #{c['id']}", callback_data=f"view_crew_{c['id']}")])
        buttons.append([InlineKeyboardButton("🏠 Main menu", callback_data="main_menu")])
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

    elif query.data == "my_crew":
        crew = next((c for c in published_crews if c["creator_id"] == uid), None)
        if not crew:
            await query.edit_message_text(
                "You don't have an active crew. Use /start to create one.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main menu", callback_data="main_menu")]]),
            )
            return
        text = (
            f"🔥 *My Crew #{crew['id']}*\n\n"
            f"📍 {crew['area']}\n{crew['vibe']}\n"
            f"👥 {crew['crew_size']} already · looking for {crew['looking_for']} more\n"
        )
        if crew.get("message"):
            text += f'\n_"{crew["message"]}"_\n'
        await query.edit_message_text(text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main menu", callback_data="main_menu")]]))

    elif query.data == "main_menu":
        await query.edit_message_text(MAIN_MENU_TEXT, parse_mode="Markdown", reply_markup=MAIN_MENU_KEYBOARD)

    else:
        await query.edit_message_text("Unknown action.")


# ── App setup ───────────────────────────────────────────────────────────────

def main() -> None:
    if not TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set in .env")

    app = Application.builder().token(TOKEN).build()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        create_crew_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(create_crew_start, pattern="^create_crew$")],
            states={
                CREW_SIZE:   [CallbackQueryHandler(crew_size,    pattern="^size_")],
                LOOKING_FOR: [CallbackQueryHandler(looking_for,  pattern="^looking_")],
                VIBE:        [CallbackQueryHandler(vibe,         pattern="^vibe_")],
                AREA:        [CallbackQueryHandler(area,         pattern="^area_")],
                MESSAGE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, message_text),
                    CallbackQueryHandler(message_skip, pattern="^msg_skip$"),
                ],
                CONFIRM: [CallbackQueryHandler(confirm, pattern="^confirm_")],
            },
            fallbacks=[CommandHandler("start", start)],
            per_message=False,
        )

    # ConversationHandler must be registered before the catch-all button handler
    app.add_handler(create_crew_conv)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(view_crew,      pattern="^view_crew_"))
    app.add_handler(CallbackQueryHandler(member_profile, pattern="^member_"))
    app.add_handler(CallbackQueryHandler(request_join,   pattern="^join_"))
    app.add_handler(CallbackQueryHandler(jview,          pattern="^jview_"))
    app.add_handler(CallbackQueryHandler(jaccept,        pattern="^jaccept_"))
    app.add_handler(CallbackQueryHandler(jdecline,       pattern="^jdecline_"))
    app.add_handler(CallbackQueryHandler(button))

    print("Bot is running... Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()

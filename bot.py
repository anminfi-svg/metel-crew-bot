import os
import traceback
import warnings
from datetime import date, datetime
from dotenv import load_dotenv
from supabase import create_client
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

_sb_url = os.getenv("SUPABASE_URL")
_sb_key = os.getenv("SUPABASE_KEY")
if not _sb_url or not _sb_key:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in .env")
sb = create_client(_sb_url, _sb_key)

# Conversation states
OCCASION_TYPE, TITLE, EVENT_DATE, CREW_SIZE, LOOKING_FOR, VIBE, AREA, MESSAGE, CONFIRM = range(9)

MAIN_MENU_TEXT = (
    "👯 *Crew Finder*\n\n"
    "Looking for people to go out with?\n"
    "Find a crew, join one, or create your own."
)

MAIN_MENU_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("👯 Find a crew",   callback_data="find_crew")],
    [InlineKeyboardButton("➕ Create a crew", callback_data="create_crew")],
    [InlineKeyboardButton("🔥 My crews",      callback_data="my_crews")],
    [InlineKeyboardButton("👤 My profile",    callback_data="my_profile")],
])

OCCASION_LABELS = {
    "occasion_party":   "🎉 Party / event",
    "occasion_drinks":  "🍸 Drinks / pregame",
    "occasion_club":    "🕺 Club night",
    "occasion_concert": "🎵 Concert / rave",
    "occasion_hangout": "🏖 Hangout",
    "occasion_other":   "✍️ Other",
}

VIBE_LABELS = {
    "vibe_chill":    "🍸 Chill / drinks",
    "vibe_dance":    "💃 Dance all night",
    "vibe_fullsend": "🔥 Full send",
    "vibe_social":   "🫂 Social / meet people",
}


def _format_date(date_str: str) -> str:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        return f"{d.strftime('%b')} {d.day}"
    except Exception:
        return date_str


def _is_past_crew(crew: dict) -> bool:
    ed = crew.get("event_date")
    if not ed:
        return False
    try:
        return datetime.strptime(ed, "%Y-%m-%d").date() < date.today()
    except Exception:
        return False


def _get_user_crews(uid: int) -> list:
    created = sb.table("crews").select("*").eq("creator_id", uid).execute().data or []
    member_rows = sb.table("crew_members").select("crew_id").eq("telegram_id", uid).execute().data or []

    # Seed the result dict with all created crews (deduplicates by id)
    all_crews: dict = {c["id"]: c for c in created}

    # Fetch any crews the user joined but didn't create
    for row in member_rows:
        cid = row["crew_id"]
        if cid not in all_crews:
            rows = sb.table("crews").select("*").eq("id", cid).execute().data or []
            if rows:
                all_crews[rows[0]["id"]] = rows[0]

    return list(all_crews.values())


def _crew_card(c: dict) -> str:
    title = c.get("title") or c.get("area", "Unknown")
    occasion = c.get("occasion_type")
    ed = c.get("event_date")

    lines = [f"*#{c['id']} — {title}*"]
    parts = []
    if occasion:
        parts.append(occasion)
    if ed:
        parts.append(_format_date(ed))
    if parts:
        lines.append(" · ".join(parts))
    lines.append(f"📍 {c['area']}")
    lines.append(f"👥 {c['current_size']} people · +{c['spots_needed']} wanted")
    return "\n".join(lines)


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

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎉 Party / event",    callback_data="occasion_party")],
        [InlineKeyboardButton("🍸 Drinks / pregame", callback_data="occasion_drinks")],
        [InlineKeyboardButton("🕺 Club night",        callback_data="occasion_club")],
        [InlineKeyboardButton("🎵 Concert / rave",   callback_data="occasion_concert")],
        [InlineKeyboardButton("🏖 Hangout",          callback_data="occasion_hangout")],
        [InlineKeyboardButton("✍️ Other",            callback_data="occasion_other")],
    ])
    await query.edit_message_text(
        "➕ *Create a gang*\n\nWhat are you making a gang for?",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    return OCCASION_TYPE


async def occasion_type_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["occasion_type"] = OCCASION_LABELS[query.data]
    await query.edit_message_text(
        "What's it called?\n\ne.g. _METEL Back 2 School_, _Friday drinks_, _Hyde Park picnic_",
        parse_mode="Markdown",
    )
    return TITLE


async def title_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    title = update.message.text.strip()
    if not title:
        await update.message.reply_text("Please enter a name for your event.")
        return TITLE
    context.user_data["title"] = title
    await update.message.reply_text(
        "📅 When is it?\n\nEnter the date as *DD/MM/YYYY*\ne.g. _11/09/2026_",
        parse_mode="Markdown",
    )
    return EVENT_DATE


async def event_date_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.strip()
    try:
        parsed = datetime.strptime(raw, "%d/%m/%Y").date()
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid date. Please use *DD/MM/YYYY* format, e.g. _11/09/2026_",
            parse_mode="Markdown",
        )
        return EVENT_DATE

    if parsed < date.today():
        await update.message.reply_text("❌ That date is in the past. Please enter a future date.")
        return EVENT_DATE

    context.user_data["event_date"] = parsed.strftime("%Y-%m-%d")
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("1", callback_data="size_1"),
        InlineKeyboardButton("2", callback_data="size_2"),
        InlineKeyboardButton("3", callback_data="size_3"),
        InlineKeyboardButton("4+", callback_data="size_4+"),
    ]])
    await update.message.reply_text(
        "How many people are already in your gang?",
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
        [InlineKeyboardButton("🍸 Chill / drinks",       callback_data="vibe_chill")],
        [InlineKeyboardButton("💃 Dance all night",      callback_data="vibe_dance")],
        [InlineKeyboardButton("🔥 Full send",            callback_data="vibe_fullsend")],
        [InlineKeyboardButton("🫂 Social / meet people", callback_data="vibe_social")],
    ])
    await query.edit_message_text("What's the vibe?", reply_markup=keyboard)
    return VIBE


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
        "💬 Got a one-line message for your gang? _(optional)_\n\n"
        "e.g. _Pregaming around 9_\n\n"
        "Type it below or tap Skip.",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    return MESSAGE


def _build_preview(context: ContextTypes.DEFAULT_TYPE) -> tuple[str, InlineKeyboardMarkup]:
    d = context.user_data
    text = "👯 *GANG*\n\n"
    if d.get("occasion_type"):
        text += f"{d['occasion_type']}\n"
    if d.get("title"):
        text += f"{d['title']}\n"
    if d.get("event_date"):
        text += f"📅 {_format_date(d['event_date'])}\n"
    text += (
        f"\n👥 {d['crew_size']} people already\n"
        f"➕ Looking for {d['looking_for']} more\n"
        f"{d['vibe']}\n"
        f"📍 {d['area']}\n"
    )
    if d.get("message"):
        text += f'\n"{d["message"]}"'
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


def _parse_count(s: str) -> int:
    return 4 if s == "4+" else int(s)


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_publish":
        d = context.user_data
        uid = update.effective_user.id
        try:
            sb.table("profiles").upsert({
                "telegram_id": uid,
                "first_name": update.effective_user.first_name,
                "username": update.effective_user.username,
            }).execute()
            result = sb.table("crews").insert({
                "creator_id": uid,
                "current_size": _parse_count(d["crew_size"]),
                "spots_needed": _parse_count(d["looking_for"]),
                "vibe": d["vibe"],
                "area": d["area"],
                "message": d.get("message"),
                "status": "active",
                "occasion_type": d.get("occasion_type"),
                "title": d.get("title"),
                "event_date": d.get("event_date"),
            }).execute()
            crew_id = result.data[0]["id"]
            sb.table("crew_members").insert({"crew_id": crew_id, "telegram_id": uid}).execute()
            await query.edit_message_text(
                "✅ *Gang published!*\n\nYour gang is now live. Good luck finding your people! 🎉\n\n"
                "Use /start to return to the menu.",
                parse_mode="Markdown",
            )
        except Exception as e:
            print(f"DB error publishing crew: {e}\n{traceback.format_exc()}")
            await query.edit_message_text("❌ Something went wrong. Please try again.")
    else:
        await query.edit_message_text("❌ Cancelled.\n\nUse /start to return to the menu.")

    context.user_data.clear()
    return ConversationHandler.END


# ── Crew detail & member profile ────────────────────────────────────────────

async def view_crew(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    crew_id = query.data.removeprefix("view_crew_")

    try:
        crew_result = sb.table("crews").select("*").eq("id", crew_id).execute()
        if not crew_result.data:
            await query.edit_message_text("Crew not found. Use /start to go back.")
            return
        crew = crew_result.data[0]

        creator_result = sb.table("profiles").select("first_name, username").eq("telegram_id", crew["creator_id"]).execute()
        creator = creator_result.data[0] if creator_result.data else {}

        members_result = sb.table("crew_members").select("telegram_id").eq("crew_id", crew_id).execute()
        member_uids = [m["telegram_id"] for m in members_result.data]

        member_profiles = {}
        if member_uids:
            profiles_result = sb.table("profiles").select("telegram_id, first_name").in_("telegram_id", member_uids).execute()
            member_profiles = {p["telegram_id"]: p for p in profiles_result.data}

        viewer_uid = update.effective_user.id
        pending_result = (
            sb.table("join_requests")
            .select("id")
            .eq("crew_id", crew_id)
            .eq("requester_id", viewer_uid)
            .eq("status", "pending")
            .execute()
        )
        has_pending = len(pending_result.data) > 0
    except Exception as e:
        print(f"DB error loading crew: {e}")
        await query.edit_message_text("Failed to load crew. Please try again.")
        return

    is_past = _is_past_crew(crew)
    total = (crew.get("current_size") or 0) + (crew.get("spots_needed") or 0)

    text = f"👯 *CREW #{crew['id']}*\n\n"
    if crew.get("occasion_type"):
        text += f"{crew['occasion_type']}\n"
    if crew.get("title"):
        text += f"{crew['title']}\n"
    if crew.get("event_date"):
        text += f"📅 {_format_date(crew['event_date'])}\n"
    text += f"\n📍 {crew['area']}\n{crew['vibe']}\n👥 {crew['current_size']}/{total} people\n"
    if crew.get("message"):
        text += f'\n_"{crew["message"]}"_\n'

    creator_line = f"👑 {creator.get('first_name', 'Unknown')}"
    if creator.get("username"):
        creator_line += f" — @{creator['username']}"
    text += f"\n{creator_line}\n"

    buttons = []
    for uid_m in member_uids:
        p = member_profiles.get(uid_m, {})
        name = p.get("first_name", str(uid_m))
        buttons.append([InlineKeyboardButton(f"👤 {name}", callback_data=f"member_{uid_m}_{crew_id}")])

    is_own = crew["creator_id"] == viewer_uid
    is_member = viewer_uid in member_uids
    if not is_past and not is_own and not is_member and not has_pending:
        buttons.append([InlineKeyboardButton("🙋 Request to join", callback_data=f"join_{crew_id}")])

    back_cb = "my_crews_past" if is_past else "find_crew"
    back_label = "⬅️ Back" if is_past else "⬅️ Back to crews"
    buttons.append([
        InlineKeyboardButton(back_label, callback_data=back_cb),
        InlineKeyboardButton("🏠 Main menu", callback_data="main_menu"),
    ])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))


async def member_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, uid_str, crew_id_str = query.data.split("_", 2)
    uid = int(uid_str)
    crew_id = crew_id_str

    try:
        result = sb.table("profiles").select("first_name, username").eq("telegram_id", uid).execute()
        p = result.data[0] if result.data else {}
    except Exception as e:
        print(f"DB error loading member profile: {e}")
        p = {}

    name = p.get("first_name", "Unknown")
    username = p.get("username")

    text = f"👤 *{name}*"
    if username:
        text += f"\n\nTelegram: @{username}"

    buttons = []
    if username:
        buttons.append([InlineKeyboardButton("💬 Open Telegram", url=f"https://t.me/{username}")])
    buttons.append([
        InlineKeyboardButton("⬅️ Back to crew", callback_data=f"view_crew_{crew_id}"),
        InlineKeyboardButton("🏠 Main menu",     callback_data="main_menu"),
    ])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))


# ── Join request flow ───────────────────────────────────────────────────────

async def request_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    crew_id = query.data.removeprefix("join_")
    uid = update.effective_user.id

    try:
        crew_result = sb.table("crews").select("creator_id").eq("id", crew_id).execute()
        crew = crew_result.data[0] if crew_result.data else None
        existing_result = (
            sb.table("join_requests")
            .select("id")
            .eq("crew_id", crew_id)
            .eq("requester_id", uid)
            .eq("status", "pending")
            .execute()
        )
    except Exception as e:
        print(f"DB error checking join request: {e}")
        await query.answer("Something went wrong. Please try again.", show_alert=True)
        return

    if not crew:
        await query.answer("Crew not found.", show_alert=True)
        return
    if crew["creator_id"] == uid:
        await query.answer("That's your own crew!", show_alert=True)
        return
    if existing_result.data:
        await query.answer("You already sent a request to this crew.", show_alert=True)
        return

    await query.answer()

    try:
        sb.table("profiles").upsert({
            "telegram_id": uid,
            "first_name": update.effective_user.first_name,
            "username": update.effective_user.username,
        }).execute()
        req_result = sb.table("join_requests").insert({
            "crew_id": crew_id,
            "requester_id": uid,
            "status": "pending",
        }).execute()
        req_id = req_result.data[0]["id"]
    except Exception as e:
        print(f"DB error creating join request: {e}")
        await query.edit_message_text("Failed to send request. Please try again.")
        return

    await query.edit_message_text(
        "✅ *Join request sent to the crew creator.*\n\nYou'll be notified when they respond.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main menu", callback_data="main_menu")]]),
    )

    uname_line = f"\n@{update.effective_user.username}" if update.effective_user.username else ""
    notif_text = f"🙋 *New join request for Crew #{crew_id}*\n\n{update.effective_user.first_name}{uname_line}"
    notif_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 View requester", callback_data=f"jview_{req_id}")],
        [
            InlineKeyboardButton("✅ Accept",  callback_data=f"jaccept_{req_id}"),
            InlineKeyboardButton("❌ Decline", callback_data=f"jdecline_{req_id}"),
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
    req_id = query.data.removeprefix("jview_")

    try:
        req_result = sb.table("join_requests").select("requester_id, crew_id, status").eq("id", req_id).execute()
        if not req_result.data:
            await query.edit_message_text("Request not found.")
            return
        req = req_result.data[0]
        profile_result = sb.table("profiles").select("first_name, username").eq("telegram_id", req["requester_id"]).execute()
        p = profile_result.data[0] if profile_result.data else {}
    except Exception as e:
        print(f"DB error loading join request: {e}")
        await query.edit_message_text("Failed to load request. Please try again.")
        return

    name = p.get("first_name", "Unknown")
    username = p.get("username")
    text = f"👤 *{name}*"
    if username:
        text += f"\n@{username}"

    buttons = []
    if username:
        buttons.append([InlineKeyboardButton("💬 Open Telegram", url=f"https://t.me/{username}")])
    buttons.append([
        InlineKeyboardButton("✅ Accept",  callback_data=f"jaccept_{req_id}"),
        InlineKeyboardButton("❌ Decline", callback_data=f"jdecline_{req_id}"),
    ])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))


async def jaccept(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    req_id = query.data.removeprefix("jaccept_")

    try:
        req_result = sb.table("join_requests").select("*").eq("id", req_id).execute()
        if not req_result.data or req_result.data[0]["status"] != "pending":
            await query.edit_message_text("This request is no longer pending.")
            return
        req = req_result.data[0]

        sb.table("join_requests").update({"status": "accepted"}).eq("id", req_id).execute()
        sb.table("crew_members").insert({"crew_id": req["crew_id"], "telegram_id": req["requester_id"]}).execute()

        crew_result = sb.table("crews").select("current_size, creator_id").eq("id", req["crew_id"]).execute()
        crew = crew_result.data[0] if crew_result.data else {}
        new_size = (crew.get("current_size") or 1) + 1
        sb.table("crews").update({"current_size": new_size}).eq("id", req["crew_id"]).execute()

        requester_result = sb.table("profiles").select("first_name, username").eq("telegram_id", req["requester_id"]).execute()
        requester_p = requester_result.data[0] if requester_result.data else {}

        creator_p = {}
        if crew.get("creator_id"):
            creator_result = sb.table("profiles").select("username").eq("telegram_id", crew["creator_id"]).execute()
            creator_p = creator_result.data[0] if creator_result.data else {}
    except Exception as e:
        print(f"DB error accepting request: {e}")
        await query.edit_message_text("Failed to accept request. Please try again.")
        return

    name = requester_p.get("first_name", "Unknown")
    r_uname = requester_p.get("username")
    host_uname = creator_p.get("username")

    creator_buttons = []
    if r_uname:
        creator_buttons.append([InlineKeyboardButton(f"💬 Message {name}", url=f"https://t.me/{r_uname}")])
    creator_buttons.append([InlineKeyboardButton("🏠 Main menu", callback_data="main_menu")])
    await query.edit_message_text(
        f"✅ *{name} joined your crew.*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(creator_buttons),
    )

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
    req_id = query.data.removeprefix("jdecline_")

    try:
        req_result = sb.table("join_requests").select("requester_id, crew_id, status").eq("id", req_id).execute()
        if not req_result.data or req_result.data[0]["status"] != "pending":
            await query.edit_message_text("This request is no longer pending.")
            return
        req = req_result.data[0]
        profile_result = sb.table("profiles").select("first_name").eq("telegram_id", req["requester_id"]).execute()
        first_name = profile_result.data[0].get("first_name", "Unknown") if profile_result.data else "Unknown"
        sb.table("join_requests").update({"status": "declined"}).eq("id", req_id).execute()
    except Exception as e:
        print(f"DB error declining request: {e}")
        await query.edit_message_text("Failed to decline request. Please try again.")
        return

    await query.edit_message_text(
        f"❌ Request from *{first_name}* declined.",
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
        try:
            result = sb.table("crews").select("*").eq("status", "active").execute()
            visible = [
                c for c in result.data
                if c["creator_id"] != uid and not _is_past_crew(c)
            ]
        except Exception as e:
            print(f"DB error loading crews: {e}")
            await query.edit_message_text("Failed to load crews. Please try again.")
            return

        visible.sort(key=lambda c: c.get("event_date") or "9999-12-31")

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
            lines.append(_crew_card(c) + "\n")
            buttons.append([InlineKeyboardButton(f"View crew #{c['id']}", callback_data=f"view_crew_{c['id']}")])
        buttons.append([InlineKeyboardButton("🏠 Main menu", callback_data="main_menu")])
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

    elif query.data == "my_crews":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔥 Active crews", callback_data="my_crews_active")],
            [InlineKeyboardButton("🗂 Past crews",   callback_data="my_crews_past")],
            [InlineKeyboardButton("🏠 Main menu",    callback_data="main_menu")],
        ])
        await query.edit_message_text("🔥 *My crews*", parse_mode="Markdown", reply_markup=keyboard)

    elif query.data == "my_crews_active":
        try:
            all_crews = _get_user_crews(uid)
        except Exception as e:
            print(f"DB error loading my crews (active): {e}\n{traceback.format_exc()}")
            await query.edit_message_text("Failed to load your crews. Please try again.")
            return

        active = [c for c in all_crews if c.get("status") == "active" and not _is_past_crew(c)]
        active.sort(key=lambda c: c.get("event_date") or "9999-12-31")

        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="my_crews")],
            [InlineKeyboardButton("🏠 Main menu", callback_data="main_menu")],
        ])
        if not active:
            await query.edit_message_text("You have no active crews.", reply_markup=back_kb)
            return

        lines = ["🔥 *Active crews*\n"]
        buttons = []
        for c in active:
            lines.append(_crew_card(c) + "\n")
            buttons.append([InlineKeyboardButton(f"View crew #{c['id']}", callback_data=f"view_crew_{c['id']}")])
        buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="my_crews")])
        buttons.append([InlineKeyboardButton("🏠 Main menu", callback_data="main_menu")])
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

    elif query.data == "my_crews_past":
        try:
            all_crews = _get_user_crews(uid)
        except Exception as e:
            print(f"DB error loading my crews (past): {e}\n{traceback.format_exc()}")
            await query.edit_message_text("Failed to load your crews. Please try again.")
            return

        past = [c for c in all_crews if _is_past_crew(c) or c.get("status") == "archived"]
        past.sort(key=lambda c: c.get("event_date") or "0000-01-01", reverse=True)

        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="my_crews")],
            [InlineKeyboardButton("🏠 Main menu", callback_data="main_menu")],
        ])
        if not past:
            await query.edit_message_text("You have no past crews.", reply_markup=back_kb)
            return

        lines = ["🗂 *Past crews*\n"]
        buttons = []
        for c in past:
            lines.append(_crew_card(c) + "\n")
            buttons.append([InlineKeyboardButton(f"View crew #{c['id']}", callback_data=f"view_crew_{c['id']}")])
        buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="my_crews")])
        buttons.append([InlineKeyboardButton("🏠 Main menu", callback_data="main_menu")])
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

    elif query.data == "my_profile":
        try:
            sb.table("profiles").upsert({
                "telegram_id": uid,
                "first_name": update.effective_user.first_name,
                "username": update.effective_user.username,
            }).execute()
            result = sb.table("profiles").select("first_name, username").eq("telegram_id", uid).execute()
            p = result.data[0] if result.data else {}
        except Exception as e:
            print(f"DB error loading profile: {e}")
            p = {}

        name = p.get("first_name") or update.effective_user.first_name or "Unknown"
        username = p.get("username") or update.effective_user.username
        text = f"👤 *{name}*"
        if username:
            text += f"\n@{username}"
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main menu", callback_data="main_menu")]]),
        )

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
                OCCASION_TYPE: [CallbackQueryHandler(occasion_type_handler, pattern="^occasion_")],
                TITLE:         [MessageHandler(filters.TEXT & ~filters.COMMAND, title_text)],
                EVENT_DATE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, event_date_text)],
                CREW_SIZE:     [CallbackQueryHandler(crew_size,   pattern="^size_")],
                LOOKING_FOR:   [CallbackQueryHandler(looking_for, pattern="^looking_")],
                VIBE:          [CallbackQueryHandler(vibe,        pattern="^vibe_")],
                AREA:          [CallbackQueryHandler(area,        pattern="^area_")],
                MESSAGE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, message_text),
                    CallbackQueryHandler(message_skip, pattern="^msg_skip$"),
                ],
                CONFIRM: [CallbackQueryHandler(confirm, pattern="^confirm_")],
            },
            fallbacks=[CommandHandler("start", start)],
            per_message=False,
            allow_reentry=True,
        )

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

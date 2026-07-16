"""
Life Energy — Telegram sales bot
=================================
Handles the first-contact conversation with a lead: greets them, finds out
what they're interested in, recommends a package, books them for a free
diagnostic consultation, logs everything to Google Sheets, and hands the
lead off to a real person (Ірина / partner) for the live conversation.

The bot NEVER closes a sale or gives final pricing commitments by itself —
its only job is to qualify, inform, and schedule. Every "ready" lead is
pushed to the admin's Telegram chat so a human can take over.
"""
import logging
import os
import traceback
from datetime import datetime, timedelta

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from sheets import log_lead, update_lead_status

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")  # set after running /whoami once

# ---------------------------------------------------------------------------
# Conversation states
# ---------------------------------------------------------------------------
CHOOSING_INTEREST, ASK_TIME, ASK_NAME, ASK_CONTACT, DIRECT_SURVEY = range(5)

# ---------------------------------------------------------------------------
# Copy — pulled directly from the Life Energy administrator playbook
# ---------------------------------------------------------------------------
WELCOME = (
    "Добрий день! 😊\n"
    "Дякуємо за ваш інтерес до екосистеми Life Energy.\n"
    "Підкажіть, будь ласка, що саме вас зацікавило?"
)

INTEREST_OPTIONS = [
    ("literacy", "🔹 Фінансова грамотність"),
    ("income", "🔹 Додатковий дохід"),
    ("career", "🔹 Нова професія"),
    ("invest", "🔹 Інвестування"),
    ("business", "🔹 Розвиток бізнесу"),
    ("unsure", "🤔 Ще не знаю, що обрати"),
]

INTEREST_REPLIES = {
    "unsure": (
        "Чудово.\nСаме для таких випадків ми проводимо безкоштовно "
        "«Діагностику фінансового потенціалу Life Energy».\n\n"
        "За 10–15 хвилин консультант допоможе:\n"
        "✔ оцінити вашу поточну фінансову ситуацію;\n"
        "✔ визначити ваші цілі;\n"
        "✔ підібрати програму, яка буде максимально корисною саме для вас.\n\n"
        "Консультація безкоштовна та ні до чого не зобов'язує."
    ),
    "literacy": (
        "Дякую.\nЯкраз для цього в екосистемі Life Energy є навчальна програма, яка допомагає:\n"
        "✔ навчитися керувати особистими фінансами;\n"
        "✔ планувати бюджет;\n"
        "✔ створювати фінансовий резерв;\n"
        "✔ формувати власний капітал.\n\n"
        "Щоб зрозуміти, чи саме ця програма буде для вас найкращою, пропонуємо коротку "
        "безкоштовну консультацію."
    ),
    "income": (
        "Чудово.\nБагато наших учасників починали саме з такого запиту.\n"
        "В екосистемі Life Energy є програма, яка допомагає опанувати професію фінансового "
        "консультанта та створити додаткове джерело доходу.\n\n"
        "Спочатку ми проводимо коротку консультацію, щоб зрозуміти, чи цей напрям відповідає "
        "вашим цілям."
    ),
    "career": (
        "Дякую за відповідь.\nВ екосистемі Life Energy є програма, яка допомагає опанувати "
        "професію фінансового консультанта та створити додаткове джерело доходу.\n\n"
        "На консультації ми розповімо:\n"
        "✔ як проходить навчання;\n"
        "✔ які компетенції отримують учасники;\n"
        "✔ як відбувається супровід;\n"
        "✔ які можливості професійного розвитку відкриває екосистема Life Energy."
    ),
    "invest": (
        "Дякую.\nІнвестиційний напрямок входить до наших програм «Фінансовий радник» та "
        "«Professional & Leader» — там є окремий модуль про фінансові інструменти, включно з "
        "інвестиціями та криптовалютою.\n\n"
        "Пропонуємо коротку безкоштовну консультацію, щоб підібрати правильний рівень."
    ),
    "business": (
        "Дякую.\nДля підприємців і керівників ми маємо окремий напрямок розвитку, який "
        "допомагає систематизувати фінанси, масштабувати діяльність та розвивати лідерські "
        "компетенції.\n\n"
        "Після короткої консультації зможемо рекомендувати програму, яка найбільше "
        "відповідатиме вашим цілям."
    ),
}

TIME_OPTIONS = [
    ("today", "Сьогодні"),
    ("tomorrow", "Завтра"),
    ("week", "Цього тижня"),
    ("text", "Краще напишіть мені текстом"),
]

PRICE_ANSWER = (
    "Вартість залежить від програми, яка буде найбільш корисною саме для вас.\n"
    "Саме тому ми спочатку проводимо коротку консультацію, щоб зрозуміти ваші потреби та "
    "запропонувати оптимальний варіант. Після цього консультант детально розповість про "
    "програму, її наповнення та умови участі."
)

WHAT_IS_THIS_ANSWER = (
    "Life Energy — це освітня екосистема, яка допомагає людям розвивати фінансову "
    "грамотність, формувати здорові фінансові звички, опановувати сучасні фінансові "
    "компетенції та, за бажанням, розвиватися у професії фінансового консультанта."
)

# Simple keyword triggers checked on any free-text message outside the flow
PRICE_KEYWORDS = ("скільки коштує", "яка ціна", "вартість", "прайс", "ціна")
WHAT_KEYWORDS = ("що це", "що таке life energy", "розкажіть про", "що взагалі")
START_KEYWORD = "старт"


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    context.user_data["started_at"] = datetime.utcnow().isoformat()
    keyboard = [
        [InlineKeyboardButton(label, callback_data=key)] for key, label in INTEREST_OPTIONS
    ]
    await update.message.reply_text(WELCOME, reply_markup=InlineKeyboardMarkup(keyboard))
    return CHOOSING_INTEREST


async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Utility command so the admin can find their own chat_id once."""
    await update.message.reply_text(f"Ваш chat_id: {update.effective_chat.id}")


async def interest_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    interest_key = query.data
    context.user_data["interest"] = interest_key
    reply_text = INTEREST_REPLIES.get(interest_key, INTEREST_REPLIES["unsure"])

    keyboard = [[InlineKeyboardButton(label, callback_data=key)] for key, label in TIME_OPTIONS]
    await query.edit_message_text(reply_text)
    await query.message.reply_text(
        "Коли вам буде зручно поспілкуватися?", reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ASK_TIME


async def time_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    time_key = query.data
    context.user_data["preferred_time"] = time_key

    if time_key == "text":
        await query.edit_message_text(
            "Добре! Напишіть, будь ласка, кілька слів про вашу ситуацію — і консультант "
            "відповість вам особисто найближчим часом."
        )
        context.user_data["status"] = "escalated_to_text"
        await _notify_admin(context, update.effective_user, context.user_data, note="Хоче написати текстом")
        return ConversationHandler.END

    await query.edit_message_text("Чудово! Як до вас звертатися?")
    return ASK_NAME


async def name_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["name"] = update.message.text.strip()
    contact_button = ReplyKeyboardMarkup(
        [[{"text": "📱 Надіслати номер телефону", "request_contact": True}]],
        one_time_keyboard=True,
        resize_keyboard=True,
    )
    await update.message.reply_text(
        "Дякуємо! Надішліть, будь ласка, номер телефону — консультант зв'яжеться з вами у "
        "визначений час.",
        reply_markup=contact_button,
    )
    return ASK_CONTACT


async def contact_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = update.message.text.strip()
    context.user_data["phone"] = phone
    context.user_data["status"] = "diagnostic_booked"

    user = update.effective_user
    try:
        log_lead(
            telegram_username=user.username or "",
            telegram_id=user.id,
            name=context.user_data.get("name", ""),
            phone=phone,
            interest=context.user_data.get("interest", ""),
            preferred_time=context.user_data.get("preferred_time", ""),
            status="diagnostic_booked",
        )
    except Exception:
        err_text = traceback.format_exc().replace("\n", " | ")
        logger.error("SHEET_WRITE_FAILED: %s", err_text)

    await update.message.reply_text(
        "Записали вас на безкоштовну діагностику фінансового потенціалу. 🌿\n"
        "Наш консультант зв'яжеться з вами у визначений час. Дякуємо за довіру до Life Energy!",
        reply_markup=ReplyKeyboardRemove(),
    )
    await _notify_admin(context, user, context.user_data, note="Готовий(-а) до діагностики")

    if context.job_queue and context.user_data.get("preferred_time") == "week":
        context.job_queue.run_once(
            _followup_job,
            when=timedelta(hours=24),
            chat_id=update.effective_chat.id,
            name=f"followup_{update.effective_chat.id}",
        )
    return ConversationHandler.END


async def _followup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_message(
        chat_id=context.job.chat_id,
        text="Добрий день! 😊 Чи все ще актуальна тема фінансового розвитку? "
        "Буду рада допомогти призначити зручний час для консультації.",
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Дякую за вашу відповідь. Рішення про навчання завжди має бути усвідомленим. "
        "Якщо виникнуть будь-які запитання — я із задоволенням допоможу.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


async def free_text_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.lower()

    if START_KEYWORD in text:
        await start(update, context)
        return

    if any(k in text for k in PRICE_KEYWORDS):
        await update.message.reply_text(PRICE_ANSWER)
        return

    if any(k in text for k in WHAT_KEYWORDS):
        await update.message.reply_text(WHAT_IS_THIS_ANSWER)
        return

    await update.message.reply_text(
        "Дякую за повідомлення! Я передала його консультанту Life Energy — з вами зв'яжуться "
        "найближчим часом. Якщо хочете, можу одразу записати вас на безкоштовну діагностику: "
        "напишіть слово «СТАРТ»."
    )
    await _notify_admin(
        context, update.effective_user, {"raw_message": update.message.text}, note="Незрозуміле повідомлення — потрібна людина"
    )


async def _notify_admin(context: ContextTypes.DEFAULT_TYPE, user, data: dict, note: str) -> None:
    if not ADMIN_CHAT_ID:
        logger.warning("ADMIN_CHAT_ID не встановлено — сповіщення не надіслано")
        return
    lines = [f"🔔 {note}", f"Від: @{user.username or user.id} ({user.full_name})"]
    for key, label in (
        ("interest", "Інтерес"),
        ("preferred_time", "Бажаний час"),
        ("name", "Ім'я"),
        ("phone", "Телефон"),
        ("raw_message", "Повідомлення"),
    ):
        if data.get(key):
            lines.append(f"{label}: {data[key]}")
    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text="\n".join(lines))


def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex(r"(?i)старт"), start),
        ],
        states={
            CHOOSING_INTEREST: [CallbackQueryHandler(interest_chosen)],
            ASK_TIME: [CallbackQueryHandler(time_chosen)],
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, name_received)],
            ASK_CONTACT: [
                MessageHandler(filters.CONTACT, contact_received),
                MessageHandler(filters.TEXT & ~filters.COMMAND, contact_received),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, free_text_fallback))
    return app


if __name__ == "__main__":
    application = build_app()
    logger.info("Life Energy bot запущено — очікую повідомлення...")
    application.run_polling()

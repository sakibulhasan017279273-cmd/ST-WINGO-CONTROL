import os
import asyncio
import logging
import requests

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHANNEL_USERNAME = os.getenv(
    "CHANNEL_USERNAME",
    ""
).strip()

API_URL = (
    "https://draw.ar-lottery01.com/"
    "WinGo/WinGo_1M/GetHistoryIssuePage.json"
)

CHECK_INTERVAL = 4

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# ============================================================
# MEMORY
# ============================================================

last_issue = None
active_signal = None
last_result_issue = None


# ============================================================
# WIN GO API
# ============================================================

def get_history():

    try:

        response = requests.get(
            API_URL,
            params={"t": int(asyncio.get_event_loop().time() * 1000)},
            timeout=10,
            headers={
                "User-Agent": "ST-Wingo-Master/1.0",
                "Accept": "application/json",
            },
        )

        response.raise_for_status()

        data = response.json()

        history = (
            data
            .get("data", {})
            .get("list", [])
        )

        if not isinstance(history, list):
            return []

        return history

    except Exception as error:

        logger.error(
            "API error: %s",
            error
        )

        return []


# ============================================================
# HELPERS
# ============================================================

def number_of(item):

    try:
        return int(item.get("number"))
    except Exception:
        return None


def big_small(number):

    if number is None:
        return None

    return "BIG" if number >= 5 else "SMALL"


def next_period(issue):

    try:
        return str(
            int(str(issue)) + 1
        )
    except Exception:
        return str(issue)


# ============================================================
# SIGNAL ENGINE
#
# This follows the supplied source structure:
# - recent history
# - BIG / SMALL classification
# - multiple observations
# - two number candidates
#
# Signals are predictions, not guaranteed outcomes.
# ============================================================

def generate_signal(history):

    numbers = []

    for item in history[:20]:

        number = number_of(item)

        if number is not None:
            numbers.append(number)

    if len(numbers) < 3:

        return {
            "prediction": "WAIT",
            "numbers": [],
            "confidence": 0,
        }


    sizes = [
        big_small(n)
        for n in numbers
    ]

    big_score = 0
    small_score = 0


    # --------------------------------------------------------
    # Recent weighted observation
    # --------------------------------------------------------

    for index, side in enumerate(
        sizes[:10]
    ):

        weight = 10 - index

        if side == "BIG":
            big_score += weight
        else:
            small_score += weight


    # --------------------------------------------------------
    # Streak reversal
    # --------------------------------------------------------

    if len(sizes) >= 3:

        if (
            sizes[0] ==
            sizes[1] ==
            sizes[2]
        ):

            if sizes[0] == "BIG":
                small_score += 8
            else:
                big_score += 8


    # --------------------------------------------------------
    # Alternation
    # --------------------------------------------------------

    if len(sizes) >= 4:

        alternating = (
            sizes[0] != sizes[1]
            and sizes[1] != sizes[2]
            and sizes[2] != sizes[3]
        )

        if alternating:

            if sizes[0] == "BIG":
                small_score += 5
            else:
                big_score += 5


    # --------------------------------------------------------
    # Frequency balance
    # --------------------------------------------------------

    big_count = sizes.count("BIG")
    small_count = sizes.count("SMALL")

    if big_count < small_count:
        big_score += 3

    elif small_count < big_count:
        small_score += 3


    # --------------------------------------------------------
    # Final BIG / SMALL
    # --------------------------------------------------------

    prediction = (
        "BIG"
        if big_score >= small_score
        else "SMALL"
    )


    # --------------------------------------------------------
    # Number candidates
    # --------------------------------------------------------

    pool = (
        [5, 6, 7, 8, 9]
        if prediction == "BIG"
        else [0, 1, 2, 3, 4]
    )

    frequency = {
        number: 0
        for number in pool
    }

    for number in numbers:

        if number in frequency:
            frequency[number] += 1


    ranked = sorted(
        pool,
        key=lambda number:
            frequency[number],
        reverse=True
    )

    number_one = ranked[0]
    number_two = ranked[1]


    # --------------------------------------------------------
    # Confidence
    # --------------------------------------------------------

    total = (
        big_score +
        small_score
    )

    if total:

        confidence = round(
            60 +
            (
                max(
                    big_score,
                    small_score
                ) / total
            ) * 30
        )

    else:
        confidence = 60

    confidence = max(
        50,
        min(98, confidence)
    )


    return {
        "prediction": prediction,
        "numbers": [
            number_one,
            number_two,
        ],
        "confidence": confidence,
    }


# ============================================================
# RESULT
# ============================================================

def calculate_result(
    signal,
    actual_number
):

    if actual_number in signal["numbers"]:
        return "JACKPOT"

    actual_size = big_small(
        actual_number
    )

    if (
        signal["prediction"]
        == actual_size
    ):
        return "WIN"

    return "LOSS"


# ============================================================
# TELEGRAM MESSAGE
# ============================================================

def signal_message(
    period,
    signal
):

    numbers = " / ".join(
        str(x)
        for x in signal["numbers"]
    )

    return (
        "🔥⚡ ST WINGO MASTER ⚡🔥\n"
        "\n"
        "🎯 <b>PERIOD</b>\n"
        f"<code>{period}</code>\n"
        "\n"
        "💥 <b>SIGNAL</b>\n"
        f"<b>{signal['prediction']}</b>\n"
        "\n"
        "🎰 <b>NUMBERS</b>\n"
        f"<b>{numbers}</b>\n"
        "\n"
        "💯 <b>CONFIDENCE</b>\n"
        f"<b>{signal['confidence']}%</b>\n"
        "\n"
        "⏱ <b>MARKET</b>\n"
        "<b>WINGO 1 MIN</b>\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ Prediction only — "
        "no result is guaranteed."
    )


def result_message(
    period,
    actual,
    result
):

    emoji = {
        "WIN": "👑",
        "LOSS": "❌",
        "JACKPOT": "🎰",
    }.get(result, "📊")

    return (
        f"{emoji} <b>{result}</b>\n"
        "\n"
        f"🎯 Period: <code>{period}</code>\n"
        f"🔢 Result Number: <b>{actual}</b>\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔥 ST WINGO MASTER"
    )


# ============================================================
# SEND CHANNEL
# ============================================================

async def send_channel(
    application,
    text
):

    if not CHANNEL_USERNAME:
        logger.warning(
            "CHANNEL_USERNAME is not configured."
        )
        return

    try:

        await application.bot.send_message(
            chat_id=CHANNEL_USERNAME,
            text=text,
            parse_mode="HTML",
        )

    except Exception as error:

        logger.error(
            "Telegram send error: %s",
            error
        )


# ============================================================
# ENGINE
# ============================================================

async def engine(
    application
):

    global last_issue
    global active_signal
    global last_result_issue

    while True:

        try:

            history = get_history()

            if not history:

                await asyncio.sleep(
                    CHECK_INTERVAL
                )

                continue


            latest = history[0]

            issue = str(
                latest.get(
                    "issueNumber",
                    ""
                )
            )

            actual = number_of(
                latest
            )

            if not issue or actual is None:

                await asyncio.sleep(
                    CHECK_INTERVAL
                )

                continue


            # ------------------------------------------------
            # Previous signal result
            # ------------------------------------------------

            if (
                last_issue is not None
                and issue != last_issue
                and active_signal is not None
                and last_result_issue != issue
            ):

                result = calculate_result(
                    active_signal,
                    actual
                )

                await send_channel(
                    application,
                    result_message(
                        last_issue,
                        actual,
                        result
                    )
                )

                last_result_issue = issue


            # ------------------------------------------------
            # Generate next signal
            # ------------------------------------------------

            signal = generate_signal(
                history
            )

            period = next_period(
                issue
            )

            if (
                signal["prediction"]
                != "WAIT"
            ):

                active_signal = signal

                await send_channel(
                    application,
                    signal_message(
                        period,
                        signal
                    )
                )

            last_issue = issue


        except Exception as error:

            logger.exception(
                "Engine error: %s",
                error
            )

        await asyncio.sleep(
            CHECK_INTERVAL
        )


# ============================================================
# TELEGRAM COMMANDS
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🔥 ST WINGO MASTER\n\n"
        "Bot is online.\n"
        "Market: Wingo 1 Minute\n"
        "Use /signal to check the current signal."
    )


async def signal_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    history = get_history()

    if not history:

        await update.message.reply_text(
            "⚠️ Live API data unavailable."
        )

        return


    latest = history[0]

    issue = str(
        latest.get(
            "issueNumber",
            ""
        )
    )

    signal = generate_signal(
        history
    )

    if signal["prediction"] == "WAIT":

        await update.message.reply_text(
            "⏳ Waiting for enough live data..."
        )

        return


    await update.message.reply_text(
        signal_message(
            next_period(issue),
            signal
        ),
        parse_mode="HTML"
    )


async def status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    history = get_history()

    if history:

        issue = str(
            history[0].get(
                "issueNumber",
                ""
            )
        )

        await update.message.reply_text(
            "🟢 <b>BOT ONLINE</b>\n\n"
            f"🎯 Current Period: "
            f"<code>{issue}</code>\n"
            "⏱ Market: <b>Wingo 1M</b>",
            parse_mode="HTML"
        )

    else:

        await update.message.reply_text(
            "🔴 API connection unavailable."
        )


# ============================================================
# MAIN
# ============================================================

async def post_init(
    application
):

    await application.bot.delete_webhook(
        drop_pending_updates=True
    )

    asyncio.create_task(
        engine(application)
    )


def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN environment variable is missing."
        )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "signal",
            signal_command
        )
    )

    application.add_handler(
        CommandHandler(
            "status",
            status
        )
    )

    logger.info(
        "ST Wingo Master starting..."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()

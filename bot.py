import os
import asyncio
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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

# Render Environment Variable থেকে API নেওয়া হবে।
# না দিলে এই default endpoint ব্যবহার করবে।
API_URL = os.getenv(
    "API_URL",
    "https://draw.ar-lottery01.com/"
    "WinGo/WinGo_1M/GetHistoryIssuePage.json"
).strip()

PORT = int(
    os.getenv("PORT", "10000")
)

CHECK_INTERVAL = 3

REQUEST_TIMEOUT = 12

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger("ST-WINGO-MASTER")

# ============================================================
# MEMORY
# ============================================================

last_issue = None
active_signal = None
last_result_issue = None

stats = {
    "WIN": 0,
    "LOSS": 0,
    "JACKPOT": 0,
}

# ============================================================
# HTTP HEALTH SERVER
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        if self.path in ("/", "/health"):

            body = (
                "ST Wingo Master is running."
            ).encode("utf-8")

            self.send_response(200)

            self.send_header(
                "Content-Type",
                "text/plain; charset=utf-8"
            )

            self.send_header(
                "Content-Length",
                str(len(body))
            )

            self.end_headers()

            self.wfile.write(body)

        else:

            body = b"Not Found"

            self.send_response(404)

            self.send_header(
                "Content-Type",
                "text/plain"
            )

            self.send_header(
                "Content-Length",
                str(len(body))
            )

            self.end_headers()

            self.wfile.write(body)

    def log_message(
        self,
        format,
        *args
    ):
        return


def start_health_server():

    server = ThreadingHTTPServer(
        ("0.0.0.0", PORT),
        HealthHandler
    )

    logger.info(
        "Health server listening on port %s",
        PORT
    )

    server.serve_forever()


# ============================================================
# API SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/151.0.0.0 Mobile Safari/537.36"
    ),

    "Accept": (
        "application/json,"
        "text/plain,"
        "*/*"
    ),

    "Accept-Language": (
        "en-US,en;q=0.9"
    ),

    "Cache-Control": "no-cache",

    "Pragma": "no-cache",

    "Connection": "keep-alive",

    "Referer": (
        "https://draw.ar-lottery01.com/"
    ),
})

# ============================================================
# GET API DATA
# ============================================================

def get_history():

    try:

        timestamp = int(
            time.time() * 1000
        )

        response = session.get(
            API_URL,
            params={
                "t": timestamp
            },
            timeout=REQUEST_TIMEOUT,
        )

        logger.info(
            "API status: %s",
            response.status_code
        )

        if response.status_code == 403:

            logger.error(
                "WinGo API returned 403 Forbidden."
            )

            return []

        response.raise_for_status()

        data = response.json()

        # ----------------------------------------------------
        # Possible response structures
        # ----------------------------------------------------

        history = []

        if isinstance(data, dict):

            root_data = data.get(
                "data"
            )

            if isinstance(
                root_data,
                dict
            ):

                history = root_data.get(
                    "list",
                    []
                )

            elif isinstance(
                root_data,
                list
            ):

                history = root_data

            if not history:

                history = data.get(
                    "list",
                    []
                )

        if not isinstance(
            history,
            list
        ):

            logger.warning(
                "Unexpected API structure."
            )

            return []

        return history

    except requests.exceptions.Timeout:

        logger.error(
            "WinGo API timeout."
        )

        return []

    except requests.exceptions.RequestException as error:

        logger.error(
            "API request error: %s",
            error
        )

        return []

    except ValueError as error:

        logger.error(
            "Invalid JSON response: %s",
            error
        )

        return []

    except Exception as error:

        logger.exception(
            "Unexpected API error: %s",
            error
        )

        return []


# ============================================================
# EXTRACT ISSUE
# ============================================================

def get_issue(item):

    if not isinstance(
        item,
        dict
    ):
        return None

    possible_keys = [
        "issueNumber",
        "issue",
        "period",
        "issueNo",
        "number",
    ]

    for key in possible_keys:

        value = item.get(key)

        if value is not None:

            value = str(
                value
            ).strip()

            if value:
                return value

    return None


# ============================================================
# EXTRACT NUMBER
# ============================================================

def get_number(item):

    if not isinstance(
        item,
        dict
    ):
        return None

    possible_keys = [
        "number",
        "code",
        "result",
        "resultNumber",
    ]

    for key in possible_keys:

        value = item.get(key)

        if value is None:
            continue

        try:

            text = str(
                value
            )

            digits = [
                char
                for char in text
                if char.isdigit()
            ]

            if not digits:
                continue

            number = int(
                digits[-1]
            )

            if 0 <= number <= 9:
                return number

        except Exception:
            continue

    return None


# ============================================================
# BIG / SMALL
# ============================================================

def big_small(number):

    if number is None:
        return None

    if number >= 5:
        return "BIG"

    return "SMALL"


# ============================================================
# NEXT PERIOD
# ============================================================

def next_period(issue):

    try:

        return str(
            int(str(issue)) + 1
        )

    except Exception:

        return str(
            issue
        )


# ============================================================
# SIGNAL ENGINE
# ============================================================

def generate_signal(history):

    numbers = []

    for item in history[:20]:

        number = get_number(
            item
        )

        if number is not None:
            numbers.append(
                number
            )

    if len(numbers) < 3:

        return {
            "prediction": "WAIT",
            "numbers": [],
            "confidence": 0,
        }

    sizes = [
        big_small(number)
        for number in numbers
    ]

    big_score = 0
    small_score = 0

    # --------------------------------------------------------
    # Weighted recent trend
    # --------------------------------------------------------

    for index, side in enumerate(
        sizes[:10]
    ):

        weight = 10 - index

        if side == "BIG":

            big_score += weight

        elif side == "SMALL":

            small_score += weight

    # --------------------------------------------------------
    # Streak reversal
    # --------------------------------------------------------

    if len(sizes) >= 3:

        if (
            sizes[0]
            == sizes[1]
            == sizes[2]
        ):

            if sizes[0] == "BIG":

                small_score += 8

            else:

                big_score += 8

    # --------------------------------------------------------
    # Zig-zag detection
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

    big_count = sizes.count(
        "BIG"
    )

    small_count = sizes.count(
        "SMALL"
    )

    if big_count < small_count:

        big_score += 3

    elif small_count < big_count:

        small_score += 3

    # --------------------------------------------------------
    # Final prediction
    # --------------------------------------------------------

    if big_score >= small_score:

        prediction = "BIG"

    else:

        prediction = "SMALL"

    # --------------------------------------------------------
    # Number candidates
    # --------------------------------------------------------

    if prediction == "BIG":

        pool = [
            5,
            6,
            7,
            8,
            9,
        ]

    else:

        pool = [
            0,
            1,
            2,
            3,
            4,
        ]

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
        big_score
        + small_score
    )

    if total > 0:

        confidence = round(
            60
            + (
                max(
                    big_score,
                    small_score
                )
                / total
            )
            * 30
        )

    else:

        confidence = 60

    confidence = max(
        50,
        min(
            98,
            confidence
        )
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
# RESULT CHECK
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
        actual_size
        == signal["prediction"]
    ):

        return "WIN"

    return "LOSS"


# ============================================================
# SIGNAL MESSAGE
# ============================================================

def signal_message(
    period,
    signal
):

    numbers = " / ".join(
        str(number)
        for number in signal["numbers"]
    )

    return (
        "🔥⚡ <b>ST WINGO MASTER</b> ⚡🔥\n"
        "\n"
        "🎯 <b>PERIOD</b>\n"
        f"<code>{period}</code>\n"
        "\n"
        "💥 <b>SIGNAL</b>\n"
        f"<b>{signal['prediction']}</b>\n"
        "\n"
        "🎰 <b>NUMBER</b>\n"
        f"<b>{numbers}</b>\n"
        "\n"
        "💯 <b>CONFIDENCE</b>\n"
        f"<b>{signal['confidence']}%</b>\n"
        "\n"
        "⏱ <b>MARKET</b>\n"
        "<b>WINGO 1 MINUTE</b>\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ Prediction only."
    )


# ============================================================
# RESULT MESSAGE
# ============================================================

def result_message(
    period,
    actual,
    result
):

    emoji = {
        "WIN": "✅",
        "LOSS": "❌",
        "JACKPOT": "🎰",
    }.get(
        result,
        "📊"
    )

    return (
        f"{emoji} <b>{result}</b>\n"
        "\n"
        f"🎯 Period: "
        f"<code>{period}</code>\n"
        f"🔢 Result Number: "
        f"<b>{actual}</b>\n"
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
# MAIN ENGINE
# ============================================================

async def engine(
    application
):

    global last_issue
    global active_signal
    global last_result_issue

    logger.info(
        "Signal engine started."
    )

    while True:

        try:

            history = get_history()

            if not history:

                await asyncio.sleep(
                    CHECK_INTERVAL
                )

                continue

            latest = history[0]

            issue = get_issue(
                latest
            )

            actual = get_number(
                latest
            )

            if (
                issue is None
                or actual is None
            ):

                logger.warning(
                    "Latest API item missing issue/number: %s",
                    latest
                )

                await asyncio.sleep(
                    CHECK_INTERVAL
                )

                continue

            # ------------------------------------------------
            # New result detected
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

                stats[result] += 1

                await send_channel(
                    application,
                    result_message(
                        last_issue,
                        actual,
                        result
                    )
                )

                last_result_issue = issue

                logger.info(
                    "Result: %s | Issue: %s | Number: %s",
                    result,
                    issue,
                    actual
                )

            # ------------------------------------------------
            # Generate next signal only once per new issue
            # ------------------------------------------------

            if issue != last_issue:

                signal = generate_signal(
                    history
                )

                if (
                    signal["prediction"]
                    != "WAIT"
                ):

                    period = next_period(
                        issue
                    )

                    active_signal = signal

                    await send_channel(
                        application,
                        signal_message(
                            period,
                            signal
                        )
                    )

                    logger.info(
                        "New signal: %s | Period: %s",
                        signal["prediction"],
                        period
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
# /START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🔥 ST WINGO MASTER\n\n"
        "Bot is online.\n"
        "Market: Wingo 1 Minute\n\n"
        "Use /signal to check the current signal."
    )


# ============================================================
# /SIGNAL
# ============================================================

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

    issue = get_issue(
        latest
    )

    if issue is None:

        await update.message.reply_text(
            "⚠️ Current period unavailable."
        )

        return

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


# ============================================================
# /STATUS
# ============================================================

async def status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    history = get_history()

    if not history:

        await update.message.reply_text(
            "🔴 API unavailable."
        )

        return

    issue = get_issue(
        history[0]
    )

    await update.message.reply_text(
        "🟢 <b>ST WINGO MASTER ONLINE</b>\n\n"
        f"🎯 Current Period: "
        f"<code>{issue}</code>\n"
        "⏱ Market: <b>Wingo 1 Minute</b>\n\n"
        f"✅ WIN: <b>{stats['WIN']}</b>\n"
        f"❌ LOSS: <b>{stats['LOSS']}</b>\n"
        f"🎰 JACKPOT: <b>{stats['JACKPOT']}</b>",
        parse_mode="HTML"
    )


# ============================================================
# POST INIT
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


# ============================================================
# MAIN
# ============================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN environment variable is missing."
        )

    # --------------------------------------------------------
    # Start Render HTTP server
    # --------------------------------------------------------

    health_thread = threading.Thread(
        target=start_health_server,
        daemon=True
    )

    health_thread.start()

    # --------------------------------------------------------
    # Telegram application
    # --------------------------------------------------------

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

    logger.info(
        "API URL: %s",
        API_URL
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()

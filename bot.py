import os
import re
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from config import TELEGRAM_BOT_TOKEN
from extractor import extract_content
from translator import translate_and_extract_vocab, format_telegram_output
from notion_writer import create_notion_page

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

URL_PATTERN = re.compile(r"https?://[^\s]+")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a welcome message on /start."""
    await update.message.reply_text(
        "Bonjour ! Send me any link (article, Substack, X/Twitter, Threads...) "
        "and I'll translate it into standard French with B2-C1 vocabulary notes.\n\n"
        "Chaque paragraphe traduit suivra l'original. Le resultat sera aussi sauvegarde dans Notion."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process any message containing a URL."""
    text = update.message.text

    if not text:
        return

    urls = URL_PATTERN.findall(text)
    if not urls:
        return

    url = urls[0]

    try:
        status_msg = await update.message.reply_text("Extraction du contenu...")
        content = extract_content(url)
        title = content["title"]
        full_text = content["text"]
        para_count = len(content["paragraphs"])

        await status_msg.edit_text(
            f"Contenu extrait : *{title}*\n"
            f"{para_count} paragraphes\n"
            "Traduction en cours avec DeepSeek..."
        )

        result = translate_and_extract_vocab(full_text)

        await status_msg.edit_text(
            f"Traduction terminee\n"
            f"{len(result.get('vocabulary', []))} mots de vocabulaire extraits\n"
            "Creation de la page Notion..."
        )

        notion_url = None
        try:
            notion_url = create_notion_page(title, result)
        except Exception as e:
            logger.error(f"Notion error: {e}")

        await status_msg.delete()

        telegram_output = format_telegram_output(result, title, notion_url)

        if len(telegram_output) > 4000:
            parts = _split_long_message(telegram_output)
            for part in parts:
                await update.message.reply_text(part, parse_mode="Markdown")
        else:
            await update.message.reply_text(telegram_output, parse_mode="Markdown")

        if not notion_url:
            await update.message.reply_text(
                "La sauvegarde Notion a echoue. Verifiez votre configuration Notion."
            )

    except ValueError as e:
        await update.message.reply_text(
            f"Erreur d'extraction : {e}\n\n"
            "Assurez-vous que le lien pointe vers un article accessible."
        )
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        await update.message.reply_text(
            f"Une erreur est survenue : {e}\n\nMerci de reessayer."
        )


def _split_long_message(text: str, limit: int = 4000) -> list[str]:
    parts = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            parts.append(current)
            current = line
        else:
            current += "\n" + line if current else line
    if current:
        parts.append(current)
    return parts


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass


def _start_health_server():
    port = int(os.environ.get("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info(f"Health server on port {port}")
    server.serve_forever()


def run_bot():
    """Start the Telegram bot."""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN.startswith("YOUR_"):
        raise ValueError("TELEGRAM_BOT_TOKEN not configured")

    # Diagnostic: test if we can reach Telegram at all
    _test_telegram_connectivity()

    railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")

    if railway_domain:
        threading.Thread(target=_start_health_server, daemon=True).start()
        logger.info(f"Railway domain: {railway_domain}")

    logger.info("Building Telegram app...")

    try:
        # Use longer timeouts for Railway's network
        app = (
            Application.builder()
            .token(TELEGRAM_BOT_TOKEN)
            .connect_timeout(30.0)
            .read_timeout(60.0)
            .write_timeout(30.0)
            .pool_timeout(10.0)
            .build()
        )
    except Exception as e:
        logger.error(f"Failed to build app: {e}", exc_info=True)
        raise

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Starting polling...")
    app.run_polling(drop_pending_updates=True)


def _test_telegram_connectivity():
    """Quick diagnostic: can we reach api.telegram.org?"""
    import urllib.request
    import json as _json
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN[:12]}.../getMe",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = _json.loads(resp.read())
            if data.get("ok"):
                logger.info(f"Telegram reachable. Bot: {data['result']['username']}")
            else:
                logger.error(f"Telegram API error: {data}")
    except Exception as e:
        logger.error(f"Cannot reach Telegram API: {e}")

import re
import logging
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
        "Chaque paragraphe traduit suivra l'original. Le résultat sera aussi sauvegardé dans Notion."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process any message containing a URL."""
    text = update.message.text

    if not text:
        return

    urls = URL_PATTERN.findall(text)
    if not urls:
        return  # No URL, ignore

    url = urls[0]  # Process the first URL found

    try:
        # Step 1: Extract content
        status_msg = await update.message.reply_text("🔍 Extraction du contenu...")
        content = extract_content(url)
        title = content["title"]
        full_text = content["text"]
        para_count = len(content["paragraphs"])

        await status_msg.edit_text(
            f"✅ Contenu extrait : *{title}*\n"
            f"📊 {para_count} paragraphes\n"
            f"🌐 Traduction en cours avec DeepSeek..."
        )

        # Step 2: Translate & extract vocabulary
        result = translate_and_extract_vocab(full_text)

        await status_msg.edit_text(
            f"✅ Traduction terminée\n"
            f"📚 {len(result.get('vocabulary', []))} mots de vocabulaire extraits\n"
            f"📝 Création de la page Notion..."
        )

        # Step 3: Create Notion page
        notion_url = None
        try:
            notion_url = create_notion_page(title, result)
        except Exception as e:
            logger.error(f"Notion error: {e}")
            # Continue without Notion

        # Step 4: Send result to user
        await status_msg.delete()

        telegram_output = format_telegram_output(result, title, notion_url)

        # Split if too long for Telegram (4096 char limit)
        if len(telegram_output) > 4000:
            parts = _split_long_message(telegram_output)
            for part in parts:
                await update.message.reply_text(part, parse_mode="Markdown")
        else:
            await update.message.reply_text(telegram_output, parse_mode="Markdown")

        if not notion_url:
            await update.message.reply_text(
                "⚠️ La sauvegarde Notion a échoué. Vérifiez votre configuration Notion."
            )

    except ValueError as e:
        await update.message.reply_text(
            f"❌ Erreur d'extraction : {e}\n\n"
            "Assurez-vous que le lien pointe vers un article accessible."
        )
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        await update.message.reply_text(
            f"❌ Une erreur est survenue : {e}\n\nMerci de réessayer."
        )


def _split_long_message(text: str, limit: int = 4000) -> list[str]:
    """Split a long message at paragraph boundaries."""
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


def run_bot():
    """Start the Telegram bot."""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN.startswith("YOUR_"):
        raise ValueError(
            "Telegram bot token not configured. Set TELEGRAM_BOT_TOKEN in .env"
        )

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot is polling...")
    app.run_polling()

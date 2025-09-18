import logging
import os
import re
import asyncio
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, filters
import yt_dlp

load_dotenv()

TOKEN = os.getenv('BOT_TOKEN')

# Enable logging (file + console)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    filename='bot.log',
    filemode='a'
)
logger = logging.getLogger(__name__)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(console_handler)

# Download folder (create if it doesn't exist)
DOWNLOAD_DIR = 'downloads'
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


async def start(update, context):
    """Handle /start command."""
    await update.message.reply_text("Hi! Send me a TikTok video URL")


async def help_command(update, context):
    """Handle /help command."""
    await update.message.reply_text("Just paste a TikTok URL. I'll fetch the video without watermarks. Supports MP4 downloads.")


async def download_tiktok(update, context):
    """Handle TikTok URL messages and download the video."""
    # Log the incoming update for debugging (will appear in Render logs)
    try:
        logger.info("Incoming update: %s", update.to_dict())
    except Exception:
        logger.info("Incoming update (non-serializable) - type: %s", type(update))

    # Ensure we have a message with text
    if not getattr(update, 'message', None) or not getattr(update.message, 'text', None):
        logger.warning("Received update without message.text - ignoring")
        return

    text = update.message.text.strip()

    # Regex to find all TikTok URLs
    url_pattern = r'https://(?:www\.|vt\.)?tiktok\.com/[^\s]+'
    urls = re.findall(url_pattern, text)

    if not urls:
        await update.message.reply_text("Please send a valid TikTok URL.")
        return

    # Try to delete the user's message to keep the chat clean
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except Exception:
        pass

    for url in urls:
        downloading_msg = await update.message.reply_text("Downloading... This might take a moment! ⏳")

        ydl_opts = {
            'outtmpl': f'{DOWNLOAD_DIR}/%(title)s.%(ext)s',
            'format': 'bestvideo+bestaudio/best',
            'noplaylist': True,
            'merge_output_format': 'mp4',
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            },
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    info = ydl.extract_info(url, download=True)
                except Exception as edl:
                    logger.exception("yt-dlp failed to extract or download: %s", url)
                    await update.message.reply_text(f"Failed to download the video: {str(edl)}")
                    await asyncio.sleep(int(os.getenv('DOWNLOAD_DELAY', 2)))
                    continue

                title = info.get('title', 'Downloaded Video')
                uploader = info.get('uploader', 'Unknown')
                filename = ydl.prepare_filename(info).rsplit('.', 1)[0] + '.mp4'

            # Ensure the file exists before checking size or opening
            if not os.path.exists(filename):
                logger.error("Expected downloaded file not found: %s", filename)
                await update.message.reply_text("Download finished but file was not created. Try again or send another URL.")
                await asyncio.sleep(int(os.getenv('DOWNLOAD_DELAY', 2)))
                continue

            file_size = os.path.getsize(filename) / (1024 * 1024)
            if file_size > 50:
                await update.message.reply_text("Video is too large (>50MB) for Telegram. Try another video or ask for compression help!")
                os.remove(filename)
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=downloading_msg.message_id)
                await asyncio.sleep(int(os.getenv('DOWNLOAD_DELAY', 2)))
                continue

            try:
                video_file = open(filename, 'rb')
            except Exception as ofe:
                logger.exception("Failed to open downloaded file: %s", filename)
                await update.message.reply_text("Couldn't open the downloaded file. Try again later.")
                try:
                    os.remove(filename)
                except Exception:
                    pass
                await asyncio.sleep(int(os.getenv('DOWNLOAD_DELAY', 2)))
                continue

            with video_file:
                if uploader != 'Unknown':
                    uploader_link = uploader if uploader.startswith('@') else f'@{uploader}'
                    caption = f"[{uploader}](https://www.tiktok.com/{uploader_link})"
                    parse_mode = 'Markdown'
                else:
                    caption = uploader
                    parse_mode = None

                await context.bot.send_video(
                    chat_id=update.effective_chat.id,
                    video=video_file,
                    caption=caption,
                    parse_mode=parse_mode,
                    supports_streaming=True,
                )

            os.remove(filename)
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=downloading_msg.message_id)
            await asyncio.sleep(int(os.getenv('DOWNLOAD_DELAY', 2)))

        except Exception as e:
            logger.exception(f"Download error for {url}")
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=downloading_msg.message_id)
            except Exception:
                pass

            if "Requested format is not available" in str(e):
                try:
                    with yt_dlp.YoutubeDL({'listformats': True}) as ydl:
                        info = ydl.extract_info(url, download=False)
                        formats = info.get('formats', [])
                        format_list = "\n".join([f"ID: {f['format_id']} - {f.get('ext', 'unknown')} - {f.get('resolution', 'unknown')}" for f in formats])
                        await update.message.reply_text(f"Format error for {url}. Available formats:\n{format_list}\nTry another URL or contact support.")
                except Exception:
                    await update.message.reply_text(f"Couldn't download or list formats for {url}.")
            else:
                await update.message.reply_text(f"Oops! Couldn't download that video ({url}). Error: {str(e)}\nTry another URL?")

            await asyncio.sleep(int(os.getenv('DOWNLOAD_DELAY', 2)))


def build_application():
    """Build and return the Application with handlers registered."""
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download_tiktok))
    # Global error handler to capture exceptions from handlers
    async def _handle_error(update, context):
        try:
            logger.exception("Unhandled exception while processing update: %s", update)
        except Exception:
            logger.exception("Failed while logging an exception")

    app.add_error_handler(_handle_error)
    return app


def main():
    """Start the application using webhook (Render) or polling (local)."""
    app = build_application()

    webhook_url = os.getenv('WEBHOOK_URL')
    port = int(os.getenv('PORT', 5000))

    if webhook_url:
        logger.info(f"Starting with webhook at {webhook_url}/webhook on port {port}")
        # run_webhook will start the internal web server and register webhook
        try:
            # PTB v22 accepts webhook_url; avoid unsupported 'path' kwarg
            app.run_webhook(listen='0.0.0.0', port=port, webhook_url=f"{webhook_url}/webhook")
        except Exception:
            logger.exception("Failed to start webhook server")
            raise
    else:
        logger.info("Starting with polling (no WEBHOOK_URL set)")
        app.run_polling(allowed_updates=['message'])


if __name__ == '__main__':
    main()
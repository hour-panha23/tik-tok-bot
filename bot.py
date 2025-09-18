import logging
import os
import re
import asyncio
from dotenv import load_dotenv
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp

load_dotenv()

TOKEN = os.getenv('BOT_TOKEN')

# Create Flask app
app = Flask(__name__)

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    filename='bot.log',
    filemode='a'
)
logger = logging.getLogger(__name__)

# Download folder (create if it doesn't exist)
DOWNLOAD_DIR = 'downloads'
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

async def start(update, context):
    """Handle /start command."""
    await update.message.reply_text(
        "Hi! Send me a TikTok video URL"
    )

async def help_command(update, context):
    """Handle /help command."""
    await update.message.reply_text(
        "Just paste a TikTok URL. I'll fetch the video without watermarks. Supports MP4 downloads."
    )

async def download_tiktok(update, context):
    """Handle TikTok URL messages and download the video."""
    text = update.message.text.strip()
    
    # Regex to find all TikTok URLs
    url_pattern = r'https://(?:www\.|vt\.)?tiktok\.com/[^\s]+'
    urls = re.findall(url_pattern, text)
    
    if not urls:
        await update.message.reply_text("Please send a valid TikTok URL.")
        return

    # Delete the user's message containing the links
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except Exception:
        pass  # Ignore if deletion fails (e.g., no permission in private chat)

    # Process each URL one by one
    for url in urls:
        downloading_msg = await update.message.reply_text("Downloading... This might take a moment! ⏳")

        ydl_opts = {
            'outtmpl': f'{DOWNLOAD_DIR}/%(title)s.%(ext)s',  # Save to downloads folder
            'format': 'bestvideo+bestaudio/best',  # Try best video+audio, fallback to best available
            'noplaylist': True,  # Download single video only
            'merge_output_format': 'mp4',  # Ensure output is MP4
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            },  # Mimic browser
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Extract info and download
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'Downloaded Video')
                uploader = info.get('uploader', 'Unknown')
                filename = ydl.prepare_filename(info).rsplit('.', 1)[0] + '.mp4'  # Ensure .mp4 extension

            # Check file size (Telegram limit: 50MB)
            file_size = os.path.getsize(filename) / (1024 * 1024)  # Size in MB
            if file_size > 50:
                await update.message.reply_text("Video is too large (>50MB) for Telegram. Try another video or ask for compression help!")
                os.remove(filename)
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=downloading_msg.message_id)
                # Add delay
                await asyncio.sleep(2)
                continue

            # Send the video
            with open(filename, 'rb') as video_file:
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
                    supports_streaming=True
                )

            # Clean up
            os.remove(filename)
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=downloading_msg.message_id)

            # Add delay between downloads to avoid rate limits
            await asyncio.sleep(2)

        except Exception as e:
            logger.error(f"Download error for {url}: {e}")
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=downloading_msg.message_id)
            # If format error, list available formats for debugging
            if "Requested format is not available" in str(e):
                try:
                    with yt_dlp.YoutubeDL({'listformats': True}) as ydl:
                        info = ydl.extract_info(url, download=False)
                        formats = info.get('formats', [])
                        format_list = "\n".join([f"ID: {f['format_id']} - {f.get('ext', 'unknown')} - {f.get('resolution', 'unknown')}" for f in formats])
                        await update.message.reply_text(f"Format error for {url}. Available formats:\n{format_list}\nTry another URL or contact support.")
                except Exception as format_e:
                    await update.message.reply_text(f"Couldn't download or list formats for {url}. Error: {str(format_e)}\nTry another URL?")
async def download_tiktok(update, context):
    """Handle TikTok URL messages and download the video."""
    text = update.message.text.strip()
    
    # Regex to find all TikTok URLs
    url_pattern = r'https://(?:www\.|vt\.)?tiktok\.com/[^\s]+'
    urls = re.findall(url_pattern, text)
    
    if not urls:
        await update.message.reply_text("Please send a valid TikTok URL.")
        return

    # Delete the user's message containing the links
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.message.message_id)
    except Exception:
        pass  # Ignore if deletion fails (e.g., no permission in private chat)

    # Process each URL one by one
    for url in urls:
        downloading_msg = await update.message.reply_text("Downloading... This might take a moment! ⏳")

        ydl_opts = {
            'outtmpl': f'{DOWNLOAD_DIR}/%(title)s.%(ext)s',  # Save to downloads folder
            'format': 'bestvideo+bestaudio/best',  # Try best video+audio, fallback to best available
            'noplaylist': True,  # Download single video only
            'merge_output_format': 'mp4',  # Ensure output is MP4
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            },  # Mimic browser
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Extract info and download
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'Downloaded Video')
                uploader = info.get('uploader', 'Unknown')
                filename = ydl.prepare_filename(info).rsplit('.', 1)[0] + '.mp4'  # Ensure .mp4 extension

            # Check file size (Telegram limit: 50MB)
            file_size = os.path.getsize(filename) / (1024 * 1024)  # Size in MB
            if file_size > 50:
                await update.message.reply_text("Video is too large (>50MB) for Telegram. Try another video or ask for compression help!")
                os.remove(filename)
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=downloading_msg.message_id)
                # Add delay
                await asyncio.sleep(2)
                continue

            # Send the video
            with open(filename, 'rb') as video_file:
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
                    supports_streaming=True
                )

            # Clean up
            os.remove(filename)
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=downloading_msg.message_id)

            # Add delay between downloads to avoid rate limits
            await asyncio.sleep(2)

        except Exception as e:
            logger.error(f"Download error for {url}: {e}")
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=downloading_msg.message_id)
            # If format error, list available formats for debugging
            if "Requested format is not available" in str(e):
                try:
                    with yt_dlp.YoutubeDL({'listformats': True}) as ydl:
                        info = ydl.extract_info(url, download=False)
                        formats = info.get('formats', [])
                        format_list = "\n".join([f"ID: {f['format_id']} - {f.get('ext', 'unknown')} - {f.get('resolution', 'unknown')}" for f in formats])
                        await update.message.reply_text(f"Format error for {url}. Available formats:\n{format_list}\nTry another URL or contact support.")
                except Exception as format_e:
                    await update.message.reply_text(f"Couldn't download or list formats for {url}. Error: {str(format_e)}\nTry another URL?")
            else:
                await update.message.reply_text(f"Oops! Couldn't download that video ({url}). Error: {str(e)}\nTry another URL?")
            
            # Add delay between downloads
            await asyncio.sleep(2)

@app.route('/webhook', methods=['POST'])
async def webhook():
    """Handle incoming webhook updates."""
    logger.info("Received webhook update")
    data = await request.get_json()
    logger.info(f"Update data: {data}")
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    logger.info("Update processed")
    return 'OK'

@app.route('/')
def index():
    """Health check endpoint."""
    return 'Bot is running!'

def main():
    """Start the bot."""
    global application
    # Create the Application
    application = Application.builder().token(TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, download_tiktok))

    # Get port from environment
    port = int(os.getenv('PORT', 5000))
    
    # Set webhook if URL is provided
    webhook_url = os.getenv('WEBHOOK_URL')
    if webhook_url:
        application.bot.set_webhook(url=f"{webhook_url}/webhook")
        print(f"Webhook set to {webhook_url}/webhook")
    
    # Run Flask app
    print(f"Starting Flask app on port {port}")
    app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    main()
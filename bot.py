import logging
import os
import re
import asyncio
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, filters
import yt_dlp

load_dotenv()

TOKEN = os.getenv('BOT_TOKEN')

# Enable logging (file + console) with clearer formatting
log_formatter = logging.Formatter('%(asctime)s | %(levelname)-7s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
file_handler = logging.FileHandler('bot.log', mode='a', encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(log_formatter)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(log_formatter)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)


def _mask_proxy(proxy_url: str) -> str:
    """Mask credentials in proxy URL for safe logging.

    Examples:
      http://user:pass@host:port -> http://host:port
      socks5://host:port -> socks5://host:port
    """
    try:
        if not proxy_url:
            return ''
        from urllib.parse import urlparse, urlunparse
        p = urlparse(proxy_url)
        netloc = p.hostname or ''
        if p.port:
            netloc = f"{netloc}:{p.port}"
        return urlunparse(p._replace(netloc=netloc))
    except Exception:
        return proxy_url


def _classify_download_error(exc: Exception, url: str) -> str:
    """Return a user-friendly message based on the exception text."""
    try:
        s = str(exc).lower()
    except Exception:
        s = ''

    # Deleted / removed
    if any(k in s for k in ('410', '404', 'not found', 'page not found')):
        return f"The video at {url} appears to have been removed or is not available (404/410)."

    # Private or requires login
    if any(k in s for k in ('private', 'login required', 'please login', 'authentication', '403')):
        return f"The video at {url} may be private or requires login. Try providing a cookies file (set COOKIES_FILE) or a valid session via COOKIES."

    # Timed out / network
    if any(k in s for k in ('timed out', 'timeout', 'timedout', 'connection reset')):
        return f"Timed out while downloading {url}. This can be network-related or TikTok may be blocking the request. Try again, or set a working PROXY."

    # Geo / blocked
    if any(k in s for k in ('geo', 'geoblocked', 'forbidden', 'blocked')):
        return f"The video at {url} may be region-restricted or blocked. Try using a PROXY from another region or provide cookies."

    # Rate limiting
    if any(k in s for k in ('429', 'too many requests', 'rate limit')):
        return f"Downloads are being rate-limited by TikTok for {url}. Wait a bit and try again."

    # Fallback: show the short exception text
    short = str(exc)
    if len(short) > 300:
        short = short[:300] + '...'
    return f"Couldn't download {url}. Error: {short}"

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
    # Concise incoming update logging: user_id, chat_id, message_id, text (short)
    try:
        user_id = getattr(update.effective_user, 'id', None)
        chat_id = getattr(update.effective_chat, 'id', None)
        msg_id = getattr(update.message, 'message_id', None)
        text_preview = (update.message.text[:120] + '...') if update.message and update.message.text and len(update.message.text) > 120 else getattr(update.message, 'text', '')
        logger.info("Incoming: user=%s chat=%s msg=%s text=%s", user_id, chat_id, msg_id, text_preview)
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

        # Clean common tracking params from TikTok URLs which sometimes confuse extractors
        def _clean_tiktok_url(u: str) -> str:
            try:
                from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
                parsed = urlparse(u)
                if 'tiktok.com' not in parsed.netloc:
                    return u
                if not parsed.query:
                    return u
                # Drop known tracking params like _t, _r
                qs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k not in {'_t', '_r'}]
                cleaned = parsed._replace(query=urlencode(qs))
                return urlunparse(cleaned)
            except Exception:
                return u

        original_url = url
        url = _clean_tiktok_url(url)

        ydl_opts = {
            'outtmpl': f'{DOWNLOAD_DIR}/%(title)s.%(ext)s',
            'format': 'bestvideo+bestaudio/best',
            'noplaylist': True,
            'merge_output_format': 'mp4',
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Referer': 'https://www.tiktok.com/',
                'Accept-Language': os.getenv('ACCEPT_LANGUAGE', 'en-US,en;q=0.9'),
            },
            'geo_bypass': True,
        }

        # Optional cookie support: prefer COOKIES_FILE (path to cookies.txt), fallback to COOKIES (raw Cookie header)
        cookies_file = os.getenv('COOKIES_FILE')
        raw_cookies = os.getenv('COOKIES')
        if cookies_file:
            # yt-dlp accepts a cookies file in Netscape format via 'cookiefile'
            ydl_opts['cookiefile'] = cookies_file
            logger.info('Using cookies file from COOKIES_FILE')
        elif raw_cookies:
            # If raw cookies provided, pass them as a Cookie header
            ydl_opts.setdefault('http_headers', {})
            ydl_opts['http_headers']['Cookie'] = raw_cookies
            logger.info('Using cookies from COOKIES env var')

        # Optional proxy support
        proxy = os.getenv('PROXY')
        if proxy:
            ydl_opts['proxy'] = proxy
            logger.info('Using PROXY: %s', _mask_proxy(proxy))

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    info = ydl.extract_info(url, download=True)
                except Exception as edl:
                    # First attempt failed; try a second attempt with a mobile UA and stricter headers
                    logger.warning("Initial extraction failed; retrying with mobile headers. URL: %s", url)
                    mobile_headers = {
                        'User-Agent': os.getenv('TIKTOK_MOBILE_UA', 'Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36'),
                        'Referer': 'https://www.tiktok.com/',
                        'Accept-Language': os.getenv('ACCEPT_LANGUAGE', 'en-US,en;q=0.9'),
                    }
                    retry_opts = dict(ydl_opts)
                    retry_headers = dict(ydl_opts.get('http_headers', {}))
                    retry_headers.update(mobile_headers)
                    retry_opts['http_headers'] = retry_headers

                    # Also attempt with more aggressively cleaned URL (strip all query params for www.tiktok.com links)
                    retry_url = url
                    if 'tiktok.com' in url:
                        try:
                            from urllib.parse import urlparse, urlunparse
                            p = urlparse(url)
                            if p.netloc.endswith('tiktok.com') and p.query:
                                retry_url = urlunparse(p._replace(query=''))
                        except Exception:
                            pass

                    try:
                        with yt_dlp.YoutubeDL(retry_opts) as ydl2:
                            info = ydl2.extract_info(retry_url, download=True)
                    except Exception as edl2:
                        logger.exception("yt-dlp failed on both attempts for: %s (original: %s)", url, original_url)
                        user_msg = _classify_download_error(edl2, original_url)
                        await update.message.reply_text(user_msg)
                        await asyncio.sleep(int(os.getenv('DOWNLOAD_DELAY', 2)))
                        continue

                title = info.get('title', 'Downloaded Video')
                uploader = info.get('uploader', 'Unknown')
                filename = ydl.prepare_filename(info).rsplit('.', 1)[0] + '.mp4'

            # Ensure the file exists before checking size or opening
            if not os.path.exists(filename):
                logger.error("Expected downloaded file not found: %s", filename)
                await update.message.reply_text(f"Download finished but file was not created for {original_url}. Try again or send another URL.")
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
                user_msg = _classify_download_error(ofe, original_url)
                await update.message.reply_text(user_msg)
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
        # Log a concise update summary and the full traceback for diagnostics
        try:
            summary = None
            try:
                user_id = getattr(update.effective_user, 'id', None)
                chat_id = getattr(update.effective_chat, 'id', None)
                msg_id = getattr(update.message, 'message_id', None)
                text_preview = (update.message.text[:120] + '...') if update.message and update.message.text and len(update.message.text) > 120 else getattr(update.message, 'text', '')
                summary = f'user={user_id} chat={chat_id} msg={msg_id} text={text_preview}'
            except Exception:
                try:
                    summary = str(update)
                except Exception:
                    summary = '<unserializable update>'

            logger.error('Unhandled exception while processing update: %s', summary)
            # Log traceback / context.error if available, otherwise use sys.exc_info()
            import traceback, sys
            err = getattr(context, 'error', None)
            if err is not None:
                tb = ''.join(traceback.format_exception(None, err, err.__traceback__))
            else:
                exc_info = sys.exc_info()
                if exc_info[0] is not None:
                    tb = ''.join(traceback.format_exception(*exc_info))
                else:
                    tb = 'No traceback available in context.error or sys.exc_info()'

            logger.error('Traceback:\n%s', tb)
        except Exception:
            logger.exception('Failed while logging an exception')

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
            # Use the provided WEBHOOK_URL exactly — don't append '/webhook' here.
            # This makes webhook path alignment explicit: set WEBHOOK_URL to the exact URL
            # Telegram should POST to (e.g. 'https://.../webhook' or 'https://...').
            app.run_webhook(listen='0.0.0.0', port=port, webhook_url=webhook_url)
        except Exception:
            logger.exception("Failed to start webhook server")
            raise
    else:
        logger.info("Starting with polling (no WEBHOOK_URL set)")
        app.run_polling(allowed_updates=['message'])


if __name__ == '__main__':
    main()

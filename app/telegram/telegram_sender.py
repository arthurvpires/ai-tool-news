import logging
import re
import os
import requests
import tempfile
import yt_dlp
from typing import Dict, Any
from telegram import Bot, InputMediaPhoto
from app.config import settings

logger = logging.getLogger(__name__)


class TelegramSender:
    def __init__(self):
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID
        self.bot = Bot(token=self.token) if (self.token and self.token != "your_bot_token") else None

    def build_message(self, content: Dict[str, Any], analysis: Dict[str, Any]) -> str:
        """Builds the MarkdownV2 formatted message according to the plan."""

        # Escape markdown v2 characters: _ * [ ] ( ) ~ ` > # + - = | { } . !
        def escape_md(text: str) -> str:
            chars = ["_", "*", "[", "]", "(", ")", "~", "`", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"]
            for c in chars:
                text = str(text).replace(c, f"\\{c}")
            return text

        source_escaped = escape_md(content.get("company", content.get("source", "Unknown")))

        # Truncate text if it's too long (Telegram limit is 4096 for text, 1024 for captions)
        original_text = content.get("text", "")

        # Aggressive whitespace cleanup
        original_text = re.sub(r"[ \t]+", " ", original_text)
        original_text = re.sub(r"\n\s*\n", "\n\n", original_text)
        original_text = re.sub(r"\n{3,}", "\n\n", original_text)
        original_text = original_text.strip()

        if len(original_text) > 400:
            original_text = original_text[:400] + "..."

        original_text_escaped = escape_md(original_text)
        url_escaped = escape_md(content.get("url", ""))

        msg = f"🚨 *{source_escaped}*\n\n{original_text_escaped}\n\n[See in X]({url_escaped})"
        return msg

    async def send_update(self, content: Dict[str, Any], analysis: Dict[str, Any]):
        if not self.bot:
            logger.warning(
                f"No TELEGRAM_BOT_TOKEN found. Sending skipped. Would have sent: {content.get('title', content.get('id'))}"
            )
            return

        message_text = self.build_message(content, analysis)
        images = content.get("images", [])
        video = content.get("video")

        # Configuration for stability
        MAX_RETRIES = 3
        RETRY_DELAY = 5
        # Significantly increased timeouts for reliability with media
        MEDIA_TIMEOUTS = {"read_timeout": 300, "write_timeout": 300, "connect_timeout": 60, "pool_timeout": 60}

        # Initialize bot if needed (v20+ requirement)
        try:
            async with self.bot:
                for attempt in range(MAX_RETRIES):
                    try:
                        if video:
                            download_url = content.get("url", video)
                            logger.info(f"(Attempt {attempt + 1}/{MAX_RETRIES}) Procuring video from {download_url}...")

                            with tempfile.TemporaryDirectory() as tmp_dir:
                                ydl_opts = {
                                    "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                                    "outtmpl": os.path.join(tmp_dir, "video.%(ext)s"),
                                    "quiet": True,
                                    "no_warnings": True,
                                }

                                try:
                                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                        info = ydl.extract_info(download_url, download=True)
                                        tmp_path = ydl.prepare_filename(info)

                                    logger.info(f"Uploading video file to Telegram ({os.path.getsize(tmp_path)} bytes)")
                                    with open(tmp_path, "rb") as video_file:
                                        await self.bot.send_video(
                                            chat_id=self.chat_id,
                                            video=video_file,
                                            caption=message_text,
                                            parse_mode="MarkdownV2",
                                            **MEDIA_TIMEOUTS,
                                        )
                                except Exception as yt_err:
                                    logger.error(f"yt-dlp download/upload failed: {yt_err}")
                                    if video and video.startswith("http"):
                                        logger.info(f"Retrying direct download fallback for {video}")
                                        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
                                            resp = requests.get(video, stream=True, timeout=30)
                                            resp.raise_for_status()
                                            for chunk in resp.iter_content(chunk_size=8192):
                                                tmp.write(chunk)
                                            tmp_path = tmp.name
                                        try:
                                            with open(tmp_path, "rb") as vf:
                                                await self.bot.send_video(
                                                    chat_id=self.chat_id,
                                                    video=vf,
                                                    caption=message_text,
                                                    parse_mode="MarkdownV2",
                                                    **MEDIA_TIMEOUTS,
                                                )
                                        finally:
                                            if os.path.exists(tmp_path):
                                                os.remove(tmp_path)
                                    else:
                                        raise yt_err
                        elif len(images) == 1:
                            logger.info(
                                f"(Attempt {attempt + 1}/{MAX_RETRIES}) Sending single photo for {content.get('id')}"
                            )
                            await self.bot.send_photo(
                                chat_id=self.chat_id,
                                photo=images[0],
                                caption=message_text,
                                parse_mode="MarkdownV2",
                                **MEDIA_TIMEOUTS,
                            )
                        elif len(images) > 1:
                            logger.info(
                                f"(Attempt {attempt + 1}/{MAX_RETRIES}) Sending media group ({len(images)} photos) for {content.get('id')}"
                            )
                            media_group = []
                            for idx, img_url in enumerate(images[:10]):
                                if idx == 0:
                                    media_group.append(
                                        InputMediaPhoto(img_url, caption=message_text, parse_mode="MarkdownV2")
                                    )
                                else:
                                    media_group.append(InputMediaPhoto(img_url))
                            await self.bot.send_media_group(chat_id=self.chat_id, media=media_group, **MEDIA_TIMEOUTS)
                        else:
                            logger.info(
                                f"(Attempt {attempt + 1}/{MAX_RETRIES}) Sending text-only for {content.get('id')}"
                            )
                            await self.bot.send_message(
                                chat_id=self.chat_id,
                                text=message_text,
                                parse_mode="MarkdownV2",
                                disable_web_page_preview=False,
                                **MEDIA_TIMEOUTS,
                            )

                        logger.info(f"Successfully sent update for {content.get('id')}")
                        return  # Success!

                    except Exception as e:
                        logger.error(f"Attempt {attempt + 1} failed to send to Telegram: {e}")
                        if attempt < MAX_RETRIES - 1:
                            import asyncio

                            await asyncio.sleep(RETRY_DELAY)
                        else:
                            # Final fallback to plain text if everything failed
                            try:
                                logger.info("Ultimate fallback: Sending plain text notification")
                                await self.bot.send_message(
                                    chat_id=self.chat_id,
                                    text=f"🚨 AI News Update!\n\nSource: {content.get('company')}\nLink: {content.get('url')}",
                                    write_timeout=30,
                                )
                                return  # Succeded at least with plain text
                            except Exception as e2:
                                logger.error(f"Final fallback failed: {e2}")
                                raise e2  # Re-raise to prevent marking as sent in DB
        except Exception as bot_err:
            logger.error(f"Telegram Bot Session Error: {bot_err}")
            raise bot_err

    async def send_digest(self, text: str):
        """Send a curated digest as a single Markdown message."""
        if not self.bot:
            logger.warning("No TELEGRAM_BOT_TOKEN found. Digest send skipped.")
            logger.debug(f"Digest content:\n{text}")
            return

        MAX_RETRIES = 3
        RETRY_DELAY = 5

        try:
            async with self.bot:
                for attempt in range(MAX_RETRIES):
                    try:
                        await self.bot.send_message(
                            chat_id=self.chat_id,
                            text=text,
                            parse_mode="Markdown",
                            disable_web_page_preview=True,
                            read_timeout=60,
                            write_timeout=60,
                            connect_timeout=30,
                        )
                        logger.info("Digest message sent successfully.")
                        return
                    except Exception as e:
                        logger.error(f"Digest send attempt {attempt + 1} failed: {e}")
                        if attempt < MAX_RETRIES - 1:
                            import asyncio
                            await asyncio.sleep(RETRY_DELAY)
                        else:
                            raise
        except Exception as bot_err:
            logger.error(f"Telegram Bot Session Error (digest): {bot_err}")
            raise bot_err

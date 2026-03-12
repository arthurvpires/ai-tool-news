import logging
import re
import os
import requests
import tempfile
import yt_dlp
from typing import Dict, Any, List, Optional
from telegram import Bot, InputMediaPhoto, InputMediaVideo
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
            chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
            for c in chars:
                text = str(text).replace(c, f"\\{c}")
            return text
            
        source_escaped = escape_md(content.get('company', content.get('source', 'Unknown')))
        
        # Truncate text if it's too long (Telegram limit is 4096 for text, 1024 for captions)
        original_text = content.get('text', '')
        
        # Aggressive whitespace cleanup
        original_text = re.sub(r'[ \t]+', ' ', original_text)
        original_text = re.sub(r'\n\s*\n', '\n\n', original_text)
        original_text = re.sub(r'\n{3,}', '\n\n', original_text)
        original_text = original_text.strip()

        if len(original_text) > 400:
            original_text = original_text[:400] + "..."
            
        original_text_escaped = escape_md(original_text)
        url_escaped = escape_md(content.get('url', ''))

        msg = (
            f"🚨 *{source_escaped}*\n\n"
            f"{original_text_escaped}\n\n"
            f"[Original source]({url_escaped})"
        )
        return msg

    async def send_update(self, content: Dict[str, Any], analysis: Dict[str, Any]):
        if not self.bot:
            logger.warning(f"No TELEGRAM_BOT_TOKEN found. Sending skipped. Would have sent: {content.get('title', content.get('id'))}")
            return

        message_text = self.build_message(content, analysis)
        images = content.get("images", [])
        video = content.get("video")

        try:
            if video:
                # Use tweet URL if available for better yt-dlp extraction, fallback to video URL
                download_url = content.get('url', video)
                logger.info(f"Downloading video using yt-dlp from {download_url}...")
                
                with tempfile.TemporaryDirectory() as tmp_dir:
                    ydl_opts = {
                        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                        'outtmpl': os.path.join(tmp_dir, 'video.%(ext)s'),
                        'quiet': True,
                        'no_warnings': True,
                    }
                    
                    try:
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            info = ydl.extract_info(download_url, download=True)
                            tmp_path = ydl.prepare_filename(info)
                            
                        logger.info(f"Uploading video file to Telegram: {tmp_path}")
                        with open(tmp_path, 'rb') as video_file:
                            await self.bot.send_video(
                                chat_id=self.chat_id, 
                                video=video_file,
                                caption=message_text,
                                parse_mode="MarkdownV2",
                                read_timeout=120,
                                write_timeout=120,
                                connect_timeout=60
                            )
                    except Exception as yt_err:
                        logger.error(f"yt-dlp download/upload failed: {yt_err}")
                        # Fallback to direct download if yt-dlp failed but we have a direct URL
                        if video and video.startswith("http"):
                            logger.info(f"Retrying direct download fallback for {video}")
                            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
                                resp = requests.get(video, stream=True, timeout=30)
                                resp.raise_for_status()
                                for chunk in resp.iter_content(chunk_size=8192):
                                    tmp.write(chunk)
                                tmp_path = tmp.name
                            try:
                                with open(tmp_path, 'rb') as vf:
                                    await self.bot.send_video(
                                        chat_id=self.chat_id, video=vf, 
                                        caption=message_text, parse_mode="MarkdownV2"
                                    )
                            finally:
                                if os.path.exists(tmp_path): os.remove(tmp_path)
                        else:
                            raise yt_err
            elif len(images) == 1:
                logger.info(f"Sending single photo to Telegram for {content.get('id')}")
                await self.bot.send_photo(
                    chat_id=self.chat_id,
                    photo=images[0],
                    caption=message_text,
                    parse_mode="MarkdownV2",
                    read_timeout=60,
                    write_timeout=60,
                    connect_timeout=60
                )
            elif len(images) > 1:
                logger.info(f"Sending media group ({len(images)} photos) to Telegram for {content.get('id')}")
                # Send MediaGroup for multiple images
                media_group = []
                for idx, img_url in enumerate(images[:10]): # Max 10 per group
                    if idx == 0:
                        media_group.append(InputMediaPhoto(img_url, caption=message_text, parse_mode="MarkdownV2"))
                    else:
                        media_group.append(InputMediaPhoto(img_url))
                await self.bot.send_media_group(
                    chat_id=self.chat_id, 
                    media=media_group,
                    read_timeout=60,
                    write_timeout=60,
                    connect_timeout=60
                )
            else:
                logger.info(f"Sending text-only message to Telegram for {content.get('id')}")
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=message_text,
                    parse_mode="MarkdownV2",
                    disable_web_page_preview=False,
                    read_timeout=60,
                    write_timeout=60,
                    connect_timeout=60
                )
            logger.info(f"Successfully sent update to Telegram for {content.get('id')}")
        except Exception as e:
            logger.error(f"Failed to send update to Telegram: {e}")
            # Fallback to plain text message if media sending fails or Markdown issue occurs
            try:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=f"🚨 AI News Update!\n\nSource: {content.get('company')}\nLink: {content.get('url')}",
                    read_timeout=30
                )
            except Exception as e2:
                logger.error(f"Fallback send failed: {e2}")


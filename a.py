import asyncio
import hashlib
import logging
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
import aiohttp

# ---- CONFIG ----
API_ID = 1234567          # from my.telegram.org
API_HASH = "your_api_hash_here"
SESSION_NAME = "meme_bridge"

CHANNELS = [
    "meme_channel_username_1",   # no @ symbol needed, or use numeric channel ID
    "meme_channel_username_2",
]

N8N_WEBHOOK_URL = "https://your-n8n-instance.com/webhook/telegram-memes"
N8N_WEBHOOK_SECRET = "choose-a-long-random-string-here"  # shared secret for basic auth

DOWNLOAD_DIR = "./downloads"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bridge.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)


def get_file_hash(filepath):
    """MD5 hash of the file for dedup fallback on n8n side."""
    hasher = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


async def send_to_n8n(session, payload, file_path=None):
    """POST metadata + optionally the binary file to n8n webhook, with retries."""
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            headers = {"X-Webhook-Secret": N8N_WEBHOOK_SECRET}

            if file_path:
                data = aiohttp.FormData()
                for k, v in payload.items():
                    data.add_field(k, str(v))
                data.add_field(
                    "file",
                    open(file_path, "rb"),
                    filename=file_path.split("/")[-1],
                    content_type="image/jpeg"
                )
                async with session.post(N8N_WEBHOOK_URL, data=data, headers=headers, timeout=60) as resp:
                    if resp.status == 200:
                        logger.info(f"Sent to n8n successfully: {payload.get('message_id')}")
                        return True
                    else:
                        body = await resp.text()
                        logger.warning(f"n8n responded {resp.status}: {body}")
            else:
                async with session.post(N8N_WEBHOOK_URL, json=payload, headers=headers, timeout=30) as resp:
                    if resp.status == 200:
                        return True
                    logger.warning(f"n8n responded {resp.status} (no file)")

        except Exception as e:
            logger.error(f"Attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                await asyncio.sleep(2 ** attempt)  # exponential backoff: 2s, 4s, 8s

    logger.error(f"Failed to send message {payload.get('message_id')} after {max_retries} attempts")
    return False


@client.on(events.NewMessage(chats=CHANNELS))
async def handler(event):
    message = event.message

    # Only process messages with actual media (skip text-only posts)
    if not message.media:
        logger.info(f"Skipping text-only message {message.id} from {event.chat.username}")
        return

    is_photo = isinstance(message.media, MessageMediaPhoto)
    is_video = isinstance(message.media, MessageMediaDocument) and message.video

    if not (is_photo or is_video):
        logger.info(f"Skipping non-image/video media message {message.id}")
        return

    try:
        import os
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        file_path = await message.download_media(file=DOWNLOAD_DIR + "/")

        if not file_path:
            logger.warning(f"Download returned nothing for message {message.id}")
            return

        file_hash = get_file_hash(file_path)

        payload = {
            "message_id": message.id,
            "channel": event.chat.username or str(event.chat.id),
            "channel_title": event.chat.title,
            "caption": message.text or "",
            "date": message.date.isoformat(),
            "media_type": "video" if is_video else "photo",
            "file_hash": file_hash,
            "file_unique_id": str(message.media.photo.id) if is_photo else str(message.media.document.id),
        }

        async with aiohttp.ClientSession() as session:
            success = await send_to_n8n(session, payload, file_path=file_path)

        # cleanup regardless of outcome, to avoid disk fill-up over time
        try:
            os.remove(file_path)
        except Exception:
            pass

        if success:
            logger.info(f"Processed message {message.id} from {payload['channel']}")
        else:
            logger.error(f"FAILED (after retries) message {message.id} from {payload['channel']} — check bridge.log")

    except Exception as e:
        logger.error(f"Unhandled error processing message {message.id}: {e}", exc_info=True)


async def main():
    await client.start()
    logger.info("Telethon bridge started. Listening for new posts on: " + ", ".join(CHANNELS))
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
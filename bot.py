import asyncio
import logging
import os
import shlex
import time
import json
from collections import defaultdict
from typing import Dict, Any, List

import ffmpeg
import anitopy
from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import Message

# --- Constants ---
BASE_TEMP_DIR = "/tmp/muxer_bot_temp"

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("mux_bot.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# --- Load Configuration ---
try:
    with open("config.json", 'r') as f:
        CONFIG = json.load(f)
except FileNotFoundError:
    log.critical("config.json not found! Please create it.")
    exit(1)
except json.JSONDecodeError:
    log.critical("Invalid JSON in config.json! Please check the file.")
    exit(1)

# --- User State Tracking ---
user_data: Dict[int, Dict[str, Any]] = defaultdict(lambda: {
    "video_path": None,
    "video_filename": None,
    "audio": None,
    "subtitles": [],
    "thumbnail": None,
    "metadata": {}
})

# --- Initialize Pyrogram Client ---
if not os.path.isdir(BASE_TEMP_DIR):
    os.makedirs(BASE_TEMP_DIR)

app = Client(
    "MuxerBot",
    api_id=CONFIG["api_id"],
    api_hash=CONFIG["api_hash"],
    bot_token=CONFIG["bot_token"]
)


# --- Helper Functions ---

async def progress(current, total, message: Message, start_time: float, action: str):
    now = time.time()
    if (now - getattr(message, 'last_edit_time', 0)) < 1: return
    message.last_edit_time = now
    elapsed_time = now - start_time
    speed = current / elapsed_time if elapsed_time > 0 else 0
    percentage = current * 100 / total
    progress_bar = "█" * int(percentage / 10) + "░" * (10 - int(percentage / 10))
    try:
        await message.edit_text(
            f"**{action}**\n"
            f"[{progress_bar}] {percentage:.1f}%\n\n"
            f"**Done:** `{current / (1024*1024):.2f} MB` of `{total / (1024*1024):.2f} MB`\n"
            f"**Speed:** `{speed / (1024*1024):.2f} MB/s`"
        )
    except (FloodWait, Exception): pass

def cleanup_user_data(user_id: int):
    if user_id in user_data:
        user_dir = os.path.join(BASE_TEMP_DIR, str(user_id))
        if os.path.isdir(user_dir):
            try:
                for item in os.listdir(user_dir):
                    item_path = os.path.join(user_dir, item)
                    os.remove(item_path)
                os.rmdir(user_dir)
                log.info(f"Cleaned up temporary directory for user {user_id}")
            except OSError as e:
                log.error(f"Error cleaning up directory {user_dir}: {e}")
        user_data.pop(user_id, None)

async def download_file(message: Message, status_message: Message) -> str | None:
    user_id = message.from_user.id
    # Create a dedicated temp folder for each user to prevent file conflicts
    user_temp_dir = os.path.join(BASE_TEMP_DIR, str(user_id))
    os.makedirs(user_temp_dir, exist_ok=True)

    media = message.video or message.audio or message.document or message.photo
    if not media: return None

    # FIX: Use the original filename provided by Telegram
    original_filename = getattr(media, 'file_name', f'{user_id}_{message.id}')
    file_path = os.path.join(user_temp_dir, original_filename)
    
    start_time = time.time()
    try:
        await status_message.edit_text("📥 Starting download...")
        await message.download(
            file_name=file_path,
            progress=progress,
            progress_args=(status_message, start_time, "Downloading")
        )
        await status_message.edit_text("✅ Download complete!")
        return file_path
    except Exception as e:
        log.error(f"Error downloading for user {user_id}: {e}")
        await status_message.edit_text(f"❌ Download failed: {str(e)}")
        if os.path.exists(file_path): os.remove(file_path)
        return None

async def generate_thumbnail(video_path: str, user_id: int) -> str | None:
    thumb_path = os.path.join(BASE_TEMP_DIR, str(user_id), f"thumb_{user_id}.jpg")
    try:
        probe = ffmpeg.probe(video_path)
        duration = float(probe['format']['duration'])
        seek_time = duration * 0.1
        (
            ffmpeg.input(video_path, ss=seek_time)
            .filter('scale', 320, -1).output(thumb_path, vframes=1)
            .overwrite_output().run(capture_stdout=True, capture_stderr=True)
        )
        return thumb_path
    except Exception as e:
        log.error(f"Failed to generate thumbnail: {e}")
        return None

async def run_ffmpeg_mux(user_id: int) -> tuple[bool, str]:
    user = user_data[user_id]
    user_dir = os.path.join(BASE_TEMP_DIR, str(user_id))
    output_path = os.path.join(user_dir, user["video_filename"]) # FIX: Use original filename

    try:
        args_list = ["ffmpeg", "-i", user["video_path"]]
        if user["audio"]: args_list.extend(["-i", user["audio"]])
        for sub_path in user["subtitles"]: args_list.extend(["-i", sub_path])

        input_map = ["-map", "0:v?", "-map", "0:a?", "-map", "0:s?", "-map", "0:d?", "-map", "0:t?"]
        probe = ffmpeg.probe(user['video_path'])
        audio_streams_in_video = len([s for s in probe['streams'] if s.get('codec_type') == 'audio'])
        stream_index = 1
        
        if user["audio"]:
            new_audio_map_index = audio_streams_in_video
            input_map.extend(["-map", f"{stream_index}:a"])
            metadata = user["metadata"]
            # Apply metadata to the NEW audio stream only. Its final index is `new_audio_map_index`.
            if metadata.get("lang"): input_map.extend([f"-metadata:s:a:{new_audio_map_index}", f"language={metadata['lang']}"])
            if metadata.get("title"): input_map.extend([f"-metadata:s:a:{new_audio_map_index}", f"title={metadata['title']}"])
            input_map.extend([f"-disposition:a:{new_audio_map_index}", "default"])
            stream_index += 1
            
        for i, _ in enumerate(user["subtitles"]): input_map.extend(["-map", f"{stream_index + i}:s"])

        args_list.extend(input_map)
        args_list.extend(["-c", "copy", "-map_chapters", "0", "-y", output_path])

        log.info(f"Muxing for user {user_id} with command: {' '.join(shlex.quote(str(arg)) for arg in args_list)}")
        
        process = await asyncio.create_subprocess_exec(*args_list, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=3600)

        if process.returncode != 0:
            log.error(f"FFmpeg failed: {stderr.decode().strip()}")
            return False, ""
        return True, output_path
    except asyncio.TimeoutError:
        log.error(f"FFmpeg timed out for user {user_id}")
        if 'process' in locals() and process.returncode is None: process.terminate(); await process.wait()
        return False, ""
    except Exception as e:
        log.error(f"Unexpected muxing error for user {user_id}: {e}")
        return False, ""

# --- Pyrogram Handlers ---

@app.on_message(filters.command("start"))
async def start_handler(_, message: Message):
    cleanup_user_data(message.from_user.id)
    await message.reply_text(
        "**Welcome to the Professional Muxer Bot!** ✨\n\n"
        "**Workflow:**\n"
        "1. Send your video file.\n"
        "2. Send an audio file, subtitles (`.srt`/`.ass`), and a custom thumbnail (as photo).\n"
        "3. *(Optional)* Use `/metadata` to set details for the **new** audio track.\n"
        "4. Use `/mux` when you have sent all files.\n\n"
        "Use `/cancel` to reset at any time.",
        quote=True
    )

@app.on_message(filters.command("cancel"))
async def cancel_handler(_, message: Message):
    cleanup_user_data(message.from_user.id)
    await message.reply_text("❌ Operation cancelled and all temporary files have been deleted.", quote=True)
    
@app.on_message(filters.command("metadata"))
async def metadata_handler(_, message: Message):
    user_id = message.from_user.id
    if not user_data[user_id]["video_path"]:
        return await message.reply_text("Please send the video file first.", quote=True)
    try:
        args_text = message.text.split(maxsplit=1)[1]
        args = shlex.split(args_text)
        metadata = {}
        for arg in args:
            key, value = arg.split('=', 1)
            if key.lower() in ["lang", "language"]: metadata["lang"] = value.lower()
            elif key.lower() in ["title", "name"]: metadata["title"] = value
        if not metadata: raise ValueError("No valid arguments.")
        user_data[user_id]["metadata"] = metadata
        await message.reply_text(f"✅ Metadata will be applied to the next audio track:\n`{metadata}`", quote=True)
    except (ValueError, IndexError):
        await message.reply_text("Invalid format. Use `/metadata lang=eng title=\"My Audio\"`.", quote=True)
        
@app.on_message(filters.command("mux"))
async def mux_handler(_, message: Message):
    user_id = message.from_user.id
    user = user_data[user_id]
    if not user.get("video_path"):
        return await message.reply_text("You need to send a video file first!", quote=True)
    
    status = await message.reply_text("Muxing process started...", quote=True)
    output_filename = user["video_filename"]

    # Thumbnail processing
    thumbnail_path = user.get("thumbnail")
    if not thumbnail_path:
        await status.edit_text("🖼️ No custom thumbnail found. Generating from video...")
        thumbnail_path = await generate_thumbnail(user["video_path"], user_id)

    await status.edit_text("🔄 **Muxing files...** This may take a moment.")
    mux_success, output_path = await run_ffmpeg_mux(user_id)

    if not mux_success:
        await status.edit_text("❌ Muxing failed. Check logs for details.")
        cleanup_user_data(user_id)
        return
    
    await status.edit_text("📤 Uploading final file...")
    start_time = time.time()
    try:
        await message.reply_document(
            document=output_path, thumb=thumbnail_path, file_name=output_filename,
            caption="✅ Muxing complete!", progress=progress, progress_args=(status, start_time, "Uploading")
        )
        await status.delete()
    except Exception as e:
        log.error(f"Upload failed for user {user_id}: {e}")
        await status.edit_text(f"❌ Upload failed: {str(e)}")
        
    cleanup_user_data(user_id)

@app.on_message(filters.media)
async def file_handler(_, message: Message):
    user_id = message.from_user.id
    
    # Identify the type of media more robustly
    media_type = ""
    file_name = ""
    media = message.video or message.audio or message.document or message.photo
    if not media: return # Should not happen with media filter
    
    media_mime = getattr(media, "mime_type", "")
    file_name = getattr(media, "file_name", "").lower()
    
    if message.video or "video" in media_mime: media_type = "video"
    elif message.audio or "audio" in media_mime: media_type = "audio"
    elif message.photo or "image" in media_mime: media_type = "thumbnail"
    elif file_name.endswith(('.srt', '.ass')): media_type = "subtitle"
    
    if not media_type:
        await message.reply_text("❓ Unrecognized file type.", quote=True)
        return

    # Check if a video is already present
    if media_type == "video" and user_data[user_id].get("video_path"):
        return await message.reply_text("You have already sent a video. Use `/cancel` to start over.", quote=True)
    
    status = await message.reply_text("File detected. Processing...", quote=True)
    path = await download_file(message, status)
    if not path: return

    # Assign path to correct user_data field
    if media_type == "video":
        user_data[user_id]["video_path"] = path
        user_data[user_id]["video_filename"] = file_name # FIX: Save original filename
        await status.edit_text("✅ Video added.")
    elif media_type == "audio":
        user_data[user_id]["audio"] = path
        await status.edit_text("✅ Audio track added.")
    elif media_type == "subtitle":
        user_data[user_id]["subtitles"].append(path)
        await status.edit_text(f"✅ Subtitle #{len(user_data[user_id]['subtitles'])} added.")
    elif media_type == "thumbnail":
        user_data[user_id]["thumbnail"] = path
        await status.edit_text("✅ Custom thumbnail added.")


if __name__ == "__main__":
    log.info("Bot is starting...")
    app.run()
    log.info("Bot has stopped.")
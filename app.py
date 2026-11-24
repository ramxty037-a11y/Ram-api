import os
import re
import uuid
import shutil
import tempfile
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import yt_dlp

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def clean_filename(title: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", title).strip()[:60] or "media"

@app.get("/")
def home():
    return {"status": "online", "message": "Video & Audio Downloader API Ready"}

@app.get("/info")
def get_info(url: str = Query(..., description="YouTube, Instagram, or Facebook URL")):
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = info.get("formats", [])
        available_heights = set()
        for f in formats:
            h = f.get("height")
            if h and f.get("vcodec") != "none":
                available_heights.add(h)

        target_qualities = [360, 480, 720, 1080, 1440, 2160]
        video_buttons = []
        for q in target_qualities:
            if any(h >= q for h in available_heights) or not available_heights:
                label = f"{q}p"
                if q == 1440:
                    label = "1440p (2K)"
                elif q == 2160:
                    label = "2160p (4K)"
                video_buttons.append({"quality": str(q), "label": label, "type": "mp4"})

        audio_buttons = [
            {"quality": "mp3", "label": "MP3 Audio", "type": "mp3"},
            {"quality": "m4a", "label": "M4A (AAC) Audio", "type": "m4a"},
        ]

        return {
            "title": info.get("title", "Video"),
            "thumbnail": info.get("thumbnail", ""),
            "duration": info.get("duration", 0),
            "video_formats": video_buttons,
            "audio_formats": audio_buttons,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/download")
def download_media(
    background_tasks: BackgroundTasks,
    url: str = Query(...),
    quality: str = Query("720", description="360, 480, 720, 1080, 1440, 2160, mp3, or m4a"),
):
    temp_dir = tempfile.mkdtemp(prefix="dl_")
    file_id = str(uuid.uuid4())[:8]
    output_template = os.path.join(temp_dir, f"{file_id}.%(ext)s")

    try:
        if quality in ["mp3", "m4a"]:
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": output_template,
                "quiet": True,
                "no_warnings": True,
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": quality,
                        "preferredquality": "192",
                    }
                ],
            }
            media_type = "audio/mpeg" if quality == "mp3" else "audio/mp4"
            ext = quality
        else:
            height = int(quality)
            ydl_opts = {
                "format": f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={height}]+bestaudio/best",
                "outtmpl": output_template,
                "merge_output_format": "mp4",
                "quiet": True,
                "no_warnings": True,
                "postprocessor_args": {
                    "merger": ["-c:v", "copy", "-c:a", "aac"]
                },
            }
            media_type = "video/mp4"
            ext = "mp4"

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = clean_filename(info.get("title", "video"))

        final_file = None
        for fname in os.listdir(temp_dir):
            if fname.startswith(file_id):
                final_file = os.path.join(temp_dir, fname)
                break

        if not final_file or not os.path.exists(final_file):
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise HTTPException(status_code=500, detail="File merge failed")

        background_tasks.add_task(shutil.rmtree, temp_dir, True)
        download_name = f"{title}_{quality}.{ext}"

        return FileResponse(
            path=final_file,
            media_type=media_type,
            filename=download_name,
        )
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(e))

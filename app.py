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

def get_base_ydl_opts() -> dict:
    opts = {
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'js_runtimes': {'node': {}},
        'extractor_args': {
            'youtube': {
                'player_client': ['mweb', 'tv', 'web'],
            }
        },
    }

    cookie_source = None
    if os.path.exists("/etc/secrets/cookies.txt"):
        cookie_source = "/etc/secrets/cookies.txt"
    elif os.path.exists("cookies.txt"):
        cookie_source = "cookies.txt"
    elif os.environ.get("YOUTUBE_COOKIES"):
        raw_cookies = os.environ.get("YOUTUBE_COOKIES", "")
        cookie_source = "/tmp/youtube_cookies.txt"
        clean_cookies = raw_cookies.replace("\r\n", "\n").strip() + "\n"
        with open(cookie_source, "w", encoding="utf-8") as f:
            f.write(clean_cookies)

    if cookie_source:
        opts["cookiefile"] = cookie_source
        with open(cookie_source, "r", encoding="utf-8", errors="ignore") as f:
            line_count = len(f.readlines())
        print(f"yt-dlp {yt_dlp.version.__version__} | Cookies loaded from {cookie_source} ({line_count} lines)")
    else:
        print(f"yt-dlp {yt_dlp.version.__version__} | No cookies found")

    return opts

@app.get('/')
@app.head('/')
def home():
    return {"status": "online", "message": "Video & Audio Downloader API Ready"}

@app.get('/info')
def get_info(url: str = Query(..., description="YouTube, Instagram, or Facebook URL")):
    ydl_opts = get_base_ydl_opts()
    ydl_opts['skip_download'] = True

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
        print("INFO ERROR:", str(e))
        raise HTTPException(status_code=400, detail=str(e))

@app.get('/download')
def download_media(
    background_tasks: BackgroundTasks,
    url: str = Query(...),
    quality: str = Query("720")
):
    temp_dir = tempfile.mkdtemp()
    try:
        info_opts = get_base_ydl_opts()
        info_opts['skip_download'] = True
        with yt_dlp.YoutubeDL(info_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = clean_filename(info.get("title", "media"))

        unique_id = str(uuid.uuid4())[:8]
        out_template = os.path.join(temp_dir, f"{title}_{unique_id}.%(ext)s")

        ydl_opts = get_base_ydl_opts()
        ydl_opts['outtmpl'] = out_template

        if quality == "mp3":
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
            ext = "mp3"
            media_type = "audio/mpeg"
        elif quality == "m4a":
            ydl_opts['format'] = 'bestaudio[ext=m4a]/bestaudio/best'
            ext = "m4a"
            media_type = "audio/mp4"
        else:
            ydl_opts['format'] = f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best'
            ydl_opts['merge_output_format'] = 'mp4'
            ext = "mp4"
            media_type = "video/mp4"

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        downloaded_files = os.listdir(temp_dir)
        if not downloaded_files:
            raise HTTPException(status_code=500, detail="Download failed on server.")

        file_path = os.path.join(temp_dir, downloaded_files[0])
        final_filename = f"{title}_{quality}.{ext}"

        background_tasks.add_task(shutil.rmtree, temp_dir, True)
        return FileResponse(path=file_path, filename=final_filename, media_type=media_type)

    except Exception as e:
        shutil.rmtree(temp_dir, True)
        print("DOWNLOAD ERROR:", str(e))
        raise HTTPException(status_code=400, detail=str(e))

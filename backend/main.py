import re
import uuid
import asyncio
from pathlib import Path
 
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
 
app = FastAPI()
 
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)
 
TMP = Path("/tmp/ytmp3")
TMP.mkdir(exist_ok=True)
 
 
def extract_video_id(url: str) -> str | None:
    patterns = [
        r"(?:v=|/shorts/|youtu\.be/)([A-Za-z0-9_-]{11})",
        r"embed/([A-Za-z0-9_-]{11})",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None
 
 
async def run_cmd(cmd):
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
    return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")
 
 
@app.get("/convert")
async def convert(url: str = Query(..., description="YouTube URL")):
    video_id = extract_video_id(url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")
 
    # Always update yt-dlp before converting (keeps it fresh without rebuilding Docker)
    await run_cmd(["yt-dlp", "-U"])
 
    job_id = uuid.uuid4().hex
    out_dir = TMP / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_template = str(out_dir / "%(title)s.%(ext)s")
 
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "--format", "bestaudio/best",
        "--output", out_template,
        "--no-progress",
        "--extractor-args", "youtube:player_client=web",
        f"https://www.youtube.com/watch?v={video_id}",
    ]
 
    try:
        returncode, stdout, stderr = await run_cmd(cmd)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Conversion timed out — try a shorter video")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
 
    if returncode != 0:
        # Return full stderr so we can debug
        raise HTTPException(status_code=500, detail=stderr.strip() or "yt-dlp failed")
 
    mp3_files = list(out_dir.glob("*.mp3"))
    if not mp3_files:
        raise HTTPException(status_code=500, detail="MP3 not found after conversion")
 
    mp3_path = mp3_files[0]
    return FileResponse(
        path=str(mp3_path),
        media_type="audio/mpeg",
        filename=mp3_path.name,
        headers={
            "Content-Disposition": f'attachment; filename="{mp3_path.name}"',
            "Cache-Control": "no-store",
        },
    )
 
 
@app.get("/health")
async def health():
    return {"status": "ok"}


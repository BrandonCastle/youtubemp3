import os
import re
import uuid
import asyncio
import subprocess
from pathlib import Path

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Allow all origins so your Netlify frontend can call this
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

TMP = Path("/tmp/ytmp3")
TMP.mkdir(exist_ok=True)

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


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


@app.get("/convert")
async def convert(url: str = Query(..., description="YouTube URL")):
    video_id = extract_video_id(url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

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
    "--no-warnings",
    "--no-check-certificates",
    f"https://www.youtube.com/watch?v={video_id}",
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Conversion timed out (video may be too long)")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if proc.returncode != 0:
        err = stderr.decode(errors="replace").strip().splitlines()
        # Surface the last meaningful line
        msg = next((l for l in reversed(err) if l and not l.startswith("[")), "yt-dlp failed")
        raise HTTPException(status_code=500, detail=msg)

    mp3_files = list(out_dir.glob("*.mp3"))
    if not mp3_files:
        raise HTTPException(status_code=500, detail="MP3 file not found after conversion")

    mp3_path = mp3_files[0]
    filename = mp3_path.name

    return FileResponse(
        path=str(mp3_path),
        media_type="audio/mpeg",
        filename=filename,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


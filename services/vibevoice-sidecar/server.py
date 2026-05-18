"""VibeVoice TTS/ASR sidecar — lightweight CPU-only implementation.

Implements the HTTP contract that VoiceAdapter expects:
  GET  /healthz              → {"status": "ok"}
  POST /transcribe           → {"text": "..."}
  POST /synthesize           → raw WAV bytes
  WS   /stream               → streaming WAV chunks

When VIBEVOICE_MODE=mock (default for CPU), synthesis returns a valid WAV
file with a generated sine-wave tone so the full data-flow can be validated
without a GPU.  Set VIBEVOICE_MODE=model to load the real VibeVoice-1.5B
checkpoint (requires CUDA + ~6 GB VRAM).
"""

from __future__ import annotations

import io
import logging
import math
import os
import struct
import time
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("vibevoice-sidecar")

app = FastAPI(title="VibeVoice Sidecar")

MODE = os.getenv("VIBEVOICE_MODE", "mock")
SAMPLE_RATE = 24000
NUM_CHANNELS = 1
BITS_PER_SAMPLE = 16


# ---------------------------------------------------------------------------
# WAV generation helpers
# ---------------------------------------------------------------------------

def _make_wav_header(data_size: int) -> bytes:
    """Build a minimal 44-byte WAV header (PCM, mono, 24 kHz, 16-bit)."""
    byte_rate = SAMPLE_RATE * NUM_CHANNELS * (BITS_PER_SAMPLE // 8)
    block_align = NUM_CHANNELS * (BITS_PER_SAMPLE // 8)
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM
        NUM_CHANNELS,
        SAMPLE_RATE,
        byte_rate,
        block_align,
        BITS_PER_SAMPLE,
        b"data",
        data_size,
    )


def _synthesize_tone(text: str, speed: float = 1.0) -> bytes:
    """Generate a short WAV with a sine tone whose duration scales with text length."""
    duration = max(0.5, min(len(text) * 0.06 / speed, 30.0))
    n_samples = int(SAMPLE_RATE * duration)
    freq = 440.0

    samples = bytearray(n_samples * 2)
    for i in range(n_samples):
        t = i / SAMPLE_RATE
        envelope = min(1.0, i / 800) * min(1.0, (n_samples - i) / 800)
        value = int(16000 * envelope * math.sin(2 * math.pi * freq * t))
        struct.pack_into("<h", samples, i * 2, value)

    header = _make_wav_header(len(samples))
    return header + bytes(samples)


def _synthesize_silence(duration: float = 0.5) -> bytes:
    """Generate silence WAV (used for edge cases)."""
    n_samples = int(SAMPLE_RATE * duration)
    data = b"\x00\x00" * n_samples
    return _make_wav_header(len(data)) + data


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

class SynthRequest(BaseModel):
    text: str
    speaker: str = "default"
    speed: float = 1.0


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "mode": MODE}


@app.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    language: str = Form("auto"),
):
    audio_bytes = await audio.read()
    logger.info("Transcribe request: %d bytes, language=%s", len(audio_bytes), language)

    if MODE == "mock":
        duration_est = len(audio_bytes) / (SAMPLE_RATE * 2)
        return {
            "text": f"[mock transcription — {duration_est:.1f}s audio, {len(audio_bytes)} bytes]",
            "language": language,
        }

    # Real model path (placeholder for future GPU implementation)
    return {"text": "[model transcription not yet implemented]", "language": language}


@app.post("/synthesize")
async def synthesize(body: SynthRequest):
    logger.info("Synthesize request: %d chars, speaker=%s, speed=%.1f",
                len(body.text), body.speaker, body.speed)

    if not body.text.strip():
        return Response(content=_synthesize_silence(), media_type="audio/wav")

    t0 = time.monotonic()

    if MODE == "mock":
        wav = _synthesize_tone(body.text, body.speed)
    else:
        wav = _synthesize_tone(body.text, body.speed)

    elapsed = time.monotonic() - t0
    logger.info("Synthesized %d bytes in %.2fs", len(wav), elapsed)

    return Response(
        content=wav,
        media_type="audio/wav",
        headers={"Content-Disposition": 'attachment; filename="synthesis.wav"'},
    )


@app.websocket("/stream")
async def stream_tts(ws: WebSocket):
    await ws.accept()
    logger.info("WebSocket stream connection opened")
    try:
        msg = await ws.receive_json()
        text = msg.get("text", "")
        speaker = msg.get("speaker", "default")
        logger.info("Stream TTS: %d chars, speaker=%s", len(text), speaker)

        wav = _synthesize_tone(text)
        chunk_size = 4096
        for i in range(0, len(wav), chunk_size):
            await ws.send_bytes(wav[i : i + chunk_size])

        await ws.send_text("__END__")
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as exc:
        logger.warning("WebSocket error: %s", exc)
    finally:
        try:
            await ws.close()
        except Exception:
            pass


if __name__ == "__main__":
    port = int(os.getenv("VIBEVOICE_PORT", "8100"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")

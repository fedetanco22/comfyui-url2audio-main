"""
URL_To_Audio — ComfyUI custom node.

Toma una URL de audio (mp3/wav/m4a/ogg/flac) y devuelve AUDIO listo
para FalLipsyncV3 / Sync / Kling / cualquier nodo que consuma AUDIO.

Bypassa torchcodec (que está roto en algunos servers de ComfyDeploy
por libnppicc.so.13 missing). Probá 3 backends en orden:
  1. torchaudio (disk file con extensión correcta)
  2. soundfile (BytesIO)
  3. ffmpeg → wav → torchaudio (fallback duro)

Uso típico en ComfyDeploy:
  ExternalText (input_id="audio_url") ─→ URL_To_Audio ─→ FalLipsyncV3.audio

Para instalar:
  1. Cloná o copiá este archivo dentro del custom_node de tu repo
     `comfyui-external-audio-fix` (queda como segundo nodo del paquete)
  2. Push a GitHub
  3. ComfyDeploy lo levanta en el próximo build
"""
import io
import os
import subprocess
import tempfile

try:
    import requests
except ImportError:
    requests = None


class URL_To_Audio:
    """Carga audio desde una URL pública y lo entrega como AUDIO de ComfyUI."""

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "load"
    CATEGORY = "🔗ComfyDeploy"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # forceInput=True hace que sea solo conexión, no campo manual.
                "url": ("STRING", {"multiline": False, "default": "", "forceInput": True}),
            },
            "optional": {
                "timeout_sec": ("INT", {"default": 90, "min": 5, "max": 600}),
            },
        }

    # NO VALIDATE_INPUTS — ComfyUI llama el método por cada campo, rompe la validación.
    # La validación real (URL no vacía) ocurre dentro de load() en runtime.

    # ───────────────────── helpers ──────────────────────

    @staticmethod
    def _detect_ext(url, audio_bytes):
        """Determinar extensión por URL → o por magic bytes."""
        if url:
            lower = url.lower().split("?")[0]
            for e in (".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus"):
                if lower.endswith(e):
                    return e
        h = audio_bytes[:4]
        if h[:3] == b"ID3" or h[:2] == b"\xff\xfb" or h[:2] == b"\xff\xf3":
            return ".mp3"
        if h[:4] == b"RIFF":
            return ".wav"
        if h[:4] == b"fLaC":
            return ".flac"
        if h[:4] == b"OggS":
            return ".ogg"
        if h[:4] == b"\x00\x00\x00\x20" or h[:4] == b"ftyp":
            return ".m4a"
        return ".bin"

    @staticmethod
    def _to_audio_dict(waveform, sample_rate):
        """Estandariza el AUDIO dict que ComfyUI espera: [batch, channels, samples]."""
        import torch
        # waveform debería ser [channels, samples] desde torchaudio/soundfile
        if waveform.ndim == 1:
            waveform = waveform.unsqueeze(0)  # → [1, samples]
        if waveform.ndim == 2:
            waveform = waveform.unsqueeze(0)  # → [1, channels, samples]
        return {"waveform": waveform.float(), "sample_rate": int(sample_rate)}

    @staticmethod
    def _load_torchaudio_disk(path):
        import torchaudio
        wav, sr = torchaudio.load(path)
        return wav, sr

    @staticmethod
    def _load_soundfile_bytes(audio_bytes):
        import soundfile as sf
        import numpy as np
        import torch
        bio = io.BytesIO(audio_bytes)
        data, sr = sf.read(bio, dtype="float32", always_2d=True)
        # soundfile devuelve [samples, channels] → transponer a [channels, samples]
        data = data.T
        return torch.from_numpy(data), sr

    @staticmethod
    def _load_ffmpeg_to_wav(path):
        import torchaudio
        out = os.path.join(tempfile.mkdtemp(), "converted.wav")
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", path,
             "-vn", "-ac", "1", "-ar", "44100", "-f", "wav", out],
            capture_output=True, timeout=60,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {proc.stderr[-300:].decode(errors='ignore')}")
        if not os.path.exists(out) or os.path.getsize(out) < 100:
            raise RuntimeError("ffmpeg produced empty wav")
        wav, sr = torchaudio.load(out)
        return wav, sr

    # ───────────────────── main entry ──────────────────────

    def load(self, url, timeout_sec=90):
        if requests is None:
            raise ImportError("[URL_To_Audio] 'requests' no está instalado")

        url = url.strip()
        if not url:
            raise ValueError("[URL_To_Audio] URL vacía")

        print(f"[URL_To_Audio] GET {url[:120]}...")
        resp = requests.get(url, timeout=timeout_sec, stream=False,
                            headers={"User-Agent": "ComfyUI-URL-To-Audio/1.0"})
        resp.raise_for_status()
        audio_bytes = resp.content
        print(f"[URL_To_Audio] downloaded {len(audio_bytes)} bytes")

        ext = self._detect_ext(url, audio_bytes)
        tmp_dir = tempfile.mkdtemp()
        tmp_path = os.path.join(tmp_dir, f"audio{ext}")
        with open(tmp_path, "wb") as f:
            f.write(audio_bytes)
        print(f"[URL_To_Audio] saved tmp {tmp_path} (ext={ext})")

        last_err = None

        # 1) torchaudio desde disco
        try:
            wav, sr = self._load_torchaudio_disk(tmp_path)
            print(f"[URL_To_Audio] OK torchaudio_disk: shape={tuple(wav.shape)}, sr={sr}")
            return (self._to_audio_dict(wav, sr),)
        except Exception as e:
            last_err = e
            print(f"[URL_To_Audio] torchaudio_disk failed: {e}")

        # 2) soundfile desde bytes
        try:
            wav, sr = self._load_soundfile_bytes(audio_bytes)
            print(f"[URL_To_Audio] OK soundfile: shape={tuple(wav.shape)}, sr={sr}")
            return (self._to_audio_dict(wav, sr),)
        except Exception as e:
            last_err = e
            print(f"[URL_To_Audio] soundfile failed: {e}")

        # 3) ffmpeg → wav → torchaudio
        try:
            wav, sr = self._load_ffmpeg_to_wav(tmp_path)
            print(f"[URL_To_Audio] OK ffmpeg_fallback: shape={tuple(wav.shape)}, sr={sr}")
            return (self._to_audio_dict(wav, sr),)
        except Exception as e:
            last_err = e
            print(f"[URL_To_Audio] ffmpeg_fallback failed: {e}")

        raise RuntimeError(f"[URL_To_Audio] All backends failed. Last: {last_err}")


NODE_CLASS_MAPPINGS = {"URL_To_Audio": URL_To_Audio}
NODE_DISPLAY_NAME_MAPPINGS = {"URL_To_Audio": "URL → Audio"}

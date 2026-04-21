# comfyui-url2audio

ComfyUI custom node that loads `AUDIO` from a public URL.

## Why

Some ComfyDeploy server images ship a broken `torchcodec` (missing `libnppicc.so.13`),
which makes the default `LoadAudioFromURL` / `ComfyUIDeployExternalAudio` flows crash with:

```
TypeError: 'NoneType' object is not subscriptable
```

This node bypasses `torchcodec` entirely. It downloads the file via `requests`,
detects the format (mp3 / wav / m4a / ogg / flac / aac / opus), then tries 3 backends
in order until one succeeds:

1. **torchaudio** (disk file)
2. **soundfile** (in-memory bytes)
3. **ffmpeg → wav** (hard fallback)

## Node

| Name | Display | Category |
|------|---------|----------|
| `URL_To_Audio` | `URL → Audio` | `🔗ComfyDeploy` |

### Inputs

| Field | Type | Notes |
|-------|------|-------|
| `url` | STRING | Public URL of the audio file |
| `timeout_sec` | INT (optional) | HTTP timeout, default 90 |

### Output

| Name | Type |
|------|------|
| `audio` | AUDIO |

The `AUDIO` dict format is the standard ComfyUI one:

```python
{"waveform": torch.Tensor [batch=1, channels, samples], "sample_rate": int}
```

## Wiring example (Kling+Sync workflow)

Replace the broken audio loader with:

```
ExternalText (input_id="audio_url")  ─→  URL → Audio  ─→  FalLipsyncV3.audio
```

From your client, send the audio URL as a string instead of uploading the WAV file:

```python
{
    "deployment_id": "...",
    "inputs": {
        "input_image": image_url,
        "audio_url": "https://your-cdn.com/voice.mp3",
        "motion": "...",
        ...
    }
}
```

## Install (ComfyDeploy)

Add this repo URL to your ComfyDeploy machine's custom nodes list,
or in a self-hosted ComfyUI:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/PauldeLavallaz/comfyui-url2audio
pip install requests soundfile
```

## License

MIT

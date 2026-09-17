# Local AI and media setup

## FFmpeg / FFprobe

Install both executables and ensure `ffmpeg -version` and `ffprobe -version` work as the application's OS user. Configure `FFMPEG_BIN` and `FFPROBE_BIN` if not on PATH. FFmpeg must include libx264, AAC, and the subtitles/libass filter. `PROCESS_TIMEOUT` bounds local subprocess execution (default 1800 seconds). Long or high-resolution media may need more time/resources.

## whisper.cpp (not faster-whisper)

Install/build whisper.cpp's **whisper-cli** for your operating system, and download a compatible GGML model separately. Configure `WHISPER_BINARY` and `WHISPER_MODEL`. The binary must be executable; PATH commands and explicit relative/absolute paths are supported.

The application extracts mono 16 kHz PCM WAV, invokes automatic language detection and `--output-json-full`, and reads `transcription[]`, its `tokens[]`, token `offsets.from/to` in **milliseconds**, and `result.language`. Subword tokens are merged at whitespace boundaries. This is suitable for whitespace-delimited languages; tokenization of languages without word separators needs further validation. Missing audio/speech/timestamps produce an error, not a fabricated transcript.

Do not commit your local whisper.cpp checkout or model binaries. Model execution was not available during this audit; parser behavior is fixture-tested against the full-JSON shape.

## Ollama

Install and start Ollama, then run `ollama pull llama3.2:3b` (or configure `OLLAMA_MODEL`). Set `OLLAMA_BASE_URL` to the backend-reachable service. Metadata requests use a 120-second timeout and validate the returned JSON object and field types. Pull the exact configured model; availability is required at request time.

## Translation

`TRANSLATION_BACKEND=ollama` is the existing/default implementation. For Argos, install `backend/requirements-argos.txt`, set `TRANSLATION_BACKEND=argos`, and install the desired source/target language packages using Argos' local package tooling. Packages are not silently downloaded by an HTTP request. Missing dependency/pair is actionable. Language codes such as `en` and `ur` are accepted, not arbitrary instructions as language names.

## Piper

Install a compatible Piper CLI and its native dependencies. Place `.onnx` models and matching `.onnx.json` files in `PIPER_VOICE_DIR`, and set `PIPER_MODEL` for the configured default. A voice is not listed without both files and readable configuration. Gender is `unknown` unless explicitly declared by configuration; filename guessing does not establish male/female availability. Language is read from model configuration where present. Multi-speaker models expose their speaker map in the voice selector; invalid speaker IDs are rejected before synthesis.

Voice audio must be a nonempty WAV. After generating speech, use **Generate Captions from Voice-over** before burning its captions. This retranscribes the actual synthesized audio, preserving the original transcript separately. Longer narration can extend the final frame or be trimmed explicitly; time stretching is not used.

# Local AI setup

## Ollama
Install Ollama, then download a local model, for example:

`ollama pull llama3.2:3b`

## faster-whisper
The selected Whisper model downloads on first use and can then run locally.

## Argos Translate
Install the language packages you need (for example English/Urdu) and keep them locally.

## Piper
Install Piper and download the voice model(s) you want. Set `PIPER_BIN` and `PIPER_MODEL` in `.env`.

Multiple voices are supported by changing the configured Piper model. The next implementation can expose a local voice library instead of one default voice.

## FFmpeg
Make sure `ffmpeg -version` works in the same environment as the backend.

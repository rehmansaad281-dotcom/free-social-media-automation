import json
import subprocess
from types import SimpleNamespace
import pytest
from backend.app.ai.transcription import _parse_whisper_json
from backend.app.ai.content import generate_metadata
from backend.app.ai.translation import translate_text
from backend.app.ai.tts import list_voices
from backend.app.config import settings
from backend.app.media import captions_to_srt, normalize_video, replace_audio, burn_subtitles, probe


def test_whisper_cpp_milliseconds_and_subwords(tmp_path):
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"result": {"language": "en"}, "transcription": [{"text": " Hello world!", "tokens": [
        {"text": "[_BEG_]", "offsets": {"from": 0, "to": 1}},
        {"text": " Hel", "offsets": {"from": 1000, "to": 1200}},
        {"text": "lo", "offsets": {"from": 1200, "to": 1300}},
        {"text": " world", "offsets": {"from": 1300, "to": 1500}},
        {"text": "!", "offsets": {"from": 1500, "to": 1550}},
    ]}]}))
    result = _parse_whisper_json(str(path))
    assert result["text"] == "Hello world!"
    assert result["words"] == [{"text": "Hello", "start_ms": 1000, "end_ms": 1300}, {"text": "world!", "start_ms": 1300, "end_ms": 1550}]


@pytest.mark.parametrize("value", [[], {}, {"transcription": "text"}, {"transcription": [{"text": "text", "tokens": []}]}])
def test_whisper_invalid_json(tmp_path, value):
    path = tmp_path / "out.json"; path.write_text(json.dumps(value))
    with pytest.raises(RuntimeError):
        _parse_whisper_json(str(path))


@pytest.mark.parametrize("raw", ['{}', '[]', 'not json', '{"title":null}', '{"title":"Title","description":"d","hashtags":[1],"keywords":[]}'])
def test_metadata_malformed(monkeypatch, raw):
    from backend.app.ai import content
    monkeypatch.setattr(content, "Client", lambda **kw: SimpleNamespace(chat=lambda **kw: {"message": {"content": raw}}))
    with pytest.raises(RuntimeError):
        generate_metadata("hello")


def test_translation_validation():
    with pytest.raises(ValueError): translate_text("", "en", "ur")
    with pytest.raises(ValueError): translate_text("hi", "en", "invalid language")
    assert translate_text("hello", "en", "en") == "hello"


def test_voice_models_require_config(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "piper_voice_dir", str(tmp_path))
    monkeypatch.setattr(settings, "piper_model", str(tmp_path / "missing.onnx"))
    model = tmp_path / "voice.onnx"; model.touch()
    assert list_voices() == []
    (tmp_path / "voice.onnx.json").write_text('{}')
    assert len(list_voices()) == 1


def test_srt_milliseconds(tmp_path):
    path = tmp_path / "captions.srt"
    captions_to_srt([SimpleNamespace(start_ms=1001, end_ms=2010, text="hello")], str(path))
    assert "00:00:01,001 --> 00:00:02,010" in path.read_text()


def test_real_ffmpeg_render_and_original_preserved(video, ffmpeg, tmp_path):
    original = video.read_bytes()
    normalized = tmp_path / "normalized.mp4"
    normalize_video(str(video), str(normalized))
    voice = tmp_path / "voice.wav"
    subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "sine=frequency=880", "-t", "0.5", str(voice)], check=True)
    audio = tmp_path / "audio.mp4"
    replace_audio(str(normalized), str(voice), str(audio))
    srt = tmp_path / "captions.srt"
    captions_to_srt([SimpleNamespace(start_ms=0, end_ms=1000, text="Hello")], str(srt))
    final = tmp_path / "final.mp4"
    burn_subtitles(str(audio), str(srt), str(final))
    assert final.stat().st_size > 0
    decoded = subprocess.run([ffmpeg, "-v", "info", "-i", str(final), "-f", "null", "-"], capture_output=True, text=True)
    assert decoded.returncode == 0
    assert "00:00:02." in decoded.stderr  # short voice must not truncate video
    assert video.read_bytes() == original


def test_real_ffprobe(video):
    import shutil
    if not shutil.which(settings.ffprobe_bin):
        pytest.skip("FFprobe executable unavailable")
    assert probe(str(video))["streams"][0]["codec_type"] == "video"

"""Watch Samsung call recordings, transcribe locally, and send text to AI Orchestra."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

AUDIO_EXTENSIONS = {".m4a", ".mp3", ".wav", ".ogg", ".webm", ".flac", ".mp4"}
TEXT_EXTENSIONS = {".txt"}


@dataclass
class Config:
    watch_dir: Path
    api_url: str
    api_key: str
    state_file: Path
    whisper_model: str = "small"
    language: str = "ru"
    poll_seconds: int = 20
    stable_seconds: int = 10
    process_existing: bool = False


def load_config(path: Path) -> Config:
    raw = json.loads(path.read_text(encoding="utf-8"))
    watch_dir = Path(os.path.expandvars(raw["watch_dir"])).expanduser()
    state_value = raw.get("state_file", str(watch_dir / ".call-watcher-state.json"))
    return Config(
        watch_dir=watch_dir,
        api_url=raw.get("api_url", "http://localhost:8787"),
        api_key=raw.get("api_key", ""),
        state_file=Path(os.path.expandvars(state_value)).expanduser(),
        whisper_model=raw.get("whisper_model", "small"),
        language=raw.get("language", "ru"),
        poll_seconds=max(5, int(raw.get("poll_seconds", 20))),
        stable_seconds=max(2, int(raw.get("stable_seconds", 10))),
        process_existing=bool(raw.get("process_existing", False)),
    )


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"initialized": False, "processed": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {"initialized": False, "processed": {}}
    except (OSError, json.JSONDecodeError):
        return {"initialized": False, "processed": {}}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def source_id(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class LocalTranscriber:
    def __init__(self, model_name: str, language: str) -> None:
        self.model_name = model_name
        self.language = language
        self._model = None

    def transcribe(self, path: Path) -> str:
        if path.suffix.lower() in TEXT_EXTENSIONS:
            return path.read_text(encoding="utf-8").strip()
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as error:
                raise RuntimeError(
                    "Установите бесплатный распознаватель: py -m pip install faster-whisper"
                ) from error
            self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
        segments, _ = self._model.transcribe(
            str(path),
            language=self.language or None,
            vad_filter=True,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()


def send_transcript(config: Config, path: Path, file_id: str, transcript: str) -> dict[str, Any]:
    metadata = {
        "source_id": file_id,
        "source_device": "samsung-fold",
        "source_path": str(path),
        "recorded_at": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(path.stat().st_mtime),
        ),
        "language": config.language,
    }
    body = urllib.parse.urlencode(
        {
            "metadata": json.dumps(metadata, ensure_ascii=False),
            "transcript": transcript,
        }
    ).encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Idempotency-Key": file_id,
    }
    if config.api_key:
        headers["x-api-key"] = config.api_key
    request = urllib.request.Request(
        f"{config.api_url.rstrip('/')}/v1/calls/intake",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Оркестр ответил HTTP {error.code}: {detail}") from error


def candidate_files(config: Config) -> list[Path]:
    extensions = AUDIO_EXTENSIONS | TEXT_EXTENSIONS
    return sorted(
        (
            path
            for path in config.watch_dir.iterdir()
            if path.is_file()
            and path.suffix.lower() in extensions
            and time.time() - path.stat().st_mtime >= config.stable_seconds
        ),
        key=lambda path: path.stat().st_mtime,
    )


def scan_once(config: Config, state: dict[str, Any], transcriber: LocalTranscriber) -> int:
    files = candidate_files(config)
    processed = state.setdefault("processed", {})
    if not state.get("initialized") and not config.process_existing:
        for path in files:
            processed[source_id(path)] = {"file": path.name, "status": "skipped-existing"}
        state["initialized"] = True
        save_state(config.state_file, state)
        print(f"Первый запуск: пропущено старых записей — {len(files)}")
        return 0

    state["initialized"] = True
    completed = 0
    for path in files:
        file_id = source_id(path)
        if file_id in processed:
            continue
        print(f"Обрабатываю: {path.name}")
        try:
            transcript = transcriber.transcribe(path)
            if not transcript:
                raise RuntimeError("Распознавание вернуло пустой текст")
            result = send_transcript(config, path, file_id, transcript)
        except Exception as error:
            print(f"Ошибка {path.name}: {error}", file=sys.stderr)
            continue
        processed[file_id] = {
            "file": path.name,
            "call_id": result["call"]["id"],
            "duplicate": result["duplicate"],
            "processed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        save_state(config.state_file, state)
        completed += 1
        project = result.get("suggested_project") or {}
        print(
            f"Готово: проект={project.get('name', 'не определён')}, "
            f"предложено задач={len(result.get('proposed_actions', []))}"
        )
    save_state(config.state_file, state)
    return completed


def main() -> int:
    parser = argparse.ArgumentParser(description="Samsung call recordings → AI Orchestra")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("config.json"),
    )
    parser.add_argument("--once", action="store_true", help="Один проход и выход")
    args = parser.parse_args()

    config = load_config(args.config)
    if not config.watch_dir.is_dir():
        print(f"Папка записей не найдена: {config.watch_dir}", file=sys.stderr)
        return 2
    state = load_state(config.state_file)
    transcriber = LocalTranscriber(config.whisper_model, config.language)
    while True:
        scan_once(config, state, transcriber)
        if args.once:
            return 0
        time.sleep(config.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import wave
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from src.config import find_binary
from src.tools.file_tools import copy_file, ensure_dir, ensure_parent
from src.tools.ffmpeg_tools import run_ffmpeg


def separate_with_demucs(
    source_audio: str | Path,
    output_dir: str | Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    source_path = Path(source_audio)
    directory = ensure_dir(output_dir)
    provider = str(config.get("separation", {}).get("provider", "demucs"))
    if provider != "demucs":
        raise RuntimeError(f"Unsupported separation provider: {provider}")
    method = str(config.get("separation", {}).get("method", "python")).lower()
    if method == "cli":
        return _separate_with_demucs_cli(source_path, directory, config)
    return _separate_with_demucs_python(source_path, directory, config)


def _separate_with_demucs_python(
    source_path: Path,
    directory: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    try:
        import torch
        from demucs.apply import apply_model
        from demucs.pretrained import get_model
        from demucs.separate import load_track
    except ImportError as exc:
        raise RuntimeError(f"Demucs Python API is unavailable: {exc}") from exc
    model_name = str(config.get("separation", {}).get("model", "htdemucs"))
    device = str(config.get("separation", {}).get("device", "cpu"))
    shifts = int(config.get("separation", {}).get("shifts", 1))
    overlap = float(config.get("separation", {}).get("overlap", 0.25))
    segment = config.get("separation", {}).get("segment")
    segment_value = float(segment) if segment else None
    with _temporary_env(_demucs_env(config)):
        model = get_model(model_name)
        model.to(device)
        model.eval()
        wav = load_track(source_path, model.audio_channels, model.samplerate)
        ref = wav.mean(0)
        wav -= ref.mean()
        wav /= ref.std()
        with torch.no_grad():
            sources = apply_model(
                model,
                wav[None],
                device=device,
                shifts=shifts,
                split=True,
                overlap=overlap,
                progress=False,
                num_workers=0,
                segment=segment_value,
            )[0]
        sources *= ref.std()
        sources += ref.mean()
    vocals_index = model.sources.index("vocals")
    vocals = sources[vocals_index]
    background = torch.zeros_like(vocals)
    for index, source in enumerate(sources):
        if index != vocals_index:
            background += source
    raw_dir = ensure_dir(directory / "_python_raw")
    raw_vocals = raw_dir / "vocals.wav"
    raw_background = raw_dir / "background.wav"
    _write_tensor_wav(raw_vocals, vocals, int(model.samplerate))
    _write_tensor_wav(raw_background, background, int(model.samplerate))
    vocals_path = directory / "vocals.wav"
    background_path = directory / "background.wav"
    _standardize_audio(raw_vocals, vocals_path, config)
    _standardize_audio(raw_background, background_path, config)
    return {
        "provider": "demucs",
        "method": "python",
        "model": model_name,
        "source_audio": str(source_path),
        "vocals_wav": str(vocals_path),
        "background_wav": str(background_path),
        "raw_vocals_wav": str(raw_vocals),
        "raw_background_wav": str(raw_background),
    }


def _separate_with_demucs_cli(
    source_path: Path,
    directory: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    demucs_command = _demucs_command()
    model = str(config.get("separation", {}).get("model", "htdemucs"))
    raw_dir = directory / "_demucs_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    command = [
        *demucs_command,
        "--two-stems",
        "vocals",
        "-n",
        model,
        "-o",
        str(raw_dir),
    ]
    shifts = config.get("separation", {}).get("shifts")
    if shifts is not None:
        command.extend(["--shifts", str(shifts)])
    overlap = config.get("separation", {}).get("overlap")
    if overlap is not None:
        command.extend(["--overlap", str(overlap)])
    segment = config.get("separation", {}).get("segment")
    if segment is not None:
        command.extend(["--segment", str(segment)])
    device = config.get("separation", {}).get("device")
    if device:
        command.extend(["--device", str(device)])
    command.append(str(source_path))
    result = subprocess.run(command, capture_output=True, text=True, env=_demucs_env(config))
    if result.returncode != 0:
        output = "\n".join(part for part in [result.stdout, result.stderr] if part)
        raise RuntimeError(
            f"Demucs command failed with exit code {result.returncode}: {' '.join(command)}\n{output}"
        )
    vocals_src, background_src = _find_demucs_stems(raw_dir, model, source_path.stem)
    vocals_path = directory / "vocals.wav"
    background_path = directory / "background.wav"
    _standardize_audio(vocals_src, vocals_path, config)
    _standardize_audio(background_src, background_path, config)
    return {
        "provider": "demucs",
        "method": "cli",
        "model": model,
        "source_audio": str(source_path),
        "vocals_wav": str(vocals_path),
        "background_wav": str(background_path),
        "command": command,
    }


def _find_demucs_stems(raw_dir: Path, model: str, source_stem: str) -> tuple[Path, Path]:
    candidates = [
        raw_dir / model / source_stem,
        *raw_dir.glob(f"*/{source_stem}"),
    ]
    for directory in candidates:
        vocals = directory / "vocals.wav"
        no_vocals = directory / "no_vocals.wav"
        if vocals.exists() and no_vocals.exists():
            return vocals, no_vocals
    raise RuntimeError(f"Unable to locate Demucs stems under {raw_dir}")


def _demucs_command() -> list[str]:
    demucs_binary = shutil.which("demucs")
    if demucs_binary is not None:
        return [demucs_binary]
    return [sys.executable, "-m", "demucs"]


def _demucs_env(config: dict[str, Any]) -> dict[str, str]:
    env = os.environ.copy()
    try:
        ffmpeg_path = find_binary(config, "ffmpeg.ffmpeg_path", "ffmpeg")
    except FileNotFoundError:
        return env
    ffmpeg_dir = str(ffmpeg_path.parent)
    path_value = env.get("PATH", "")
    env["PATH"] = f"{ffmpeg_dir}{os.pathsep}{path_value}" if path_value else ffmpeg_dir
    return env


@contextmanager
def _temporary_env(env: dict[str, str]) -> Iterator[None]:
    original = os.environ.copy()
    os.environ.update(env)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def _write_tensor_wav(path: Path, audio: Any, sample_rate: int) -> None:
    ensure_parent(path)
    tensor = audio.detach().cpu().clamp(-1.0, 1.0)
    if tensor.dim() == 1:
        tensor = tensor.unsqueeze(0)
    pcm = (tensor.transpose(0, 1).contiguous().numpy() * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(int(tensor.shape[0]))
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(pcm.tobytes())


def _standardize_audio(source: Path, destination: Path, config: dict[str, Any]) -> None:
    ensure_parent(destination)
    sample_rate = int(config.get("media", {}).get("audio_sample_rate", 16000))
    try:
        run_ffmpeg(
            config,
            [
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                source,
                "-ac",
                "1",
                "-ar",
                str(sample_rate),
                "-c:a",
                "pcm_s16le",
                destination,
            ],
        )
    except Exception:
        copy_file(source, destination)

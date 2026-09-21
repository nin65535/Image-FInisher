from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Callable

from PIL import Image, UnidentifiedImageError

from backend.app.services.mosaic import MosaicClient
from backend.app.services.rename import _exclusive_commit
from backend.app.services.upscale import ComfyUIClient


class PipelineError(RuntimeError):
    """A user-facing failure from an integrated image pipeline."""


def _size(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as image:
            if image.format != "PNG":
                raise PipelineError("処理結果がPNG形式ではありません。")
            image.verify()
        with Image.open(path) as image:
            image.load()
            return image.size
    except PipelineError:
        raise
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        raise PipelineError(f"PNGを読み込めません: {exc}") from exc


def execute_pipeline(
    *, source_path: str, output_path: str, enabled_steps: list[str], settings: dict[str, Any],
    job_id: str, image_id: int, upscale_client: ComfyUIClient | None,
    mosaic_client: MosaicClient | None, on_step: Callable[[str, str, str | None, str | None], None],
) -> dict[str, Any]:
    source, destination = Path(source_path), Path(output_path)
    temp_root = destination.parent.parent / ".imagefinisher-tmp"
    image_temp = temp_root / job_id / str(image_id)
    current = image_temp / "source.png"
    original_size = _size(source)
    current_size = original_size
    committed = False
    if destination.exists():
        raise PipelineError(f"完成ファイルがすでに存在します: {destination.name}")
    try:
        destination.parent.mkdir(parents=False, exist_ok=True)
        image_temp.mkdir(parents=True, exist_ok=False)
        shutil.copy2(source, current)
        for index, step in enumerate(enabled_steps):
            result = image_temp / f"{index + 1}_{step}.png"
            on_step(step, "running", str(current), None)
            try:
                if step == "rename":
                    shutil.copy2(current, result)
                    expected = current_size
                elif step == "upscale":
                    if upscale_client is None:
                        raise PipelineError("ComfyUI拡大サービスが設定されていません。")
                    expected = (current_size[0] * 2, current_size[1] * 2)
                    upscale_client.upscale(current, result, f"{upscale_client.config.output_subfolder}/{job_id}_{image_id}")
                elif step == "mosaic":
                    if mosaic_client is None:
                        raise PipelineError("ComfyUI AutoMosaicサービスが設定されていません。")
                    strength = settings.get("mosaic_strength")
                    mosaic_client.config.validate_strength(strength)
                    expected = current_size
                    mosaic_client.mosaic(current, result, f"{mosaic_client.config.output_subfolder}/{job_id}_{image_id}", strength)
                else:
                    raise PipelineError(f"未対応の工程です: {step}")
                actual = _size(result)
                if actual != expected:
                    raise PipelineError(
                        f"{step}後の画像寸法が不正です: expected={expected[0]}x{expected[1]}, "
                        f"actual={actual[0]}x{actual[1]}"
                    )
            except Exception as exc:
                on_step(step, "failed", str(current), str(exc))
                raise
            on_step(step, "completed", str(current), str(result))
            current, current_size = result, expected
        _exclusive_commit(current, destination)
        committed = True
        if _size(destination) != current_size:
            raise PipelineError("完成ファイルの検証に失敗しました。")
        return {"format": "PNG", "source_size": list(original_size), "size": list(current_size)}
    finally:
        if committed:
            try:
                if _size(destination) != current_size:
                    destination.unlink(missing_ok=True)
            except PipelineError:
                destination.unlink(missing_ok=True)
        shutil.rmtree(image_temp, ignore_errors=True)
        try:
            (temp_root / job_id).rmdir()
            temp_root.rmdir()
        except OSError:
            pass

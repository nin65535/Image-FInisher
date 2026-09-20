from __future__ import annotations

import copy
import json
import mimetypes
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from backend.app.services.rename import _exclusive_commit


class UpscaleError(RuntimeError):
    """A safe, user-facing upscale step failure."""


@dataclass(frozen=True)
class UpscaleConfig:
    workflow_path: Path
    source_node: str
    source_input: str
    output_node: str
    output_input: str
    output_subfolder: str
    timeout_seconds: float


def load_upscale_config(app_root: Path) -> UpscaleConfig:
    try:
        master = json.loads((app_root / "app_master.json").read_text(encoding="utf-8"))
        raw = master["comfyui"]["imageUpscale"]
        workflow_path = (app_root / raw["workflowPath"]).resolve()
        if not workflow_path.is_relative_to(app_root.resolve()) or not workflow_path.is_file():
            raise ValueError("workflowPath がアプリ内の既存ファイルではありません。")
        config = UpscaleConfig(
            workflow_path=workflow_path,
            source_node=str(raw["nodes"]["sourceImage"]["nodeId"]),
            source_input=str(raw["nodes"]["sourceImage"]["inputName"]),
            output_node=str(raw["nodes"]["output"]["nodeId"]),
            output_input=str(raw["nodes"]["output"]["inputName"]),
            output_subfolder=str(raw["outputSubfolder"]).strip("/\\"),
            timeout_seconds=float(raw["timeoutSeconds"]),
        )
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        workflow[config.source_node]["inputs"][config.source_input]
        workflow[config.output_node]["inputs"][config.output_input]
        if not config.output_subfolder or config.timeout_seconds <= 0:
            raise ValueError("出力サブフォルダまたはタイムアウトが不正です。")
        return config
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"拡大設定を読み込めません: {exc}") from exc


class ComfyUIClient:
    def __init__(self, config: UpscaleConfig, base_url: str = "http://127.0.0.1:8188") -> None:
        self.config = config
        self.base_url = base_url.rstrip("/")
        self._workflow = json.loads(config.workflow_path.read_text(encoding="utf-8"))

    def _request(self, path: str, *, data: bytes | None = None, headers: dict[str, str] | None = None) -> bytes:
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except (OSError, urllib.error.URLError) as exc:
            raise UpscaleError(f"ComfyUIへ接続できません: {exc}") from exc

    def _upload(self, source: Path) -> str:
        boundary = uuid.uuid4().hex
        mime = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{source.name}\"\r\n"
            f"Content-Type: {mime}\r\n\r\n"
        ).encode() + source.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        result = json.loads(self._request("/upload/image", data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}))
        return str(Path(result.get("subfolder", "")) / result["name"]).replace("\\", "/")

    def upscale(self, source: Path, destination: Path, output_prefix: str) -> None:
        uploaded = self._upload(source)
        workflow = copy.deepcopy(self._workflow)
        workflow[self.config.source_node]["inputs"][self.config.source_input] = uploaded
        workflow[self.config.output_node]["inputs"][self.config.output_input] = output_prefix
        payload = json.dumps({"prompt": workflow, "client_id": uuid.uuid4().hex}).encode()
        queued = json.loads(self._request("/prompt", data=payload, headers={"Content-Type": "application/json"}))
        prompt_id = queued.get("prompt_id")
        if not prompt_id:
            raise UpscaleError("ComfyUIがprompt_idを返しませんでした。")

        deadline = time.monotonic() + self.config.timeout_seconds
        output: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            history = json.loads(self._request(f"/history/{urllib.parse.quote(str(prompt_id))}"))
            entry = history.get(str(prompt_id))
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error" or status.get("completed") is False:
                    raise UpscaleError("ComfyUIの拡大処理が失敗しました。")
                images = entry.get("outputs", {}).get(self.config.output_node, {}).get("images", [])
                if images:
                    output = images[0]
                    break
            time.sleep(0.2)
        if output is None:
            raise UpscaleError("ComfyUIの拡大処理がタイムアウトしました。")
        query = urllib.parse.urlencode({key: output[key] for key in ("filename", "subfolder", "type") if key in output})
        destination.write_bytes(self._request(f"/view?{query}"))


def _verify_upscaled_png(path: Path, expected_size: tuple[int, int]) -> None:
    try:
        with Image.open(path) as image:
            if image.format != "PNG":
                raise UpscaleError("拡大結果がPNG形式ではありません。")
            image.verify()
        with Image.open(path) as image:
            image.load()
            if image.size != expected_size:
                raise UpscaleError(
                    f"拡大後の画像寸法が不正です: expected={expected_size[0]}x{expected_size[1]}, "
                    f"actual={image.width}x{image.height}"
                )
    except UpscaleError:
        raise
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        raise UpscaleError(f"拡大結果のPNGを読み込めません: {exc}") from exc


def execute_upscale(*, client: ComfyUIClient, source_path: str, output_path: str,
                    expected_size: tuple[int, int], job_id: str, image_id: int,
                    output_subfolder: str) -> str:
    source = Path(source_path)
    destination = Path(output_path)
    temp_root = destination.parent.parent / ".imagefinisher-tmp"
    image_temp = temp_root / job_id / str(image_id)
    staged = image_temp / destination.name
    committed = False
    if not source.is_file():
        raise UpscaleError(f"入力原本が見つかりません: {source}")
    if destination.exists():
        raise UpscaleError(f"完成ファイルがすでに存在します: {destination.name}")
    try:
        destination.parent.mkdir(parents=False, exist_ok=True)
        image_temp.mkdir(parents=True, exist_ok=False)
        prefix = f"{output_subfolder}/{job_id}_{image_id}"
        client.upscale(source, staged, prefix)
        _verify_upscaled_png(staged, expected_size)
        _exclusive_commit(staged, destination)
        committed = True
        _verify_upscaled_png(destination, expected_size)
        return str(destination)
    except FileExistsError as exc:
        raise UpscaleError("画像専用の一時領域がすでに存在します。") from exc
    finally:
        if committed:
            try:
                _verify_upscaled_png(destination, expected_size)
            except UpscaleError:
                destination.unlink(missing_ok=True)
        shutil.rmtree(image_temp, ignore_errors=True)
        try:
            (temp_root / job_id).rmdir()
            temp_root.rmdir()
        except OSError:
            pass

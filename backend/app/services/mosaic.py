from __future__ import annotations

import copy
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from backend.app.services.rename import _exclusive_commit
from backend.app.services.upscale import ComfyUIClient, UpscaleConfig, UpscaleError


class MosaicError(RuntimeError):
    """A safe, user-facing AutoMosaic step failure."""


@dataclass(frozen=True)
class MosaicConfig:
    workflow_path: Path
    source_node: str
    source_input: str
    strength_node: str
    strength_input: str
    output_node: str
    output_input: str
    output_subfolder: str
    timeout_seconds: float
    minimum: int
    maximum: int | None
    default: int

    def validate_strength(self, value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise MosaicError("モザイク強度は整数で指定してください。")
        if value < self.minimum or (self.maximum is not None and value > self.maximum):
            upper = f"{self.maximum}以下" if self.maximum is not None else ""
            raise MosaicError(f"モザイク強度は{self.minimum}以上{upper}で指定してください。")
        return value


def load_mosaic_config(app_root: Path) -> MosaicConfig:
    try:
        master = json.loads((app_root / "app_master.json").read_text(encoding="utf-8"))
        raw = master["comfyui"]["autoMosaic"]
        strength = raw["strength"]
        workflow_path = (app_root / raw["workflowPath"]).resolve()
        if not workflow_path.is_relative_to(app_root.resolve()) or not workflow_path.is_file():
            raise ValueError("workflowPath がアプリ内の既存ファイルではありません。")
        config = MosaicConfig(
            workflow_path=workflow_path,
            source_node=str(raw["nodes"]["sourceImage"]["nodeId"]),
            source_input=str(raw["nodes"]["sourceImage"]["inputName"]),
            strength_node=str(raw["nodes"]["strength"]["nodeId"]),
            strength_input=str(raw["nodes"]["strength"]["inputName"]),
            output_node=str(raw["nodes"]["output"]["nodeId"]),
            output_input=str(raw["nodes"]["output"]["inputName"]),
            output_subfolder=str(raw["outputSubfolder"]).strip("/\\"),
            timeout_seconds=float(raw["timeoutSeconds"]),
            minimum=int(strength["minimum"]),
            maximum=int(strength["maximum"]) if strength.get("maximum") is not None else None,
            default=int(strength["default"]),
        )
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        workflow[config.source_node]["inputs"][config.source_input]
        workflow[config.strength_node]["inputs"][config.strength_input]
        workflow[config.output_node]["inputs"][config.output_input]
        if not config.output_subfolder or config.timeout_seconds <= 0:
            raise ValueError("出力サブフォルダまたはタイムアウトが不正です。")
        config.validate_strength(config.default)
        return config
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, MosaicError) as exc:
        raise RuntimeError(f"AutoMosaic設定を読み込めません: {exc}") from exc


class MosaicClient:
    def __init__(self, config: MosaicConfig, base_url: str = "http://127.0.0.1:8188") -> None:
        self.config = config
        bridge = UpscaleConfig(config.workflow_path, config.source_node, config.source_input,
                               config.output_node, config.output_input, config.output_subfolder,
                               config.timeout_seconds)
        self._client = ComfyUIClient(bridge, base_url)

    def mosaic(self, source: Path, destination: Path, output_prefix: str, strength: int) -> None:
        self.config.validate_strength(strength)
        workflow = copy.deepcopy(self._client._workflow)
        workflow[self.config.strength_node]["inputs"][self.config.strength_input] = strength
        original = self._client._workflow
        try:
            self._client._workflow = workflow
            self._client.upscale(source, destination, output_prefix)
        except UpscaleError as exc:
            raise MosaicError(str(exc).replace("拡大", "AutoMosaic")) from exc
        finally:
            self._client._workflow = original


def _verify_mosaic_png(path: Path, expected_size: tuple[int, int]) -> None:
    try:
        with Image.open(path) as image:
            if image.format != "PNG":
                raise MosaicError("AutoMosaic結果がPNG形式ではありません。")
            image.verify()
        with Image.open(path) as image:
            image.load()
            if image.size != expected_size:
                raise MosaicError(f"AutoMosaic後の画像寸法が不正です: expected={expected_size[0]}x{expected_size[1]}, actual={image.width}x{image.height}")
    except MosaicError:
        raise
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        raise MosaicError(f"AutoMosaic結果のPNGを読み込めません: {exc}") from exc


def execute_mosaic(*, client: MosaicClient, source_path: str, output_path: str,
                   expected_size: tuple[int, int], strength: int, job_id: str, image_id: int) -> str:
    source, destination = Path(source_path), Path(output_path)
    temp_root = destination.parent.parent / ".imagefinisher-tmp"
    image_temp = temp_root / job_id / str(image_id)
    staged = image_temp / destination.name
    committed = False
    if not source.is_file():
        raise MosaicError(f"入力原本が見つかりません: {source}")
    if destination.exists():
        raise MosaicError(f"完成ファイルがすでに存在します: {destination.name}")
    try:
        destination.parent.mkdir(parents=False, exist_ok=True)
        image_temp.mkdir(parents=True, exist_ok=False)
        client.mosaic(source, staged, f"{client.config.output_subfolder}/{job_id}_{image_id}", strength)
        _verify_mosaic_png(staged, expected_size)
        _exclusive_commit(staged, destination)
        committed = True
        _verify_mosaic_png(destination, expected_size)
        return str(destination)
    except FileExistsError as exc:
        raise MosaicError("画像専用の一時領域がすでに存在します。") from exc
    finally:
        if committed:
            try:
                _verify_mosaic_png(destination, expected_size)
            except MosaicError:
                destination.unlink(missing_ok=True)
        shutil.rmtree(image_temp, ignore_errors=True)
        try:
            (temp_root / job_id).rmdir()
            temp_root.rmdir()
        except OSError:
            pass


class PersonalSettings:
    def __init__(self, path: Path, default_strength: int) -> None:
        self.path, self.default_strength = path, default_strength

    def mosaic_strength(self) -> int:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8")).get("mosaic_strength")
            return value if isinstance(value, int) and not isinstance(value, bool) else self.default_strength
        except (OSError, json.JSONDecodeError, AttributeError):
            return self.default_strength

    def save_mosaic_strength(self, value: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, object] = {}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError):
            pass
        data["mosaic_strength"] = value
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)

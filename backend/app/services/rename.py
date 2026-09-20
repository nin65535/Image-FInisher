from __future__ import annotations

import errno
import os
import shutil
from pathlib import Path

from PIL import Image, UnidentifiedImageError


class RenameError(RuntimeError):
    """A safe, user-facing rename step failure."""


def _verify_png(path: Path, expected_size: tuple[int, int]) -> None:
    try:
        with Image.open(path) as image:
            if image.format != "PNG":
                raise RenameError("PNG形式ではありません。")
            image.verify()
        with Image.open(path) as image:
            image.load()
            if image.size != expected_size:
                raise RenameError(
                    f"画像寸法が変化しました: expected={expected_size[0]}x{expected_size[1]}, "
                    f"actual={image.width}x{image.height}"
                )
    except RenameError:
        raise
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        raise RenameError(f"PNGを読み込めません: {exc}") from exc


def _exclusive_commit(staged: Path, destination: Path) -> None:
    """Commit without ever replacing an existing destination."""
    try:
        os.link(staged, destination)
    except FileExistsError as exc:
        raise RenameError(f"完成ファイルがすでに存在します: {destination.name}") from exc
    except OSError as exc:
        if exc.errno not in {errno.EXDEV, errno.EPERM, errno.EACCES, errno.ENOTSUP}:
            raise RenameError(f"完成ファイルを確定できません: {exc}") from exc
        try:
            with staged.open("rb") as source, destination.open("xb") as target:
                shutil.copyfileobj(source, target)
                target.flush()
                os.fsync(target.fileno())
        except FileExistsError as nested:
            raise RenameError(f"完成ファイルがすでに存在します: {destination.name}") from nested
        except OSError as nested:
            destination.unlink(missing_ok=True)
            raise RenameError(f"完成ファイルを確定できません: {nested}") from nested


def execute_rename(
    *,
    source_path: str,
    output_path: str,
    expected_size: tuple[int, int],
    job_id: str,
    image_id: int,
) -> str:
    source = Path(source_path)
    destination = Path(output_path)
    output_folder = destination.parent
    temp_root = output_folder.parent / ".imagefinisher-tmp"
    image_temp = temp_root / job_id / str(image_id)
    staged = image_temp / destination.name
    committed = False

    if not source.is_file():
        raise RenameError(f"入力原本が見つかりません: {source}")
    if destination.exists():
        raise RenameError(f"完成ファイルがすでに存在します: {destination.name}")

    try:
        output_folder.mkdir(parents=False, exist_ok=True)
    except OSError as exc:
        raise RenameError(f"完成フォルダを作成できません: {exc}") from exc

    try:
        image_temp.mkdir(parents=True, exist_ok=False)
        shutil.copy2(source, staged)
        _verify_png(staged, expected_size)
        _exclusive_commit(staged, destination)
        committed = True
        _verify_png(destination, expected_size)
        return str(destination)
    except FileExistsError as exc:
        raise RenameError("画像専用の一時領域がすでに存在します。") from exc
    finally:
        if committed:
            try:
                _verify_png(destination, expected_size)
            except RenameError:
                destination.unlink(missing_ok=True)
        shutil.rmtree(image_temp, ignore_errors=True)
        job_temp = temp_root / job_id
        try:
            job_temp.rmdir()
            temp_root.rmdir()
        except OSError:
            pass

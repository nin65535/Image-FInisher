from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field


NAME_PATTERN = re.compile(r"^(?P<group>.+)_(?P<number>\d+)_$")
MAX_GROUP_SIZE = 9_999


class ValidationIssue(BaseModel):
    code: str
    message: str
    path: str | None = None


class PlannedImage(BaseModel):
    source_name: str
    source_path: str
    group: str
    output_name: str
    output_path: str
    width: int | None = None
    height: int | None = None


class GroupPlan(BaseModel):
    name: str
    count: int
    examples: list[PlannedImage]


class ScanResult(BaseModel):
    input_folder: str
    output_folder: str
    target_count: int
    excluded_count: int
    can_start: bool
    groups: list[GroupPlan]
    images: list[PlannedImage]
    errors: list[ValidationIssue]


def _same_path(left: Path, right: Path) -> bool:
    return str(left.resolve(strict=False)).casefold() == str(right.resolve(strict=False)).casefold()


def _is_root(path: Path) -> bool:
    resolved = path.resolve(strict=False)
    return resolved == Path(resolved.anchor)


def _dangerous_path_errors(input_folder: Path, output_folder: Path, app_root: Path) -> list[ValidationIssue]:
    errors: list[ValidationIssue] = []
    if _is_root(input_folder):
        errors.append(ValidationIssue(code="unsafe_input_path", message="ドライブルートは入力フォルダにできません。", path=str(input_folder)))
    if _same_path(input_folder, app_root):
        errors.append(ValidationIssue(code="unsafe_input_path", message="アプリルートは入力フォルダにできません。", path=str(input_folder)))
    if _is_root(output_folder) or _same_path(output_folder, input_folder) or _same_path(output_folder, app_root):
        errors.append(ValidationIssue(code="unsafe_output_path", message="完成フォルダが安全でない場所に解決されました。", path=str(output_folder)))
    return errors


def _preview(images: list[PlannedImage]) -> list[PlannedImage]:
    if len(images) <= 4:
        return images
    return [images[0], images[1], images[-2], images[-1]]


def _existing_names(folder: Path) -> set[str]:
    if not folder.is_dir():
        return set()
    try:
        return {entry.name.casefold() for entry in folder.iterdir() if entry.is_file()}
    except OSError:
        return set()


def scan_folder(input_folder: Path, *, app_root: Path) -> ScanResult:
    resolved_input = input_folder.expanduser().resolve(strict=False)
    output_folder = (resolved_input.parent / "finished").resolve(strict=False)
    errors: list[ValidationIssue] = []

    if not resolved_input.exists():
        errors.append(ValidationIssue(code="input_not_found", message="入力フォルダが見つかりません。", path=str(resolved_input)))
    elif not resolved_input.is_dir():
        errors.append(ValidationIssue(code="input_not_directory", message="入力パスはフォルダではありません。", path=str(resolved_input)))
    else:
        errors.extend(_dangerous_path_errors(resolved_input, output_folder, app_root))
        if output_folder.exists() and not output_folder.is_dir():
            errors.append(ValidationIssue(code="output_not_directory", message="完成先と同名のファイルが存在します。", path=str(output_folder)))

    entries: list[Path] = []
    if resolved_input.is_dir():
        try:
            entries = list(resolved_input.iterdir())
        except OSError as exc:
            errors.append(ValidationIssue(code="input_unreadable", message=f"入力フォルダを読み取れません: {exc}", path=str(resolved_input)))

    png_files = sorted(
        (entry for entry in entries if entry.is_file() and entry.suffix.casefold() == ".png"),
        key=lambda path: (path.name.casefold(), path.name),
    )
    excluded_count = len(entries) - len(png_files)
    if resolved_input.is_dir() and not png_files:
        errors.append(ValidationIssue(code="no_target_png", message="入力フォルダ直下に対象PNGがありません。", path=str(resolved_input)))
    grouped: dict[str, list[tuple[Path, int | None, int | None]]] = defaultdict(list)

    for source in png_files:
        match = NAME_PATTERN.fullmatch(source.stem)
        if match is None:
            errors.append(ValidationIssue(code="invalid_filename", message="PNG名が <グループ名>_<数字列>_ に一致しません。", path=str(source)))
            continue
        width: int | None = None
        height: int | None = None
        try:
            with Image.open(source) as image:
                image.verify()
            with Image.open(source) as image:
                width, height = image.size
                image.load()
        except (OSError, ValueError, UnidentifiedImageError) as exc:
            errors.append(ValidationIssue(code="unreadable_png", message=f"PNGを読み込めません: {exc}", path=str(source)))
        grouped[match.group("group")].append((source, width, height))

    existing_names = _existing_names(output_folder)
    images: list[PlannedImage] = []
    output_counts: Counter[str] = Counter()
    group_plans: list[GroupPlan] = []
    for group_name in sorted(grouped, key=lambda value: (value.casefold(), value)):
        members = grouped[group_name]
        if len(members) > MAX_GROUP_SIZE:
            errors.append(ValidationIssue(code="group_too_large", message=f"グループ「{group_name}」が9999枚を超えています。"))
        group_images: list[PlannedImage] = []
        for number, (source, width, height) in enumerate(members, start=1):
            output_name = f"{group_name}_{number:04d}.png"
            planned = PlannedImage(
                source_name=source.name,
                source_path=str(source),
                group=group_name,
                output_name=output_name,
                output_path=str(output_folder / output_name),
                width=width,
                height=height,
            )
            images.append(planned)
            group_images.append(planned)
            output_counts[output_name.casefold()] += 1
            if output_name.casefold() in existing_names:
                errors.append(ValidationIssue(code="output_exists", message=f"完成フォルダに同名ファイルがあります: {output_name}", path=str(output_folder / output_name)))
        group_plans.append(GroupPlan(name=group_name, count=len(group_images), examples=_preview(group_images)))

    for output_name, count in output_counts.items():
        if count > 1:
            errors.append(ValidationIssue(code="duplicate_output", message=f"同一バッチ内で完成名が重複します: {output_name}"))

    return ScanResult(
        input_folder=str(resolved_input),
        output_folder=str(output_folder),
        target_count=len(png_files),
        excluded_count=excluded_count,
        can_start=not errors and bool(png_files),
        groups=group_plans,
        images=images,
        errors=errors,
    )

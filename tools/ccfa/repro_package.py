"""Bundle the files and command that reproduce one reported result.

The bundle is a claim about real bytes and a real argv. The manifest records
the hash and size of every bundled file, the command as an argv array (with a
``{python}`` placeholder for later substitution), the declared dependency
file's hash, and the interpreter and platform that built it. Paths are always
relative to ``paper_root`` so usernames and out-of-tree files never leak into a
shared bundle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shlex
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from ccfa.cli import (
    ToolEnvironmentError,
    emit,
    save_text_atomically,
    tool_error,
)

MANIFEST_NAME = "MANIFEST.json"
FILES_DIR_NAME = "files"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return f"sha256:{digest}"


def _resolve_member(paper_root: Path, relpath: str) -> tuple[str, Path]:
    """Validate *relpath* against *paper_root* and return its posix form and path."""
    if Path(relpath).is_absolute():
        raise ValueError(f"清单路径必须是相对 paper_root 的相对路径: {relpath}")
    root = Path(paper_root).resolve()
    target = (Path(paper_root) / relpath).resolve()
    try:
        relative = target.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"清单路径不得逃逸 paper_root: {relpath}") from exc
    if not target.is_file():
        raise ValueError(f"清单文件不存在: {relpath}")
    return relative, target


def _file_entry(paper_root: Path, relpath: str) -> dict:
    relative, target = _resolve_member(paper_root, relpath)
    try:
        digest = sha256_of(target)
        size = target.stat().st_size
    except OSError as exc:
        raise ValueError(f"无法读取清单文件 {relative}: {exc}") from exc
    return {"path": relative, "sha256": digest, "size": size}


def build_manifest(
    paper_root: Path,
    files: list[str],
    command: list[str],
    requirements: str | None,
    notes: str | None,
) -> dict:
    entries = [_file_entry(paper_root, relpath) for relpath in files]
    entries.sort(key=lambda item: item["path"])

    requirement_entry = None
    if requirements is not None:
        relative, target = _resolve_member(paper_root, requirements)
        try:
            digest = sha256_of(target)
        except OSError as exc:
            raise ValueError(f"无法读取依赖文件 {relative}: {exc}") from exc
        requirement_entry = {"path": relative, "sha256": digest}

    return {
        "version": 1,
        "created_at": _now_iso(),
        "command": list(command),
        "files": entries,
        "requirements": requirement_entry,
        "notes": notes,
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def create_bundle(
    paper_root: Path,
    out_dir: Path,
    manifest: dict,
    *,
    force: bool = False,
) -> dict:
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise ValueError("清单 version 必须是 1")
    items = manifest.get("files")
    if not isinstance(items, list):
        raise ValueError("清单 files 必须是数组")
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("清单 files 的每个条目都必须包含字符串 path")
    requirement = manifest.get("requirements")
    if requirement is not None:
        if not isinstance(requirement, dict) or not isinstance(requirement.get("path"), str):
            raise ValueError("清单 requirements 必须包含字符串 path")

    paper_root = Path(paper_root)
    out_dir = Path(out_dir)
    if out_dir.exists():
        if not force:
            raise ValueError(f"bundle 目录已存在: {out_dir}（如需覆盖请显式使用 --force）")
        try:
            shutil.rmtree(out_dir)
        except OSError as exc:
            raise ValueError(f"无法删除已有 bundle 目录 {out_dir}: {exc}") from exc

    try:
        files_dir = out_dir / FILES_DIR_NAME
        files_dir.mkdir(parents=True, exist_ok=True)
        for item in items:
            relative, source = _resolve_member(paper_root, item["path"])
            destination = files_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

        if requirement is not None:
            relative, source = _resolve_member(paper_root, requirement["path"])
            destination = files_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

        payload = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        save_text_atomically(out_dir / MANIFEST_NAME, payload, description="清单")
    except OSError as exc:
        raise ValueError(f"无法构建 bundle {out_dir}: {exc}") from exc
    return manifest


def load_manifest(bundle_dir: Path) -> dict:
    path = Path(bundle_dir) / MANIFEST_NAME
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"无法读取清单 {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"清单不是合法 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("清单顶层必须是对象")
    if "version" not in data:
        raise ValueError("清单缺少 version 字段")
    if data["version"] != 1:
        raise ValueError(f"清单 version 不支持: {data['version']}")
    return data


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="打包可复现的结果文件与命令")
    parser.add_argument("--paper-root", required=True)
    sub = parser.add_subparsers(dest="subcommand", required=True)

    bundle = sub.add_parser("bundle", help="构建 bundle 目录与 MANIFEST.json")
    bundle.add_argument("--files", nargs="+", required=True)
    bundle.add_argument("--command", required=True)
    bundle.add_argument("--requirements")
    bundle.add_argument("--notes")
    bundle.add_argument("--out", required=True)
    bundle.add_argument("--force", action="store_true")

    args = parser.parse_args(argv[1:])
    try:
        try:
            command = shlex.split(args.command, posix=True)
        except ValueError as exc:
            raise ValueError(f"--command 无法解析为 argv: {exc}") from exc
        if not command:
            raise ValueError("--command 不能为空")

        manifest = build_manifest(
            Path(args.paper_root),
            list(args.files),
            command,
            args.requirements,
            args.notes,
        )
        create_bundle(Path(args.paper_root), Path(args.out), manifest, force=args.force)
    except (ValueError, ToolEnvironmentError) as exc:
        return tool_error(str(exc))
    return emit([], [])


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))

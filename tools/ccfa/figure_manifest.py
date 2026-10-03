"""Validate figures/manifest.yaml against the files it claims to describe.

The manifest is what makes a figure traceable: which run produced it, which
script generated it, and where the text references it. A manifest that has
drifted from reality is worse than no manifest, so every claim is checked
against bytes rather than trusted.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from ccfa.cli import Problem
from ccfa.figurebytes import JPEG_SUFFIXES, sniff
from ccfa.run_log import record_path


def load_manifest(path: Path) -> list[dict]:
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取 manifest {path}: {exc}") from exc
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"manifest 解析失败: {exc}") from exc
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError("manifest 顶层必须是列表")
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"manifest 第 {index} 项必须是对象")
    return data


def _sha256(path: Path) -> str | None:
    try:
        return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _blank(value: object) -> bool:
    return value is None or not str(value).strip()


def _resolve_figure(item: dict, paper_root: Path) -> tuple[Path, Problem | None]:
    explicit = item.get("file")
    if explicit:
        return paper_root / str(explicit), None
    name = str(item.get("name", ""))
    suffix = str(item.get("bytes_format", "")).lstrip(".")
    fallback = paper_root / "figures" / f"{name}.{suffix}"
    advisory = Problem(
        "manifest-missing-file",
        str(fallback),
        None,
        f"manifest 条目 {name} 缺 file 字段，已回退到约定路径；建议显式补写",
    )
    return fallback, advisory


def check_manifest(
    items: list[dict], paper_root: Path
) -> tuple[list[Problem], list[Problem]]:
    paper_root = Path(paper_root)
    problems: list[Problem] = []
    advisories: list[Problem] = []
    for item in items:
        name = str(item.get("name", "<unnamed>"))
        figure, fallback_advisory = _resolve_figure(item, paper_root)
        if fallback_advisory is not None:
            advisories.append(fallback_advisory)

        missing_provenance = [
            field
            for field in ("generator", "generator_hash")
            if _blank(item.get(field))
        ]
        if missing_provenance:
            fields = "、".join(missing_provenance)
            problems.append(
                Problem(
                    "figure-provenance-missing",
                    str(figure),
                    None,
                    f"条目 {name} 缺必填字段 {fields}，请补写生成脚本及其哈希",
                )
            )

        source_run_ids = item.get("source_run_ids")
        if not isinstance(source_run_ids, list) or not source_run_ids:
            problems.append(
                Problem(
                    "figure-provenance-missing",
                    str(figure),
                    None,
                    f"条目 {name} 缺可追溯的 source_run_ids（必须是非空列表）",
                )
            )
        else:
            log_dir = paper_root / "experiments" / "log"
            for run_id in source_run_ids:
                run_label = str(run_id)
                run_path = record_path(log_dir, run_label)
                if not run_path.is_file():
                    problems.append(
                        Problem(
                            "figure-source-run",
                            str(run_path),
                            None,
                            f"条目 {name} 的 source_run_ids 指向不存在的运行记录: {run_label}",
                        )
                    )

        source_data = item.get("source_data")
        if not isinstance(source_data, str) or not source_data.strip():
            problems.append(
                Problem(
                    "figure-source-data",
                    str(figure),
                    None,
                    f"条目 {name} 缺 source_data（相对 paper root 的非空路径）",
                )
            )
        else:
            source_path = paper_root / source_data
            if not source_path.is_file():
                problems.append(
                    Problem(
                        "figure-source-data",
                        str(source_path),
                        None,
                        f"条目 {name} 的 source_data 文件不存在: {source_data}",
                    )
                )

        if item.get("manual_edit") is True and _blank(item.get("manual_edit_note")):
            problems.append(
                Problem(
                    "figure-manual-edit",
                    str(figure),
                    None,
                    f"条目 {name} 标记 manual_edit: true，但缺 manual_edit_note",
                )
            )

        if not figure.is_file():
            problems.append(
                Problem("figure-missing", str(figure), None, f"条目 {name} 的交付图不存在")
            )
        else:
            declared_raw = str(item.get("bytes_format", "")).lower().lstrip(".")
            actual = sniff(figure)
            if (
                declared_raw
                and actual is not None
                and actual != "." + declared_raw
                and not (actual == ".jpg" and "." + declared_raw in JPEG_SUFFIXES)
            ):
                problems.append(
                    Problem(
                        "figure-manifest-format",
                        str(figure),
                        None,
                        f"条目 {name} 声明 bytes_format={declared_raw}，实际字节是 {actual.lstrip('.')}",
                    )
                )

        generator = item.get("generator")
        expected_hash = item.get("generator_hash")
        if generator and expected_hash:
            generator_path = paper_root / str(generator)
            actual_hash = _sha256(generator_path)
            if actual_hash is None:
                problems.append(
                    Problem(
                        "figure-hash",
                        str(generator_path),
                        None,
                        f"条目 {name} 的生成脚本不存在: {generator}",
                    )
                )
            elif actual_hash != str(expected_hash):
                problems.append(
                    Problem(
                        "figure-hash",
                        str(generator_path),
                        None,
                        f"条目 {name} 的生成脚本哈希不符（记录 {expected_hash}，实际 {actual_hash}）",
                    )
                )

        if not item.get("referenced_in"):
            advisories.append(
                Problem(
                    "unreferenced-figure",
                    str(figure),
                    None,
                    f"条目 {name} 未记录正文引用位置",
                )
            )
    return problems, advisories

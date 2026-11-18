"""Check pinned upstream reference repositories for new commits.

The reference audit is deliberately a drift detector, not an automatic
alignment claim. A changed upstream commit means a human must read the diff and
record which local contract, if any, needs to change.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

from ccfa.cli import Problem, emit, tool_error


REGISTRY = Path("docs/reference-registry.yaml")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_RE = re.compile(r"^[^/\s]+/[^/\s]+$")
TRACK_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
REQUIRED_FIELDS = ("id", "repository", "pinned_commit", "source_doc")


def load_registry(repo_root: Path) -> tuple[list[dict], list[Problem]]:
    path = Path(repo_root) / REGISTRY
    problems: list[Problem] = []
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return [], [
            Problem(
                "reference-registry-unreadable",
                str(path),
                None,
                f"无法读取 reference registry: {exc}",
            )
        ]
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return [], [
            Problem(
                "reference-registry-invalid",
                str(path),
                None,
                "reference registry 必须是 version: 1 的对象",
            )
        ]
    projects = payload.get("projects")
    if not isinstance(projects, list) or not projects:
        return [], [
            Problem(
                "reference-registry-invalid",
                str(path),
                None,
                "projects 必须是非空数组",
            )
        ]

    normalized: list[dict] = []
    seen: set[str] = set()
    root = Path(repo_root).resolve()
    for index, item in enumerate(projects):
        if not isinstance(item, dict):
            problems.append(
                Problem(
                    "reference-registry-invalid",
                    str(path),
                    None,
                    f"projects[{index}] 必须是对象",
                )
            )
            continue
        missing = [field for field in REQUIRED_FIELDS if not item.get(field)]
        if missing:
            problems.append(
                Problem(
                    "reference-registry-invalid",
                    str(path),
                    None,
                    f"projects[{index}] 缺少字段: {', '.join(missing)}",
                )
            )
            continue
        project_id = str(item["id"])
        repository = str(item["repository"])
        pinned = str(item["pinned_commit"]).lower()
        source_doc = str(item["source_doc"])
        if project_id in seen:
            problems.append(
                Problem(
                    "reference-registry-duplicate",
                    str(path),
                    None,
                    f"重复 project id: {project_id}",
                )
            )
            continue
        seen.add(project_id)
        if not REPOSITORY_RE.match(repository):
            problems.append(
                Problem(
                    "reference-registry-invalid",
                    str(path),
                    None,
                    f"{project_id}: repository 必须是 owner/name",
                )
            )
            continue
        if not SHA_RE.match(pinned):
            problems.append(
                Problem(
                    "reference-registry-invalid",
                    str(path),
                    None,
                    f"{project_id}: pinned_commit 必须是 40 位 SHA-1",
                )
            )
            continue
        track_tag = item.get("track_tag")
        if track_tag is not None and (
            not isinstance(track_tag, str) or not TRACK_TAG_RE.match(track_tag)
        ):
            problems.append(
                Problem(
                    "reference-registry-invalid",
                    str(path),
                    None,
                    f"{project_id}: track_tag 必须是安全的 tag 名称",
                )
            )
            continue
        try:
            (root / source_doc).resolve().relative_to(root)
        except ValueError:
            problems.append(
                Problem(
                    "reference-registry-invalid",
                    str(path),
                    None,
                    f"{project_id}: source_doc 必须位于仓库内",
                )
            )
            continue
        if not (root / source_doc).is_file():
            problems.append(
                Problem(
                    "reference-registry-invalid",
                    str(path),
                    None,
                    f"{project_id}: source_doc 不存在: {source_doc}",
                )
            )
            continue
        normalized.append(
            {
                "id": project_id,
                "repository": repository,
                "pinned_commit": pinned,
                "source_doc": source_doc,
                "note": str(item.get("note") or ""),
                "track_tag": track_tag,
            }
        )
    return normalized, problems


def fetch_latest_commit(
    repository: str,
    *,
    token: str | None = None,
    opener=None,
    timeout: float = 20.0,
) -> str:
    opener = opener or urllib.request.urlopen
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ccfa-reference-audit",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/commits?per_page=1",
        headers=headers,
    )
    try:
        with opener(request, timeout=timeout) as response:
            status = getattr(response, "status", None)
            if status is None:
                status = response.getcode()
            raw = response.read()
    except (OSError, urllib.error.URLError) as exc:
        raise ValueError(f"无法访问 GitHub API: {repository}: {exc}") from exc
    if status != 200:
        raise ValueError(f"GitHub API 返回 {status}: {repository}")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"GitHub API 响应不是 JSON: {repository}") from exc
    if not isinstance(payload, list) or not payload:
        raise ValueError(f"GitHub API 未返回 commit: {repository}")
    latest = payload[0].get("sha") if isinstance(payload[0], dict) else None
    if not isinstance(latest, str) or not SHA_RE.match(latest):
        raise ValueError(f"GitHub API 返回了非法 commit: {repository}")
    return latest


def fetch_tagged_commit(
    repository: str,
    tag: str,
    *,
    token: str | None = None,
    opener=None,
    timeout: float = 20.0,
) -> str:
    """Resolve a release tag to a commit SHA, following annotated tags.

    Active upstreams publish many commits between releases. Tracking a tag
    keeps the audit meaningful (a human reviews each new release) without
    turning every unrelated upstream commit into a drift alarm.
    """
    if not TRACK_TAG_RE.match(tag):
        raise ValueError(f"非法 tag 名称: {repository}:{tag}")
    opener = opener or urllib.request.urlopen
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ccfa-reference-audit",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    def get_object(path: str) -> dict:
        request = urllib.request.Request(
            f"https://api.github.com/repos/{repository}{path}", headers=headers
        )
        try:
            with opener(request, timeout=timeout) as response:
                status = getattr(response, "status", None)
                if status is None:
                    status = response.getcode()
                raw = response.read()
        except (OSError, urllib.error.URLError) as exc:
            raise ValueError(f"无法访问 GitHub API: {repository}:{tag}: {exc}") from exc
        if status != 200:
            raise ValueError(f"GitHub API 返回 {status}: {repository}:{tag}")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"GitHub API 响应不是 JSON: {repository}:{tag}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"GitHub API 响应不是对象: {repository}:{tag}")
        return payload

    ref_object = get_object(f"/git/ref/tags/{tag}").get("object")
    if not isinstance(ref_object, dict):
        raise ValueError(f"tag 无 object 字段: {repository}:{tag}")
    kind = ref_object.get("type")
    sha = ref_object.get("sha")
    if kind == "tag":
        annotated = get_object(f"/git/tags/{sha}").get("object")
        if not isinstance(annotated, dict):
            raise ValueError(f"annotated tag 无 object 字段: {repository}:{tag}")
        kind = annotated.get("type")
        sha = annotated.get("sha")
    if kind != "commit" or not isinstance(sha, str) or not SHA_RE.match(sha):
        raise ValueError(f"tag 未指向合法 commit: {repository}:{tag}")
    return sha


def audit(
    repo_root: Path,
    *,
    token: str | None = None,
    offline: bool = False,
    fetch=None,
    tag_fetch=None,
) -> dict:
    repo_root = Path(repo_root).resolve()
    projects, problems = load_registry(repo_root)
    if problems:
        return {"projects": [], "problems": problems}
    fetch = fetch or fetch_latest_commit
    tag_fetch = tag_fetch or fetch_tagged_commit
    rows: list[dict] = []
    for project in projects:
        latest = None
        if not offline:
            try:
                if project.get("track_tag"):
                    latest = tag_fetch(
                        project["repository"], project["track_tag"], token=token
                    )
                else:
                    latest = fetch(project["repository"], token=token)
            except (OSError, ValueError) as exc:
                problems.append(
                    Problem(
                        "reference-audit-fetch-failed",
                        project["repository"],
                        None,
                        str(exc),
                    )
                )
        changed = latest is not None and latest != project["pinned_commit"]
        if changed:
            problems.append(
                Problem(
                    "reference-audit-stale",
                    project["repository"],
                    None,
                    (
                        f"{project['id']} 有新 commit: "
                        f"{project['pinned_commit'][:12]} -> {latest[:12]}；"
                        f"请阅读 diff 并更新 {project['source_doc']}"
                    ),
                )
            )
        rows.append(
            {
                **project,
                "latest_commit": latest,
                "changed": changed,
                "checked": latest is not None,
            }
        )
    return {"projects": rows, "problems": problems}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="检查参照仓库是否已有未审计的新 commit")
    parser.add_argument("action", choices=("check", "list"), nargs="?", default="check")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--out")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.action == "list":
            projects, problems = load_registry(Path(args.repo_root))
            if problems:
                return emit(problems, [])
            for project in projects:
                tracked = (
                    f" tag={project['track_tag']}" if project.get("track_tag") else ""
                )
                print(
                    f"{project['id']} {project['repository']} "
                    f"{project['pinned_commit']}{tracked}"
                )
            return 0

        report = audit(
            Path(args.repo_root),
            token=args.token,
            offline=args.offline,
        )
        lines = ["# Reference Audit", ""]
        for row in report["projects"]:
            latest = row.get("latest_commit") or "not-checked"
            lines.append(
                f"- `{row['id']}`: pinned `{row['pinned_commit'][:12]}`; "
                f"latest `{latest[:12]}`; changed={row['changed']}"
            )
        text = (
            "\n".join(lines) + "\n"
            if args.format == "markdown"
            else json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        )
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
        problems = report["problems"]
        if not args.out:
            print(text, end="")
        if problems:
            for problem in problems:
                print(
                    f"{problem.path}: {problem.code}: {problem.message}",
                    file=sys.stderr,
                )
            return 1 if args.strict else 0
        return 0
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))

"""Actionable local checks before a connector-backed job acquires a worker."""

from __future__ import annotations

import re
from pathlib import Path


def stream_start_issues(project: dict) -> list[dict[str, str]]:
    if project["runtime"]["mode"] != "stream" or project.get("static_inputs"):
        return []
    issues = []
    if re.fullmatch(r"[A-Za-z0-9_.-]+", project["graph"]["name"]) is None:
        issues.append(
            {
                "path": "graph.name",
                "code": "invalid_stream_name",
                "message": (
                    "Stream graph names must use ASCII letters, numbers, '.', '_' "
                    "or '-' for checkpoint storage. Edit Graph name in the "
                    "stream settings."
                ),
            }
        )
    for index, source in enumerate(project.get("sources", [])):
        connector = source["connector"]
        if (connector["provider"], connector["name"]) != (
            "calc-flow-connectors",
            "file",
        ):
            continue
        raw_path = source["options"].get("path")
        if not isinstance(raw_path, str):
            continue
        path = Path(raw_path)
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            issues.append(
                {
                    "path": f"sources[{index}].options.path",
                    "code": "invalid_file_source",
                    "message": (
                        f"File source {source['binding']!r} needs an existing "
                        f"regular file or directory at {raw_path!r}. "
                        "Set Source Options.path to your input."
                    ),
                }
            )
    return issues

from __future__ import annotations

import json
from importlib.metadata import version
from pathlib import Path

from calc_flow import project_json_schema

from calc_flow_studio.app import create_app
from calc_flow_studio.run_manager import RunManager


def main() -> None:
    web_ui = Path(__file__).resolve().parents[1]
    constraints = (web_ui / "api-schema-constraints.txt").read_text(encoding="utf-8")
    expected_versions = dict(line.split("==", 1) for line in constraints.splitlines())
    for package, expected in expected_versions.items():
        actual = version(package)
        if actual != expected:
            raise SystemExit(
                f"API snapshots require {package}=={expected} (found {actual}). "
                "Run npm run sync:api from web-ui."
            )
    app = create_app(run_manager=RunManager(use_processes=False))
    (web_ui / "openapi.json").write_text(
        json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (web_ui.parent / "schemas" / "project-v3.schema.json").write_text(
        json.dumps(json.loads(project_json_schema()), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

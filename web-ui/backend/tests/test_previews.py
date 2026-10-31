from __future__ import annotations

import time

from studio_client import TestClient

from calc_flow_studio.app import create_app


def _project() -> dict:
    return {
        "format_version": 3,
        "id": "batch_preview",
        "name": "Batch preview",
        "runtime": {"mode": "batch", "options": {}},
        "graph": {
            "name": "Totals",
            "nodes": [
                {
                    "id": "calculate",
                    "operator": {"kind": "expression", "expression": "total = a + b"},
                }
            ],
        },
        "data_sources": [
            {
                "id": "sample",
                "input": "input",
                "format": "inline_json",
                "data": [{"a": 1, "b": 2}, {"a": 3, "b": 4}],
            }
        ],
    }


def test_batch_preview_runs_saved_data_in_a_worker(tmp_path):
    app = create_app(project_directory=tmp_path / "projects")
    with TestClient(app) as client:
        assert client.post("/api/v3/projects", json=_project()).status_code == 201
        submitted = client.post(
            "/api/v3/previews", json={"project_id": "batch_preview"}
        )
        assert submitted.status_code == 202, submitted.text
        preview_id = submitted.json()["id"]
        deadline = time.monotonic() + 8
        while True:
            fetched = client.get(f"/api/v3/previews/{preview_id}")
            assert fetched.status_code == 200, fetched.text
            preview = fetched.json()
            if preview["status"] not in {"pending", "running"}:
                break
            assert time.monotonic() < deadline, preview
            time.sleep(0.05)
        assert preview["status"] == "completed", preview
        assert preview["result"]["outputs"]["output"]["rows"] == [
            {"a": 1, "b": 2, "total": 3},
            {"a": 3, "b": 4, "total": 7},
        ]
        assert (
            client.delete(f"/api/v3/previews/{preview_id}").json()["status"]
            == "completed"
        )


def test_preview_missing_resources_and_invalid_inputs_are_reported(tmp_path):
    app = create_app(project_directory=tmp_path / "projects")
    with TestClient(app) as client:
        assert (
            client.post("/api/v3/previews", json={"project_id": "missing"}).status_code
            == 404
        )
        assert client.get("/api/v3/previews/missing").status_code == 404
        assert client.delete("/api/v3/previews/missing").status_code == 404
        project = _project()
        project["runtime"]["options"] = {"max_rows": 1}
        assert client.post("/api/v3/projects", json=project).status_code == 201
        failed = client.post("/api/v3/previews", json={"project_id": "batch_preview"})
        assert failed.status_code == 422, failed.text

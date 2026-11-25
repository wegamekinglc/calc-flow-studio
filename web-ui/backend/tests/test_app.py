from __future__ import annotations

import json
from copy import copy
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest
from calc_flow import (
    CalcFlowError,
    FileProjectStore,
    PipelineBuilder,
    ProjectDocument,
    ProviderOption,
    ProviderOptionsSchema,
    Runtime,
    project_json_schema,
)
from fastapi.testclient import TestClient as NativeTestClient
from starlette.requests import Request as StarletteRequest
from studio_client import TestClient

import calc_flow_studio.routes as routes_module
from calc_flow_studio.app import API_PREFIX, create_app, validate_bind_host
from calc_flow_studio.models import RunEvent, RunResponse, RunStatus
from calc_flow_studio.run_manager import CapabilitySnapshotError, RunManagerError


def test_local_api_rejects_rebound_hosts_origins_and_missing_launch_tokens() -> None:
    app = create_app(run_manager=FakeManager())
    with NativeTestClient(app, base_url="http://127.0.0.1") as client:
        assert (
            client.get(
                "/api/v3/catalog", headers={"Host": "rebound.example"}
            ).status_code
            == 400
        )
        assert client.post("/api/v3/projects", json={}).status_code == 403
        assert (
            client.get(
                "/api/v3/session", headers={"Origin": "http://rebound.example"}
            ).status_code
            == 403
        )
        token_response = client.get("/api/v3/session")
        assert token_response.status_code == 200
        token = token_response.json()["token"]
        assert isinstance(token, str) and len(token) >= 32
        assert (
            client.post(
                "/api/v3/projects",
                json={},
                headers={"X-Calc-Flow-Session": token},
            ).status_code
            == 422
        )
        preflight = client.options(
            "/api/v3/projects",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-Calc-Flow-Session, Content-Type",
            },
        )
        assert preflight.status_code == 200
        assert (
            client.post(
                "/api/v3/projects",
                json={},
                headers={
                    "X-Calc-Flow-Session": token,
                    "Origin": "http://127.0.0.1:5173",
                },
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v3/projects",
                json={},
                headers={
                    "X-Calc-Flow-Session": token,
                    "Origin": "http://rebound.example",
                },
            ).status_code
            == 403
        )

    second_app = create_app(run_manager=FakeManager())
    with NativeTestClient(second_app, base_url="http://127.0.0.1") as client:
        assert (
            client.post(
                "/api/v3/projects",
                json={},
                headers={"X-Calc-Flow-Session": token},
            ).status_code
            == 403
        )


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize("token", [b"\xe9", b"\xc3\xa9"], ids=["latin1", "utf8"])
def test_local_api_rejects_non_ascii_launch_tokens(
    tmp_path: Path, method: str, token: bytes
) -> None:
    app = create_app(
        project_directory=tmp_path / "projects",
        checkpoint_directory=tmp_path / "checkpoints",
        run_manager=FakeManager(),
    )
    with NativeTestClient(
        app, base_url="http://127.0.0.1", raise_server_exceptions=False
    ) as client:
        response = client.request(
            method,
            "/api/v3/projects",
            json={},
            headers={b"X-Calc-Flow-Session": token},
        )
    assert response.status_code == 403
    assert response.json() == {"detail": "Invalid launch token"}


def test_ipv6_loopback_host_remains_allowed() -> None:
    app = create_app(run_manager=FakeManager(), bind_host="::1")
    with NativeTestClient(app, base_url="http://127.0.0.1") as client:
        assert (
            client.get("/api/v3/catalog", headers={"Host": "[::1]:8765"}).status_code
            == 200
        )
        assert (
            client.get(
                "/api/v3/catalog",
                headers={"Host": "[0:0:0:0:0:0:0:1]:8765"},
            ).status_code
            == 200
        )
        for authority in (
            "[::1].evil",
            "[::1]:99999",
            "[::1]:0",
            "[::1]:not-a-port",
            "[::1%eth0]",
            "localhost:99999",
            "127.0.0.1:99999",
        ):
            assert (
                client.get("/api/v3/catalog", headers={"Host": authority}).status_code
                == 400
            )
        assert (
            client.get(
                "/api/v3/catalog",
                headers=[("Host", "rebound.example"), ("Host", "[::1]:8765")],
            ).status_code
            == 400
        )


def _project(
    project_id: str = "project_alpha", *, name: str = "Alpha"
) -> dict[str, object]:
    return {
        "format_version": 3,
        "id": project_id,
        "name": name,
        "description": "A v3 project",
        "runtime": {"mode": "batch", "options": {}},
        "graph": {
            "name": f"{name} pipeline",
            "nodes": [
                {
                    "id": "calculate",
                    "operator": {
                        "kind": "expression",
                        "expression": "result = value + 1",
                    },
                }
            ],
        },
        "data_sources": [
            {
                "id": "sample",
                "input": "input",
                "format": "inline_json",
                "data": [{"value": 1}],
            }
        ],
    }


class FakeManager:
    def __init__(self) -> None:
        self.shutdown_calls = 0
        self.wait_calls: list[tuple[str, int, float]] = []
        self.run = RunResponse.model_validate(
            {
                "id": "run_1",
                "project_id": "project_alpha",
                "status": RunStatus.RUNNING,
                "created_at": datetime(2026, 1, 1, tzinfo=UTC),
                "started_at": datetime(2026, 1, 1, tzinfo=UTC),
            }
        )

    def submit(self, project: ProjectDocument, request: object) -> RunResponse:
        assert project.root["id"] == "project_alpha"
        assert request is not None
        return self.run

    def get(self, run_id: str) -> RunResponse:
        if run_id != self.run.id:
            raise KeyError(run_id)
        return self.run

    def wait_for_events(
        self, run_id: str, *, after_sequence: int, timeout: float
    ) -> tuple[tuple[RunEvent, ...], RunStatus]:
        self.wait_calls.append((run_id, after_sequence, timeout))
        if len(self.wait_calls) == 1:
            return (), RunStatus.RUNNING
        event = RunEvent(
            sequence=after_sequence + 1,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            type="completed",
            message="Run completed",
        )
        return (event,), RunStatus.COMPLETED

    def cancel(self, run_id: str) -> RunResponse:
        current = self.get(run_id)
        return RunResponse.model_validate(
            {
                **current.model_dump(),
                "status": RunStatus.CANCELLED,
                "finished_at": datetime(2026, 1, 1, tzinfo=UTC),
            }
        )

    def shutdown(self) -> None:
        self.shutdown_calls += 1


def _client(tmp_path: Path, **kwargs: Any) -> TestClient:
    return TestClient(
        create_app(
            project_directory=tmp_path / "projects",
            checkpoint_directory=tmp_path / "checkpoints",
            **kwargs,
        )
    )


def _create(client: TestClient, project: dict[str, object] | None = None):
    return client.post(f"{API_PREFIX}/projects", json=project or _project())


def test_openapi_contains_only_v3_routes_and_exact_rust_schema(tmp_path) -> None:
    app = create_app(
        project_directory=tmp_path / "projects",
        checkpoint_directory=tmp_path / "checkpoints",
    )
    direct_openapi = app.openapi()
    with _client(tmp_path) as client:
        response = client.get("/openapi.json")
        schema = client.get(f"{API_PREFIX}/schema/project").json()

    assert response.status_code == 200
    openapi = response.json()
    assert openapi == direct_openapi
    assert API_PREFIX == "/api/v3"
    assert f"{API_PREFIX}/catalog" in openapi["paths"]
    assert f"{API_PREFIX}/schema/project" in openapi["paths"]
    assert f"{API_PREFIX}/projects/{{project_id}}" in openapi["paths"]
    assert "post" in openapi["paths"][f"{API_PREFIX}/previews"]
    assert "post" in openapi["paths"][f"{API_PREFIX}/jobs"]
    assert f"{API_PREFIX}/jobs/{{job_id}}/events" in openapi["paths"]
    assert not any("/runs" in path for path in openapi["paths"])
    assert not any(path.startswith("/api/v2/") for path in openapi["paths"])
    assert schema == json.loads(project_json_schema())
    assert schema["properties"]["format_version"]["const"] == 3

    # The v2 table backend selector must stay dead: no part of the project
    # schema may mention "backend" except the static array declaration
    # descriptor, whose `backend` field names the array provider (SCE-11).
    without_static_defs = dict(schema)
    without_static_defs["$defs"] = {
        name: definition
        for name, definition in schema["$defs"].items()
        if name != "StaticInputSpec"
    }
    assert "backend" not in json.dumps(without_static_defs).lower()

    def resolve_json_pointer(document: object, pointer: str) -> object:
        assert pointer.startswith("#/")
        current = document
        for encoded_part in pointer[2:].split("/"):
            part = encoded_part.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict):
                current = current[part]
            else:
                assert isinstance(current, list)
                current = current[int(part)]
        return current

    def schema_references(value: object):
        if isinstance(value, dict):
            reference = value.get("$ref")
            if isinstance(reference, str):
                yield reference
            for item in value.values():
                yield from schema_references(item)
        elif isinstance(value, list):
            for item in value:
                yield from schema_references(item)

    def normalize_component_references(value: object, component_name: str) -> object:
        if isinstance(value, dict):
            normalized = {
                key: normalize_component_references(item, component_name)
                for key, item in value.items()
            }
            reference = normalized.get("$ref")
            component_prefix = f"#/components/schemas/{component_name}/$defs/"
            if isinstance(reference, str) and reference.startswith(component_prefix):
                normalized["$ref"] = "#/$defs/" + reference.removeprefix(
                    component_prefix
                )
            return normalized
        if isinstance(value, list):
            return [
                normalize_component_references(item, component_name) for item in value
            ]
        return value

    for component_name in ("ProjectCreateRequest", "ProjectDocument"):
        component = openapi["components"]["schemas"][component_name]
        assert normalize_component_references(component, component_name) == schema
        assert component["$defs"]["NodeSpec"]["properties"]["operator"]["$ref"] == (
            f"#/components/schemas/{component_name}/$defs/OperatorSpec"
        )
        assert "JSONValue" not in json.dumps(component)

    for reference in schema_references(openapi):
        assert resolve_json_pointer(openapi, reference)

    paths = openapi["paths"]
    collection = paths[f"{API_PREFIX}/projects"]
    single = paths[f"{API_PREFIX}/projects/{{project_id}}"]
    import_operation = paths[f"{API_PREFIX}/projects/import"]["post"]
    for operation in (collection["post"], single["put"]):
        body = operation["requestBody"]
        assert body["required"] is True
        assert body["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ProjectCreateRequest"
        }
    for operation, status in (
        (collection["post"], "201"),
        (single["get"], "200"),
        (single["put"], "200"),
        (import_operation, "201"),
    ):
        assert operation["responses"][status]["content"]["application/json"][
            "schema"
        ] == {"$ref": "#/components/schemas/ProjectDocument"}


def test_catalog_is_exact_runtime_metadata_and_validation_uses_canonical_json(
    tmp_path,
) -> None:
    class FakeRuntime:
        def __init__(self) -> None:
            self.documents: list[str] = []

        def catalog(self) -> list[dict[str, object]]:
            return [{"kind": "test", "name": "only-runtime-metadata"}]

        def validation_report(self, project_json: str) -> dict[str, object]:
            self.documents.append(project_json)
            return {"valid": True, "issues": [], "fingerprint": "fake"}

    runtime = FakeRuntime()
    with _client(tmp_path, runtime=runtime) as client:
        assert _create(client).status_code == 201
        catalog = client.get(f"{API_PREFIX}/catalog")
        validation = client.post(f"{API_PREFIX}/projects/project_alpha/validate")

    assert catalog.json() == [{"kind": "test", "name": "only-runtime-metadata"}]
    assert validation.json() == {
        "kind": "valid",
        "valid": True,
        "issues": [],
        "fingerprint": "fake",
    }
    assert len(runtime.documents) == 2
    assert [json.loads(document)["id"] for document in runtime.documents] == [
        "project_alpha",
        "project_alpha",
    ]


def test_capabilities_route_exposes_the_typed_runtime_session_snapshot(
    tmp_path,
) -> None:
    runtime = Runtime()
    runtime.register_provider(
        "test",
        "identity",
        "1",
        lambda batch, _options: batch,
        options_schema=ProviderOptionsSchema(
            fields=(ProviderOption("flag", "boolean", required=True),)
        ),
    )
    snapshot = runtime.capabilities()

    with _client(tmp_path, runtime=runtime) as client:
        response = client.get(f"{API_PREFIX}/capabilities")
        catalog = client.get(f"{API_PREFIX}/catalog")
        openapi = client.get("/openapi.json").json()

    assert response.status_code == 200, response.text
    document = response.json()
    assert document["schemaVersion"] == 3
    capabilities = document["runtime"]
    assert capabilities["packageVersion"] == version("calc-flow-python")
    assert capabilities["projectFormatVersions"] == [3]
    assert capabilities["scope"] == {
        "kind": "runtimeSession",
        "sessionId": snapshot.scope.session_id,
        "revision": 1,
    }
    [provider] = capabilities["providers"]
    assert (provider["provider"], provider["name"], provider["version"]) == (
        "test",
        "identity",
        "1",
    )
    assert provider["inputPorts"] == [
        {"name": "input", "kind": "array", "required": True}
    ]
    assert provider["outputPorts"] == [
        {"name": "output", "kind": "array", "required": True}
    ]
    assert provider["optionsSchema"] == {
        "fields": [{"name": "flag", "valueType": "boolean", "required": True}],
        "additionalProperties": False,
    }
    assert provider["modes"] == ["batch"]
    assert provider["finality"] == "unproven"
    assert provider["supportsStaticInputs"] is False
    assert {
        "registrationKind": "provider",
        "reconstruction": "serialized",
        "provider": "test",
        "name": "identity",
        "version": "1",
    } in document["preview"]["workerRegistrations"]
    operators = {operator["kind"]: operator for operator in capabilities["operators"]}
    assert list(operators) == [operator.kind for operator in snapshot.operators]
    if snapshot.schema_version == 3:
        assert list(operators) == [
            "cross_section",
            "expression",
            "rolling",
            "snapshot_sql",
            "sql",
            "stream_asof_join",
            "stream_join",
            "window",
        ]
    if version("calc-flow-python") == "2026.11.14":
        assert {"bounded_order", "bounded_over", "distinct"} <= operators.keys()
    cross_section = operators["cross_section"]
    assert cross_section["modes"] == ["batch", "stream"]
    assert cross_section["finality"] == "group_final_append_only"
    assert any(connector["name"] == "file" for connector in capabilities["connectors"])
    assert capabilities["lateOutput"] == {
        "operators": ["cross_section", "rolling"],
        "schemaVersion": 1,
        "metricsVersion": 1,
    }
    assert document["preview"]["inputBatchKinds"] == ["table"]
    assert catalog.json() == []
    capability_operation = openapi["paths"][f"{API_PREFIX}/capabilities"]["get"]
    assert capability_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/CapabilitiesResponse"}
    assert (
        openapi["components"]["schemas"]["CapabilitiesResponse"]["properties"][
            "schemaVersion"
        ]["const"]
        == 3
    )


@pytest.mark.parametrize("phase", ["warm_cache", "second_sample"])
@pytest.mark.parametrize(
    "field, value, location",
    [
        ("schema_version", 4, "schemaVersion"),
        ("schema_version", 6, "schemaVersion"),
        ("schema_version", 3.0, "schemaVersion"),
        ("schema_version", True, "schemaVersion"),
        ("port_binding", "options", "runtime.providers.0.portBinding"),
        (
            "options_json_schema",
            '{"type":"object"}',
            "runtime.providers.0.optionsJsonSchema",
        ),
        ("state_layouts", (1,), "runtime.providers.0.stateLayouts"),
    ],
    ids=[
        "v4",
        "v6",
        "float",
        "bool",
        "port-binding",
        "options-schema",
        "state-layouts",
    ],
)
def test_capabilities_reject_incompatible_snapshots_before_reuse_or_publish(
    tmp_path, monkeypatch, phase, field, value, location
) -> None:
    runtime = Runtime()
    runtime.register_provider("test", "identity", "1", lambda batch, _options: batch)
    snapshot, registrations = runtime.capability_registration_snapshot()
    invalid = copy(snapshot)
    # Simulate an inconsistent core sampler without altering the valid snapshot.
    if field == "schema_version":
        object.__setattr__(invalid, field, value)
    else:
        if snapshot.schema_version != 5:
            pytest.skip("requires the v5 provider descriptor")
        [provider] = snapshot.providers
        invalid_provider = copy(provider)
        object.__setattr__(invalid_provider, field, value)
        object.__setattr__(invalid, "providers", (invalid_provider,))

    url = f"{API_PREFIX}/capabilities"
    with _client(tmp_path, runtime=runtime) as client:
        baseline = client.get(url)
        assert baseline.status_code == 200, baseline.text

    with _client(tmp_path, runtime=runtime) as client:
        if phase == "warm_cache":
            assert client.get(url).json() == baseline.json()
            samples = iter((invalid,))
        else:
            samples = iter((snapshot, invalid))
        monkeypatch.setattr(
            Runtime,
            "capability_registration_snapshot",
            lambda _: (next(samples, snapshot), registrations),
        )
        rejected = client.get(url)
        recovered = client.get(url)

    assert rejected.status_code == 500, rejected.text
    assert f"at {location}:" in rejected.json()["detail"]
    assert recovered.status_code == 200, recovered.text
    assert recovered.json() == baseline.json()


def test_capabilities_route_reports_a_malformed_runtime_snapshot_as_internal(
    tmp_path,
) -> None:
    class MalformedCapabilityManager(FakeManager):
        def capabilities(self):
            raise CapabilitySnapshotError(
                "runtime capability snapshot violates schema version 1 at "
                "runtime.batchKinds.0: Input should be 'table' or 'array'"
            )

    with _client(
        tmp_path,
        runtime=Runtime(),
        run_manager=MalformedCapabilityManager(),
    ) as client:
        response = client.get(f"{API_PREFIX}/capabilities")

    assert response.status_code == 500
    assert response.json() == {
        "detail": (
            "runtime capability snapshot violates schema version 1 at "
            "runtime.batchKinds.0: Input should be 'table' or 'array'"
        )
    }


def test_capabilities_route_reports_an_unavailable_runtime_session(
    tmp_path,
) -> None:
    class UnavailableCapabilityManager(FakeManager):
        def capabilities(self):
            raise RunManagerError("no parent runtime")

    with _client(
        tmp_path,
        runtime=Runtime(),
        run_manager=UnavailableCapabilityManager(),
    ) as client:
        response = client.get(f"{API_PREFIX}/capabilities")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "runtime capability snapshot is unavailable for this session"
    }


def test_mutating_routes_use_the_injected_runtime_before_store_mutation(
    tmp_path,
) -> None:
    runtime = Runtime()
    runtime.register_provider("test", "identity", "1", lambda batch, _options: batch)
    runtime.register_scalar_udf(
        provider="python",
        name="identity",
        version="1",
        input_types=("int64",),
        return_type="int64",
        volatility="immutable",
        function=lambda value: value,
    )
    provider_project = (
        PipelineBuilder("provider_project")
        .external("calc", "test", "identity", "1", {})
        .project
    )
    udf_project = (
        PipelineBuilder("udf_project")
        .expression(
            "calc",
            "result = identity(value)",
            udfs=(("python", "identity", "1"),),
        )
        .project
    )
    invalid_project = {
        **_project("invalid_project"),
        "pipeline": {"name": "empty", "nodes": []},
    }

    with _client(tmp_path, runtime=runtime) as client:
        created = _create(client, provider_project)
        imported = client.post(
            f"{API_PREFIX}/projects/import?format=json",
            content=json.dumps(udf_project),
        )
        rejected_create = _create(client, invalid_project)
        rejected_put = client.put(
            f"{API_PREFIX}/projects/invalid_project", json=invalid_project
        )
        rejected_import = client.post(
            f"{API_PREFIX}/projects/import?format=json",
            content=json.dumps({**invalid_project, "id": "unsafe\r\nid"}),
        )
        listed = client.get(f"{API_PREFIX}/projects")

    assert created.status_code == 201
    assert imported.status_code == 201
    assert rejected_create.status_code == 422
    assert rejected_put.status_code == 422
    assert rejected_import.status_code == 422
    assert [project["id"] for project in listed.json()] == [
        "provider_project",
        "udf_project",
    ]


@pytest.mark.parametrize(
    "report",
    [
        [],
        {"valid": "yes", "issues": []},
        {"valid": False, "issues": object()},
        {"valid": False, "issues": [object()]},
        {"valid": True, "issues": [], "fingerprint": float("nan")},
        {"valid": True, "issues": [{"message": "contradictory"}]},
    ],
)
def test_mutating_routes_reject_malformed_runtime_validation_reports(
    tmp_path, report
) -> None:
    class MalformedRuntime:
        def validation_report(self, project_json: str):
            assert json.loads(project_json)["id"] == "project_alpha"
            return report

    app = create_app(
        project_directory=tmp_path / "projects",
        checkpoint_directory=tmp_path / "checkpoints",
        runtime=MalformedRuntime(),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = _create(client)
        listed = client.get(f"{API_PREFIX}/projects")

    assert response.status_code == 500
    assert listed.json() == []


def test_every_validation_caller_treats_malformed_runtime_data_as_internal(
    tmp_path,
) -> None:
    class SwitchingRuntime:
        malformed = False

        def validation_report(self, project_json: str) -> dict[str, object]:
            json.loads(project_json)
            if self.malformed:
                return {"valid": False, "issues": [], "fingerprint": None}
            return {"valid": True, "issues": [], "fingerprint": "valid"}

    runtime = SwitchingRuntime()
    with _client(tmp_path, runtime=runtime) as client:
        assert _create(client).status_code == 201
        runtime.malformed = True
        responses = (
            client.post(f"{API_PREFIX}/projects/project_alpha/validate"),
            client.post(
                f"{API_PREFIX}/projects",
                json=_project("project_new", name="New"),
            ),
            client.put(
                f"{API_PREFIX}/projects/project_alpha",
                json={**_project(), "name": "Overwritten"},
            ),
            client.post(
                f"{API_PREFIX}/projects/import?format=json&replace=true",
                content=json.dumps({**_project(), "name": "Imported"}),
            ),
        )
        stored = client.get(f"{API_PREFIX}/projects/project_alpha")
        listed = client.get(f"{API_PREFIX}/projects")

    assert [response.status_code for response in responses] == [500, 500, 500, 500]
    assert all(
        response.json()["detail"].startswith(
            "runtime validation report violates the v1 contract at "
        )
        for response in responses
    )
    assert stored.json()["name"] == "Alpha"
    assert [project["id"] for project in listed.json()] == ["project_alpha"]


def test_validation_route_preserves_native_calc_flow_error_details(
    tmp_path,
) -> None:
    class FailingRuntime:
        should_fail = False

        def validation_report(self, project_json: str) -> dict[str, object]:
            json.loads(project_json)
            if self.should_fail:
                raise CalcFlowError(
                    "pipeline.nodes[0]: provider test:missing@1 is not registered"
                )
            return {"valid": True, "issues": [], "fingerprint": "valid"}

    runtime = FailingRuntime()
    with _client(tmp_path, runtime=runtime) as client:
        assert _create(client).status_code == 201
        runtime.should_fail = True
        response = client.post(f"{API_PREFIX}/projects/project_alpha/validate")

    assert response.status_code == 422
    assert response.json() == {
        "detail": "pipeline.nodes[0]: provider test:missing@1 is not registered"
    }


def test_project_crud_preserves_client_ids_sorting_and_request_values(tmp_path) -> None:
    original = _project()
    with _client(tmp_path) as client:
        created = _create(client, original)
        duplicate = _create(client, original)
        assert _create(client, _project("project_beta", name="Beta")).status_code == 201
        listed = client.get(f"{API_PREFIX}/projects")
        fetched = client.get(f"{API_PREFIX}/projects/project_alpha")
        updated_document = {**original, "name": "Updated"}
        updated = client.put(
            f"{API_PREFIX}/projects/project_alpha", json=updated_document
        )
        mismatch = client.put(f"{API_PREFIX}/projects/other", json=updated_document)
        deleted = client.delete(f"{API_PREFIX}/projects/project_alpha")
        missing = client.get(f"{API_PREFIX}/projects/project_alpha")
        missing_delete = client.delete(f"{API_PREFIX}/projects/project_alpha")

    assert created.status_code == 201
    assert created.json() == ProjectDocument.model_validate(original).model_dump(
        mode="json"
    )
    assert fetched.json() == created.json()
    assert duplicate.status_code == 409
    assert [item["id"] for item in listed.json()] == [
        "project_alpha",
        "project_beta",
    ]
    assert listed.json()[0]["node_count"] == 1
    assert fetched.json()["graph"]["nodes"][0]["id"] == "calculate"
    assert updated.json() == ProjectDocument.model_validate(
        updated_document
    ).model_dump(mode="json")
    assert mismatch.status_code == 409
    assert original["name"] == "Alpha"
    assert deleted.status_code == 204
    assert missing.status_code == 404
    assert missing_delete.status_code == 404


def test_project_creation_rejects_slash_ids(tmp_path) -> None:
    project = _project("team/alpha")
    with _client(tmp_path) as client:
        created = _create(client, project)

    assert created.status_code == 422
    assert "invalid_id" in created.text


@pytest.mark.parametrize("method", ["POST", "PUT"])
@pytest.mark.parametrize("body", [b"null", b"", b"{"])
def test_project_body_errors_preserve_fastapi_locations(tmp_path, method, body) -> None:
    url = f"{API_PREFIX}/projects"
    if method == "PUT":
        url += "/project_alpha"
    with _client(tmp_path) as client:
        response = client.request(
            method, url, content=body, headers={"Content-Type": "application/json"}
        )

    assert response.status_code == 422
    [error] = response.json()["detail"]
    assert error["msg"]
    if body == b"null":
        # The two-wheel CI pins FastAPI 0.165.0, which passes JSON null to the
        # model. Older FastAPI releases can reject it as a missing body.
        expected_by_version = {"0.150.0": {"missing"}, "0.165.0": {"value_error"}}
        expected = expected_by_version.get(
            version("fastapi"), {"value_error", "missing"}
        )
        assert error["type"] in expected
        assert error["loc"] == ["body"]
        assert error["input"] is None
    elif body:
        assert error["type"] == "json_invalid"
        assert error["loc"] == ["body", 1]
    else:
        assert error["type"] == "missing"
        assert error["loc"] == ["body"]


@pytest.mark.parametrize(
    "invalid_fields, message",
    [({"unexpected": True}, "unknown field"), ({"format_version": 2}, "expected 3")],
)
def test_project_structure_rejections_preserve_validation_details(
    tmp_path, invalid_fields, message
) -> None:
    document = _project() | invalid_fields
    with _client(tmp_path) as client:
        responses = (
            _create(client, document),
            client.put(f"{API_PREFIX}/projects/project_alpha", json=document),
        )
        assert client.get(f"{API_PREFIX}/projects").json() == []
    for response in responses:
        assert response.status_code == 422
        [error] = response.json()["detail"]
        assert error["type"] == "value_error"
        assert error["loc"] == ["body"]
        assert message in error["msg"]
        assert error["input"] == document
        assert error["ctx"] == {"error": {}}


def test_project_write_rejections_preserve_stored_content(tmp_path) -> None:
    url = f"{API_PREFIX}/projects"
    project_url = f"{url}/project_alpha"
    document = _project()
    changed = document | {"name": "Changed"}
    invalid = changed | {"format_version": 2}
    unexecutable = changed | {"graph": {"name": "empty", "nodes": []}}
    with _client(tmp_path) as client:
        created = _create(client, document)
        assert created.status_code == 201
        [stored] = (tmp_path / "projects").glob("*.json")
        original_bytes = stored.read_bytes()

        rejected_create = _create(client, unexecutable | {"id": "rejected"})
        rejected_update = client.put(project_url, json=unexecutable)
        rejected_import = client.post(
            f"{url}/import?format=json&replace=true", content=json.dumps(unexecutable)
        )
        for response in (rejected_create, rejected_update, rejected_import):
            assert response.status_code == 422
            detail = response.json()["detail"]
            assert detail["kind"] == "invalid"
            assert detail["valid"] is False
            assert detail["fingerprint"] is None
            assert detail["issues"][0]["path"] == "graph.nodes"

        assert client.put(project_url, json=invalid).status_code == 422
        for fmt, content in (("json", b"{"), ("yaml", b"graph: [")):
            malformed = client.post(
                f"{url}/import?format={fmt}&replace=true", content=content
            )
            assert malformed.status_code == 422
            assert isinstance(malformed.json()["detail"], str)
        missing_format = client.post(
            f"{url}/import?replace=true", content=json.dumps(changed)
        )
        assert missing_format.status_code == 422
        [error] = missing_format.json()["detail"]
        assert error["type"] == "missing"
        assert error["loc"] == ["query", "format"]
        assert _create(client, changed).status_code == 409
        assert (
            client.put(project_url, json=changed | {"id": "other"}).status_code == 409
        )
        assert client.get(project_url).json() == created.json()
        assert [item["id"] for item in client.get(url).json()] == ["project_alpha"]
        assert list((tmp_path / "projects").glob("*.json")) == [stored]
        assert stored.read_bytes() == original_bytes


def test_project_write_supports_installed_core_parallelism_modes(tmp_path) -> None:
    document = _project()
    document["graph"]["datafusion"] = {"parallelism_mode": "auto_rows"}
    modes = json.loads(project_json_schema())["$defs"]["DataFusionParallelismMode"]
    supports_auto_rows = any(mode["const"] == "auto_rows" for mode in modes["oneOf"])
    core_version = version("calc-flow-python")
    if core_version in {"2026.10.27", "2026.11.14"}:
        assert supports_auto_rows == (core_version == "2026.11.14")
    with _client(tmp_path) as client:
        created = _create(client, document)
        if supports_auto_rows:
            assert created.status_code == 201, created.text
            assert (
                created.json()["graph"]["datafusion"]["parallelism_mode"] == "auto_rows"
            )
            fetched = client.get(f"{API_PREFIX}/projects/project_alpha")
            assert fetched.status_code == 200
            assert fetched.json() == created.json()
        else:
            assert created.status_code == 422
            assert client.get(f"{API_PREFIX}/projects").json() == []
            assert not list((tmp_path / "projects").glob("*.json"))


def test_project_routes_await_async_store_and_never_use_blocking_facades(
    tmp_path,
) -> None:
    class AsyncOnlyStore:
        def __init__(self) -> None:
            self.projects: dict[str, ProjectDocument] = {}

        async def create(self, project: ProjectDocument) -> None:
            self.projects[str(project.root["id"])] = ProjectDocument.model_validate(
                project.root
            )

        async def put(self, project: ProjectDocument) -> None:
            self.projects[str(project.root["id"])] = ProjectDocument.model_validate(
                project.root
            )

        async def get(self, project_id: str) -> ProjectDocument:
            return ProjectDocument.model_validate(self.projects[project_id].root)

        async def list(self) -> list[ProjectDocument]:
            return list(self.projects.values())

        async def delete(self, project_id: str) -> None:
            del self.projects[project_id]

        def create_blocking(self, *_: object) -> None:
            raise AssertionError("blocking facade used")

    store = AsyncOnlyStore()
    with _client(tmp_path, project_store=store) as client:
        assert _create(client).status_code == 201
        assert client.get(f"{API_PREFIX}/projects/project_alpha").status_code == 200
        assert (
            client.put(
                f"{API_PREFIX}/projects/project_alpha", json=_project()
            ).status_code
            == 200
        )
        assert client.get(f"{API_PREFIX}/projects").status_code == 200
        assert client.delete(f"{API_PREFIX}/projects/project_alpha").status_code == 204
        assert client.get(f"{API_PREFIX}/projects/project_alpha").status_code == 404


def test_import_export_use_bounded_strict_rust_transforms_and_conflicts(
    tmp_path,
) -> None:
    document = _project()
    with _client(tmp_path) as client:
        imported = client.post(
            f"{API_PREFIX}/projects/import?format=json",
            content=json.dumps(document),
        )
        conflict = client.post(
            f"{API_PREFIX}/projects/import?format=json",
            content=json.dumps(document),
        )
        replaced = client.post(
            f"{API_PREFIX}/projects/import?format=json&replace=true",
            content=json.dumps({**document, "name": "Replaced"}),
        )
        json_export = client.get(
            f"{API_PREFIX}/projects/project_alpha/export?format=json"
        )
        yaml_export = client.get(
            f"{API_PREFIX}/projects/project_alpha/export?format=yaml"
        )
        yaml_import = client.post(
            f"{API_PREFIX}/projects/import?format=yaml&replace=true",
            content=yaml_export.content,
        )
        unsafe = client.post(
            f"{API_PREFIX}/projects/import?format=yaml",
            content="!!python/object/apply:os.system ['id']",
        )
        alias = client.post(
            f"{API_PREFIX}/projects/import?format=yaml",
            content=(
                "format_version: 2\nid: alias\nname: &name alias\n"
                "description: *name\npipeline: {name: p, nodes: []}\n"
            ),
        )
        oversized = client.post(
            f"{API_PREFIX}/projects/import?format=json",
            content=b"x" * (10 * 1024 * 1024 + 1),
        )
        missing = client.get(f"{API_PREFIX}/projects/missing/export")
        missing_validation = client.post(f"{API_PREFIX}/projects/missing/validate")
        missing_checkpoint = client.get(f"{API_PREFIX}/projects/missing/checkpoint")

    assert imported.status_code == 201
    assert conflict.status_code == 409
    assert replaced.status_code == 201
    assert replaced.json()["name"] == "Replaced"
    assert json_export.status_code == 200
    assert json_export.text.endswith("\n")
    assert (
        json_export.text
        == json.dumps(json_export.json(), indent=2, sort_keys=True) + "\n"
    )
    assert yaml_export.status_code == 200
    assert "format_version: 3" in yaml_export.text
    assert yaml_import.status_code == 201
    assert yaml_import.json() == replaced.json()
    assert unsafe.status_code == 422
    assert alias.status_code == 422
    assert oversized.status_code == 422
    assert missing.status_code == 404
    assert missing_validation.status_code == 404
    assert missing_checkpoint.status_code == 404


def test_import_streams_with_early_and_running_size_limits(
    tmp_path, monkeypatch
) -> None:
    maximum = 10 * 1024 * 1024
    parser_calls: list[int] = []

    def tracking_parser(document: str | bytes) -> ProjectDocument:
        parser_calls.append(len(document))
        return ProjectDocument.model_validate(_project())

    monkeypatch.setattr(routes_module, "import_project_json", tracking_parser)
    with _client(tmp_path) as client:
        declared_oversize = client.post(
            f"{API_PREFIX}/projects/import?format=json",
            content=json.dumps(_project()),
            headers={"Content-Length": str(maximum + 1)},
        )

        def chunks():
            yield b" " * maximum
            yield b"x"

        streamed_oversize = client.post(
            f"{API_PREFIX}/projects/import?format=json", content=chunks()
        )
        malformed_length = client.post(
            f"{API_PREFIX}/projects/import?format=json",
            content=b"",
            headers={"Content-Length": "not-an-integer"},
        )
        negative_length = client.post(
            f"{API_PREFIX}/projects/import?format=json",
            content=b"",
            headers={"Content-Length": "-1"},
        )
        duplicate_length = client.post(
            f"{API_PREFIX}/projects/import?format=json",
            content=b"",
            headers=[("Content-Length", "0"), ("Content-Length", "1")],
        )

        def exact_chunks():
            yield b"x" * maximum

        exact_limit = client.post(
            f"{API_PREFIX}/projects/import?format=json", content=exact_chunks()
        )

    assert declared_oversize.status_code == 422
    assert streamed_oversize.status_code == 422
    assert malformed_length.status_code == 422
    assert negative_length.status_code == 422
    assert duplicate_length.status_code == 422
    assert exact_limit.status_code == 201
    assert parser_calls == [maximum]


def test_import_never_uses_request_body_buffering(tmp_path, monkeypatch) -> None:
    async def fail_body(_: StarletteRequest) -> bytes:
        raise AssertionError("Request.body() buffered the project import")

    monkeypatch.setattr(StarletteRequest, "body", fail_body)
    with _client(tmp_path) as client:
        imported = client.post(
            f"{API_PREFIX}/projects/import?format=json",
            content=json.dumps(_project()),
        )

    assert imported.status_code == 201


def test_export_content_disposition_encodes_untrusted_project_ids(tmp_path) -> None:
    class UntrustedStore:
        async def get(self, project_id: str) -> ProjectDocument:
            return ProjectDocument.model_validate(_project(project_id))

    app = create_app(
        project_store=UntrustedStore(),
        checkpoint_directory=tmp_path / "checkpoints",
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        exported = client.get(
            f"{API_PREFIX}/projects/unsafe%0D%0AX-Injected%3Ayes/export"
        )

    assert exported.status_code == 200
    disposition = exported.headers["content-disposition"]
    assert disposition.startswith("attachment; filename*=UTF-8''")
    assert "%0D%0A" in disposition
    assert "\r" not in disposition
    assert "\n" not in disposition


def test_injected_key_error_maps_missing_project_dependencies_to_404(tmp_path) -> None:
    class MissingStore:
        async def get(self, project_id: str) -> ProjectDocument:
            raise KeyError(project_id)

    with _client(tmp_path, project_store=MissingStore()) as client:
        responses = (
            client.get(f"{API_PREFIX}/projects/missing/export"),
            client.post(f"{API_PREFIX}/projects/missing/validate"),
            client.get(f"{API_PREFIX}/projects/missing/checkpoint"),
            client.delete(f"{API_PREFIX}/projects/missing/checkpoint"),
        )

    assert [response.status_code for response in responses] == [404, 404, 404, 404]


def test_import_and_export_threadpool_only_pure_rust_transformations(
    tmp_path, monkeypatch
) -> None:
    calls: list[object] = []
    original = routes_module.run_in_threadpool

    async def tracking(function, *args, **kwargs):
        calls.append(function)
        return await original(function, *args, **kwargs)

    monkeypatch.setattr(routes_module, "run_in_threadpool", tracking)
    with _client(tmp_path) as client:
        assert (
            client.post(
                f"{API_PREFIX}/projects/import?format=json",
                content=json.dumps(_project()),
            ).status_code
            == 201
        )
        assert (
            client.get(
                f"{API_PREFIX}/projects/project_alpha/export?format=yaml"
            ).status_code
            == 200
        )

    assert routes_module.import_project_json in calls
    assert routes_module.export_project_yaml in calls
    assert FileProjectStore.create not in calls
    assert FileProjectStore.get not in calls


def test_v2_checkpoint_routes_are_removed(tmp_path) -> None:
    with _client(tmp_path) as client:
        assert _create(client).status_code == 201
        inspected = client.get(f"{API_PREFIX}/projects/project_alpha/checkpoint")
        reset = client.delete(f"{API_PREFIX}/projects/project_alpha/checkpoint")

    assert inspected.status_code == 404
    assert reset.status_code == 404


def test_v2_checkpoint_store_is_not_attached_to_studio(tmp_path) -> None:
    with _client(tmp_path) as client:
        state = client.app.state

    assert not hasattr(state, "checkpoint_store")


def test_v2_run_routes_are_removed(tmp_path) -> None:
    with _client(tmp_path) as client:
        assert _create(client).status_code == 201
        submitted = client.post(f"{API_PREFIX}/projects/project_alpha/runs", json={})
        fetched = client.get(f"{API_PREFIX}/runs/run_1")
        events = client.get(f"{API_PREFIX}/runs/run_1/events")
        cancelled = client.delete(f"{API_PREFIX}/runs/run_1")

    statuses = {
        submitted.status_code,
        fetched.status_code,
        events.status_code,
        cancelled.status_code,
    }
    assert statuses == {404}


def test_app_serves_static_frontend_and_accepts_only_loopback(tmp_path) -> None:
    frontend = tmp_path / "frontend"
    assets = frontend / "assets"
    assets.mkdir(parents=True)
    (frontend / "index.html").write_text("<h1>Local studio</h1>", encoding="utf-8")
    (assets / "app.js").write_text("export {};", encoding="utf-8")
    app = create_app(
        project_directory=tmp_path / "projects", frontend_directory=frontend
    )

    with TestClient(app) as client:
        index = client.get("/")
        asset = client.get("/assets/app.js")

    assert index.status_code == 200
    assert "Local studio" in index.text
    assert asset.status_code == 200
    assert validate_bind_host("127.0.0.1") == "127.0.0.1"
    assert validate_bind_host("::1") == "::1"
    assert validate_bind_host("localhost") == "localhost"
    with pytest.raises(ValueError, match="loopback"):
        validate_bind_host("0.0.0.0")
    with pytest.raises(ValueError, match="loopback"):
        validate_bind_host("example.com")

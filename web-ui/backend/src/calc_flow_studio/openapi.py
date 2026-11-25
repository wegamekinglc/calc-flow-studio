"""Embed the installed core's project JSON Schema in the Studio contract."""

from __future__ import annotations

import json

from calc_flow import project_json_schema
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from calc_flow_studio.models import ProjectCreateRequest, ProjectDocument


def project_openapi(app: FastAPI) -> dict:
    if app.openapi_schema is None:
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        canonical = json.loads(project_json_schema())
        for model in (ProjectCreateRequest, ProjectDocument):
            component = model.__name__
            prefix = f"#/components/schemas/{component}/$defs/"
            schema["components"]["schemas"][component] = _rebase_refs(canonical, prefix)
        app.openapi_schema = schema
    return app.openapi_schema


def _rebase_refs(value: object, prefix: str) -> object:
    if isinstance(value, dict):
        return {
            key: prefix + item.removeprefix("#/$defs/")
            if key == "$ref" and isinstance(item, str) and item.startswith("#/$defs/")
            else _rebase_refs(item, prefix)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rebase_refs(item, prefix) for item in value]
    return value

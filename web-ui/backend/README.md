# Calc Flow Studio

`calc-flow-studio` packages the local FastAPI service and built React client for
Calc Flow. It requires `calc-flow-python>=2026.10.27,<2027` and serves
the batch-preview and continuous-job APIs under `/api/v3`.

Studio is built as a separate wheel and is not published to PyPI. Follow the
repository [README](../../README.md#requirements) to create the environment
with the core wheel and this package, including the React assets.
Then start the loopback-only service from the repository root:

```bash
uv run --no-sync --package calc-flow-studio calc-flow-web
```

Open `http://127.0.0.1:8765`. The server rejects non-loopback hosts by default.
HTTP clients can read a launch-specific token from `GET /api/v3/session` and
send it as `X-Calc-Flow-Session` on `POST`, `PUT`, `PATCH`, and `DELETE` requests.
The browser client handles this automatically. Cross-origin requests must come
from the local Studio development origin.
See the local [Studio guide](../../docs/studio-guide.md) for execution and
configuration, and [installation instructions](../../README.md#requirements)
for upgrading the core dependency or installing the pinned source wheel.

Batch execution uses saved input data and the project's bounded preview options:

| Method   | Path                         | Behavior                         |
|----------|------------------------------|----------------------------------|
| `POST`   | `/api/v3/previews`            | Submit `{"project_id": "..."}`   |
| `GET`    | `/api/v3/previews/{id}`       | Read status and bounded results  |
| `DELETE` | `/api/v3/previews/{id}`       | Cancel an active preview         |

Preview states include `pending`, `running`, `completed`, `failed`, `cancelled`,
and `timed_out`. Completed responses contain output schemas, rows, truncation
flags, and execution diagnostics. Stream jobs use `/api/v3/jobs` and persist
their output through configured sinks. Interactive API documentation is served
at `/docs`; the old v2 run endpoints remain removed.

Calc Flow Studio is licensed under Apache-2.0.

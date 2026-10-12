# Calc Flow Studio

Calc Flow Studio is the local FastAPI and React companion application for
[Calc Flow](https://github.com/wegamekinglc/calc-flow). It serves the
continuous-job API under `/api/v3` together with the browser client for
editing, validating, previewing, and running Calc Flow projects locally.

## Layout

- `web-ui/backend/` — the `calc-flow-studio` Python package (FastAPI backend).
- `web-ui/src/` — the React/TypeScript client (Vite and React Flow 12).
- `web-ui/scripts/` — managed start/stop helpers and API-contract tooling.
- `schemas/` — the checked project-v3 JSON Schema, verified against the
  installed `calc-flow-python` in the backend test suite.
- `docs/` — Studio guides.

## Requirements

- Python 3.13 or newer, uv, Node.js 20 or newer, and npm.
- `calc-flow-python>=2026.10.12,<2027`.

Until the first Calc Flow release carrying the public Runtime registration API
ships to PyPI (any release after `2026.10.12`), the backend needs a core wheel
built from the pinned calc-flow commit referenced in
`.github/workflows/ci.yml`. Build it from a calc-flow checkout with:

```bash
uv build --wheel --config-setting 'build-args=--features pyo3/abi3-py313'
```

Then create the environment and overlay the core wheel:

```bash
uv sync --package calc-flow-studio --extra dev --no-install-workspace
uv pip install --python .venv/bin/python --no-deps /path/to/calc_flow_python-*.whl
uv pip install --python .venv/bin/python --no-deps --editable web-ui/backend
```

Once that release is on PyPI, plain `uv sync --extra dev` is sufficient and
the dependency floor moves up to the release version.

## Run

Start the API and Vite server together from the repository root on macOS,
Linux, or WSL:

```bash
./web-ui/scripts/start_web_ui.sh
```

On native Windows PowerShell:

```powershell
.\web-ui\scripts\start_web_ui.ps1
```

Open `http://127.0.0.1:5173`. Logs and PID state are written to
`.calc-flow-web/`. Stop both managed process groups with the matching command
for your platform:

```bash
./web-ui/scripts/stop_web_ui.sh
```

```powershell
.\web-ui\scripts\stop_web_ui.ps1
```

To serve the built frontend from the installed Studio wheel instead, run only
the API and open `http://127.0.0.1:8765`:

```bash
uv run --no-sync --package calc-flow-studio calc-flow-web
```

See [web-ui/README.md](web-ui/README.md) for the development workflow and
[web-ui/backend/README.md](web-ui/backend/README.md) for the package contract.

## Verification

```bash
cd web-ui
npm ci
npm run sync:api
npm run build
npm test
npx playwright install chromium
npm run test:e2e
npm audit --omit=dev
cd backend
uv run --project . --extra dev pytest --cov=calc_flow_studio
```

The backend test suite enforces an 85% coverage floor, and the checked-in API
contract (`web-ui/openapi.json`, `web-ui/src/api/schema.d.ts`) is regenerated
with `npm run sync:api` and drift-checked in CI.

## License

Calc Flow Studio is licensed under Apache-2.0.

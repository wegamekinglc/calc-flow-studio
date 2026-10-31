# Calc Flow Studio

Calc Flow Studio is the local FastAPI and React companion application for
[Calc Flow](https://github.com/wegamekinglc/calc-flow). It serves the
batch-preview and continuous-job APIs under `/api/v3` together with the browser client for
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
- `calc-flow-python>=2026.10.27,<2027`.

Install the published core and the editable Studio package with:

```bash
uv sync --package calc-flow-studio --extra dev
```

For the exact core revision validated in CI, build a wheel from the calc-flow
commit pinned by `CALC_FLOW_CORE_REF` in `.github/workflows/ci.yml`:

```bash
uv build --wheel --config-setting 'build-args=--features pyo3/abi3-py313'
```

Then create the environment and overlay the core wheel:

```bash
uv sync --package calc-flow-studio --extra dev --no-install-workspace
uv pip install --python .venv/bin/python --no-deps /path/to/calc_flow_python-*.whl
uv pip install --python .venv/bin/python --no-deps --editable web-ui/backend
```

Use `uv run --no-sync` after installing a source-built core wheel so dependency
resolution does not replace it with the published release. API generation and
the managed start scripts preserve that installed core.

## Run

After upgrading an existing checkout, rerun `uv sync --package calc-flow-studio
--extra dev` to replace the older core dependency. For a source-built core,
reinstall the pinned wheel afterward and preserve it with `uv run --no-sync`.
Reinstall frontend dependencies with `npm --prefix web-ui ci`, then stop and
restart the managed services. Existing project documents remain project-v3.

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

To serve the frontend directly from the backend in this checkout, build it
first, then start only the API and open `http://127.0.0.1:8765`:

```bash
npm --prefix web-ui run build
uv run --no-sync --package calc-flow-studio calc-flow-web
```

The packaged Studio wheel includes those frontend assets.

**Batch** projects use **Run batch** and show calculated rows in **Results
preview**. **Stream** projects use **Start job** and read their configured
connector sources. The [Studio guide](docs/studio-guide.md) includes a complete
file-stream example and troubleshooting for graph names and input paths.

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
uv run --no-sync --project . pytest --cov=calc_flow_studio
```

The backend test suite enforces an 85% coverage floor, and the checked-in API
contract (`web-ui/openapi.json`, `web-ui/src/api/schema.d.ts`) is regenerated
with `npm run sync:api` and drift-checked in CI.

## License

Calc Flow Studio is licensed under Apache-2.0.

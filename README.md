# Calc Flow Studio

Calc Flow Studio is the local FastAPI and React companion application for
[Calc Flow](https://github.com/wegamekinglc/calc-flow). It serves the
batch-preview and continuous-job APIs under `/api/v3` together with the browser client for
editing, validating, previewing, and running Calc Flow projects locally.

## Layout

- `web-ui/backend/` — the `calc-flow-studio` Python package (FastAPI backend).
- `web-ui/src/` — the React/TypeScript client (Vite and React Flow 12).
- `web-ui/scripts/` — managed start/stop helpers and API-contract tooling.
- `schemas/` — the checked project-v3 JSON Schema for the supported core
  release floor.
- `docs/` — Studio guides.

## Requirements

- Python 3.13 or newer and uv.
- Node.js 20.19+ (20.x), 22.13+ (22.x), or 24+, with npm. CI uses 20.20.0.
- `calc-flow-python>=2026.10.27,<2027`.

Install the published core and the editable Studio package with:

```bash
uv sync --package calc-flow-studio --extra dev
```

CI tests the published core wheels `2026.10.27` and `2026.11.14`. The full
backend coverage and browser checks use the release floor `2026.10.27`.

To test a source build, run this command from the Calc Flow core checkout:

```bash
uv build --wheel --config-setting 'build-args=--features pyo3/abi3-py313'
```

Then create the environment and overlay the core wheel:

```bash
uv sync --package calc-flow-studio --extra dev --no-install-workspace
uv pip install --python .venv/bin/python --no-deps /path/to/calc_flow_python-*.whl
uv pip install --python .venv/bin/python --no-deps --editable web-ui/backend
```

Use `uv run --no-sync` after installing a source-built core wheel to preserve
that installation. The managed start scripts also use the installed core.

## Run

After upgrading an existing checkout, rerun `uv sync --package calc-flow-studio
--extra dev` to refresh the dependencies. For a source-built core, reinstall
your wheel afterward and preserve it with `uv run --no-sync`.
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

The backend test suite enforces an 85% coverage floor. The running server's
project schema and OpenAPI project components follow the installed core.
`npm run sync:api` and `npm run build:wheel` generate the checked-in OpenAPI and
TypeScript snapshots in an isolated Python 3.13 environment using the
`2026.10.27` core wheel and [pinned API dependencies](web-ui/api-schema-constraints.txt).
Use `npm ci` to install the generator from the npm lockfile. CI checks the
snapshots against this toolchain.

## License

Calc Flow Studio is licensed under Apache-2.0.

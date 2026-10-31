# Studio

[Documentation](../README.md) / Studio

Calc Flow Studio edits project-v3 documents, previews finite batch calculations,
and operates continuous jobs on a local computer. Install and start it using
the repository [requirements](../README.md#requirements) and
[run instructions](../README.md#run).
The packaged application opens at `http://127.0.0.1:8765`; the managed
development frontend opens at `http://127.0.0.1:5173`.

## Edit a calculation

Use the order-total calculation in
[01_datafusion_pipeline.py](https://github.com/wegamekinglc/calc-flow/blob/main/examples/01_datafusion_pipeline.py) as a small
calculation to understand: Python expressions calculate `gross`, then filter
and select the large orders. Export a reusable `Program` with `to_project()`
to obtain the native graph. The compiler can fuse those operations into fewer
nodes. Studio edits the lowered node, port, and expression fields in that
document. Validate the graph after
changing nodes or connections, then save the project.

For batch input cards, **Edit data** opens a draft editor. **Confirm** applies
valid input; **Cancel**, Escape, or closing the dialog discards the draft.
Confirming a card does not save the entire project. See the
[Studio application guide](../web-ui/README.md#edit-data-sources) for controls.

In **Batch** mode, select **Run batch** to save the confirmed inputs and execute
the calculation. **Results preview** shows each output's schema, row count,
bounded rows, and truncation indicator. The initial `total = a + b` example
returns `3` and `7`. **Cancel batch** stops an active worker; failures and
timeouts appear in the same panel. Preview limits come from the project's
batch runtime options.

Schema field names and Source/Sink binding names keep keyboard focus during
continuous edits. For stream Source/Sink cards, **Options** accepts a JSON
object as you type. A valid object updates the editable project immediately;
incomplete or invalid JSON stays in the local editor and is excluded from
saved or exported project values.

Each unfinished Options draft stays with its binding during renames and when
other bindings are added or removed. Removing the binding discards its draft.
Switching projects or externally replacing a binding, including a reload that
replaces it, displays the current project Options instead. External changes to
that Options value also replace the draft. These drafts are temporary editor
state.

[Example 14](https://github.com/wegamekinglc/calc-flow/blob/main/examples/14_project_persistence.py) demonstrates the project
serialization used by application code. Executable UDFs and provider callbacks
are registered in a trusted runtime and are not embedded in the saved graph.

## Inspect symbolic calculations

The programs in [examples 09–13](https://github.com/wegamekinglc/calc-flow/blob/main/docs/symbolic-workflows.md) compile symbolic
declarations into native project nodes. Selecting a node in Studio shows the
**Lowered project inspection** section: serialized expressions, operator and
provider identity, state and watermark requirements, and recognized matrix
copy boundaries.

This inspection reads the document exported by `program.to_project()`. It does
not run the Python builder or reconstruct expression objects or logical aliases.
Reloaded graphs retain physical binding names; Python collection and convenience
stream methods resolve logical names for their own execution. Exporting with
`mode="stream"` still requires
explicit operational connector and state settings before a job can launch. Reported sizes are
declared limits or estimates; use live metrics to observe memory and latency.

## Start and observe a continuous job

Stream execution uses connector bindings. Switching from Batch to Stream
replaces inline input cards with source and sink configuration; choose an
existing server-side input file instead of relying on the earlier inline data.
The default `file` connector takes a snapshot and finishes at EOF. Use a
continuous connector for an ongoing feed.

To run the default graph against a local JSON Lines file, create the input from
the repository root on Linux, macOS, or WSL:

```bash
uv run --no-sync --package calc-flow-studio python - <<'PY'
from pathlib import Path

path = Path(".calc-flow-input/input.json")
path.parent.mkdir(parents=True, exist_ok=True)
with path.open("x", encoding="utf-8") as stream:
    stream.write('{"a":1,"b":2}\n{"a":3,"b":4}\n')
PY
```

This command preserves an existing file; choose an unused path in that case. On
Windows, save the same two UTF-8 JSON Lines records using an editor. In the
stream settings, use graph name `main-pipeline`, source Options
`{"path":".calc-flow-input/input.json","format":"json"}`, and sink Options
`{"path":".calc-flow-output","output":"results"}`. Paths resolve relative to
the backend's working directory; use absolute paths when starting it elsewhere.
Select **Start job**. This example reaches `completed` and writes Parquet
outputs containing totals `3` and `7` beneath `.calc-flow-output`.

Checkpoint storage requires a graph name containing only ASCII letters,
numbers, dots, underscores, or dashes. Existing projects using `Main pipeline`
can change **Graph name** to `main-pipeline`. Start-time checks return a `422`
validation report with `graph.name` or `sources[i].options.path` when the name
is invalid or a local file source is missing, before a worker starts.

Configure a stream project with the registered sources, sinks, formats,
watermark policy, delivery requirements, and managed state settings described
in the [connector guide](https://github.com/wegamekinglc/calc-flow/blob/main/docs/connectors/README.md). The Job observatory starts the job,
shows status, results, and bounded metrics, and resumes event observation after
a connection interruption.

Use the checkpoint control to await a durable epoch, graceful shutdown to drain
accepted work, and cancellation to stop work and settle resources. These
controls correspond to the lifecycle demonstrated by
[04_continuous_runtime.py](https://github.com/wegamekinglc/calc-flow/blob/main/examples/04_continuous_runtime.py) and
[08_streaming_recovery.py](https://github.com/wegamekinglc/calc-flow/blob/main/examples/08_streaming_recovery.py); their in-memory
Python connector objects are not serialized into Studio projects.

## Configure late side outputs

Import a complete stream project or select a rolling/cross-section node and
choose **Side output** under **Late row policy**. The runtime must confirm
support for that operator. Studio obtains this through validation probes and
exposes it in `GET /api/v3/capabilities` as
`runtime.lateOutput.operators`, with `schemaVersion` and `metricsVersion`
equal to 1; a package version alone is not proof of support.

The node shows separate `output` and `late` ports. Connect and bind both
external routes in the stream configuration, using the physical names from the
[project guide](https://github.com/wegamekinglc/calc-flow/blob/main/docs/projects-guide.md#late-side-output-projects). Validate, save,
and export the project; its policy, exact schemas, edges, Sink bindings, and
per-output delivery settings remain data in the project document.

Changing policy is disabled while the late route is connected or bound;
disconnect it and remove its Sink binding explicitly first. Switching to
batch mode is disabled while side output is enabled. These controls preserve
the configured late route. The inspector shows its local closing boundary and
explains that late output has no event-time ordering or Watermark/Idle.
Barrier/EOF still pass, including empty late epochs. Normal-node progress
does not represent event-time progress on the late branch.

The standard `POST /api/v3/jobs` body still supplies only `project_id`.
Invalid projects fail before a worker starts. Project create/import/update
errors retain the `422` validation envelope; validation issues carry
`path`, `code`, and `message`. See
[project diagnostics](https://github.com/wegamekinglc/calc-flow/blob/main/docs/projects-guide.md#late-side-output-projects).
There is no raw late-row JSON preview: 64-bit diagnostic times and sequences
remain in Arrow. `late_rows` counts excluded normal rows; Sink/edge metrics
measure delivery. Two Sinks need independent delivery proofs and do not
provide simultaneous cross-system visibility.

## Service limits

Studio binds to loopback and is a local single-user application. Jobs run in
workers with concurrency, resident-memory, checkpoint-disk, and lifecycle
limits. The API accepts only loopback Host headers. Mutating requests require
the launch token from `GET /api/v3/session` in `X-Calc-Flow-Session`; the browser
client obtains it automatically. Token validation rejects missing or invalid
values, including non-ASCII values, with `403` and
`{"detail": "Invalid launch token"}` before a route handler runs.

The REST job API accepts connector-backed stream projects. A project
declaring static inputs can be inspected, but job creation returns `422`
because the REST contract has no field for live static values. Run such a
project through Python with explicit `static_inputs`, as in
[example 11](https://github.com/wegamekinglc/calc-flow/blob/main/examples/11_symbolic_static_matrix.py).

Consult the local [HTTP API reference](../web-ui/backend/README.md) for Studio
routes, the generated `/docs` page for request and response schemas, and
the [core design](https://github.com/wegamekinglc/calc-flow/blob/main/docs/design.md)
for runtime ownership.

Next: [Studio API reference](../web-ui/backend/README.md).

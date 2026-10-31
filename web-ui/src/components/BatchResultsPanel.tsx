import type { RunResponse, ValidationReport } from '../types';

interface BatchResultsPanelProps {
  preview: RunResponse | null;
  validation: ValidationReport | null;
  busy: boolean;
  onCancel: () => void;
}

const displayValue = (value: unknown): string =>
  value === undefined || value === null ? 'null'
    : typeof value === 'string' ? value : JSON.stringify(value);

export function BatchResultsPanel({ preview, validation, busy, onCancel }: BatchResultsPanelProps) {
  const active = preview?.status === 'pending' || preview?.status === 'running';
  return (
    <section className="results panel" aria-label="Batch results">
      <div className="panel-heading results-heading">
        <div><span className="eyebrow">Batch calculation</span><h2>Results preview</h2></div>
        {preview && <span className={`status-pill ${preview.status}`} role="status">{preview.status}</span>}
        {active && <button className="text-button" type="button" disabled={busy} onClick={onCancel}>Cancel batch</button>}
      </div>
      {validation && (
        <div className={`validation-banner ${validation.valid ? 'valid' : 'invalid'}`}>
          <strong>{validation.valid ? 'Graph is valid' : 'Graph needs attention'}</strong>
          <span>{validation.valid ? validation.fingerprint : validation.issues.map((issue) => issue.message).join(' · ')}</span>
        </div>
      )}
      {preview?.error && <div className="validation-banner invalid" role="alert">{preview.error}</div>}
      {!preview && <div className="empty-state"><p>Run the batch project to preview its calculated rows.</p></div>}
      {active && <p role="status">Calculating saved inputs…</p>}
      {preview?.status === 'completed' && (
        <div className="output-stack">
          {Object.entries(preview.result.outputs).map(([name, output]) => (
            <section className="output-card" key={name} aria-label={`Batch output ${name}`}>
              <header><h3>{name}</h3><span>{output.total_rows.toLocaleString()} rows{output.truncated ? ' · preview truncated' : ''}</span></header>
              {output.kind === 'table' ? (
                <div className="table-wrap">
                  <table aria-label={`${name} rows`}>
                    <thead><tr>{output.schema.map((field) => <th key={field.name} scope="col">{field.name}<small>{field.type}</small></th>)}</tr></thead>
                    <tbody>{output.rows.map((row, index) => (
                      <tr key={index}>{output.schema.map((field) => <td key={field.name}>{displayValue(row[field.name])}</td>)}</tr>
                    ))}</tbody>
                  </table>
                </div>
              ) : <pre>{JSON.stringify(output.data, null, 2)}</pre>}
            </section>
          ))}
          {Object.keys(preview.result.outputs).length === 0 && <p>The calculation completed without outputs.</p>}
        </div>
      )}
    </section>
  );
}

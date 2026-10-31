import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { api } from '../api/client';
import type { RunResponse } from '../types';
import { useBatchPreview } from './useBatchPreview';

const completed: RunResponse = {
  id: 'preview-1', project_id: 'project-1', status: 'completed',
  created_at: '2026-01-01T00:00:00Z', started_at: '2026-01-01T00:00:00Z',
  finished_at: '2026-01-01T00:00:01Z', error: null,
  result: { outputs: {}, metadata: {}, node_timings: {}, datafusion_metrics: [] },
};

afterEach(() => vi.restoreAllMocks());

describe('useBatchPreview', () => {
  it('delivers completed results and stops polling', async () => {
    const fetchPreview = vi.spyOn(api, 'preview').mockResolvedValue(completed);
    const onUpdate = vi.fn();
    const onError = vi.fn();
    renderHook(() => useBatchPreview('preview-1', onUpdate, onError));
    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith(completed));
    expect(fetchPreview).toHaveBeenCalledOnce();
    expect(onError).not.toHaveBeenCalled();
  });

  it('aborts an in-flight request and ignores its result after switching projects', async () => {
    let finish!: (preview: RunResponse) => void;
    let signal: AbortSignal | undefined;
    vi.spyOn(api, 'preview').mockImplementation((_id, requestSignal) => {
      signal = requestSignal;
      return new Promise((resolve) => { finish = resolve; });
    });
    const onUpdate = vi.fn();
    const onError = vi.fn();
    const { unmount } = renderHook(() => useBatchPreview('preview-1', onUpdate, onError));
    unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => { finish(completed); });
    expect(onUpdate).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
  });
});

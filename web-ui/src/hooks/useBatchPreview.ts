import { useEffect } from 'react';

import { api } from '../api/client';
import type { RunResponse } from '../types';

export function useBatchPreview(
  previewId: string | null,
  onUpdate: (preview: RunResponse) => void,
  onError: (error: Error) => void,
): void {
  useEffect(() => {
    if (!previewId) return;
    const controller = new AbortController();
    const isLive = () => !controller.signal.aborted;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const preview = await api.preview(previewId, controller.signal);
        if (!isLive()) return;
        onUpdate(preview);
        if (preview.status !== 'pending' && preview.status !== 'running') return;
      } catch (error) {
        if (!isLive()) return;
        onError(error as Error);
        return;
      }
      if (isLive()) timer = setTimeout(() => void poll(), 250);
    };
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [previewId, onUpdate, onError]);
}

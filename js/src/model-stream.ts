import type { StreamFn } from '@earendil-works/pi-agent-core';
import { createAssistantMessageEventStream, type AssistantMessage } from '@earendil-works/pi-ai';

/** firstEventMs: connection setup until the first stream event; totalMs: the whole response. */
export type StreamDeadline = number | { firstEventMs: number; totalMs: number };

/** Bound connection setup, the wait for the first event and the entire response, even if a transport ignores
 * abort. A function deadline is read when each request starts (the time left in the run). Python agent/loop.py
 * StreamedRequest: 300 s for the first event, then the stream runs while events flow up to 930 s in all, so a long
 * turn that is still streaming is not cut and billed again. */
export function deadlineStream(
  streamFn: StreamFn,
  deadline: StreamDeadline | (() => StreamDeadline),
): StreamFn {
  return (model, context, options) => {
    const limit = typeof deadline === 'function' ? deadline() : deadline;
    const totalMs = Math.max(1, Math.round(typeof limit === 'number' ? limit : limit.totalMs));
    const firstEventMs = Math.min(
      totalMs,
      Math.max(1, Math.round(typeof limit === 'number' ? limit : limit.firstEventMs)),
    );
    const output = createAssistantMessageEventStream();
    const controller = new AbortController();
    let ended = false;
    let partial: AssistantMessage | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let firstEvent: ReturnType<typeof setTimeout> | undefined;
    const cleanup = () => {
      clearTimeout(timer);
      clearTimeout(firstEvent);
      options?.signal?.removeEventListener('abort', cancel);
    };
    const fail = (message: string, cancelled = false) => {
      if (ended) return;
      ended = true;
      cleanup();
      // Freeze partial evidence. A late provider response must not mutate run history.
      const error: AssistantMessage = {
        role: 'assistant',
        content: [],
        api: model.api,
        provider: model.provider,
        model: model.id,
        usage: {
          input: 0,
          output: 0,
          cacheRead: 0,
          cacheWrite: 0,
          totalTokens: 0,
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
        },
        timestamp: Date.now(),
        ...(partial ? structuredClone(partial) : {}),
        stopReason: cancelled ? 'aborted' : 'error',
        errorMessage: message,
      };
      output.push({ type: 'error', reason: error.stopReason as 'error' | 'aborted', error });
      output.end();
      controller.abort();
    };
    const cancel = () => fail('Model request cancelled.', true);
    options?.signal?.addEventListener('abort', cancel, { once: true });
    if (options?.signal?.aborted) cancel();
    else {
      timer = setTimeout(() => fail(`Model stream exceeded ${totalMs} ms.`), totalMs);
      if (firstEventMs < totalMs)
        firstEvent = setTimeout(
          () => fail(`Model stream exceeded ${firstEventMs} ms before its first event.`),
          firstEventMs,
        );
      void (async () => {
        try {
          const source = await streamFn(model, context, { ...options, signal: controller.signal });
          if (ended) return;
          for await (const event of source) {
            if (ended) return;
            clearTimeout(firstEvent);
            if ('partial' in event) partial = event.partial;
            if (event.type === 'done' || event.type === 'error') {
              ended = true;
              cleanup();
              output.push(event);
              output.end();
              return;
            }
            output.push(event);
          }
          fail('Model stream ended before a terminal response event.');
        } catch (error) {
          fail(error instanceof Error ? error.message : String(error));
        }
      })();
    }
    return output;
  };
}

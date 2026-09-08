import type { StreamFn } from '@earendil-works/pi-agent-core';
import { createAssistantMessageEventStream, type AssistantMessage } from '@earendil-works/pi-ai';

/** Bound connection setup and the entire response, even if a transport ignores abort. */
export function deadlineStream(streamFn: StreamFn, timeoutMs: number): StreamFn {
  return (model, context, options) => {
    const output = createAssistantMessageEventStream();
    const controller = new AbortController();
    let ended = false;
    let partial: AssistantMessage | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const cleanup = () => {
      clearTimeout(timer);
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
      timer = setTimeout(() => fail(`Model stream exceeded ${timeoutMs} ms.`), timeoutMs);
      void (async () => {
        try {
          const source = await streamFn(model, context, { ...options, signal: controller.signal });
          if (ended) return;
          for await (const event of source) {
            if (ended) return;
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

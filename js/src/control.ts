/** Await a cooperative callback without letting a hung hook hold the run open forever. */
export async function bounded<T>(
  work: () => T | Promise<T>,
  timeoutMs: number,
  signal?: AbortSignal,
): Promise<T> {
  signal?.throwIfAborted();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let abort: (() => void) | undefined;
  const interrupted = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => reject(new Error(`Hook exceeded ${timeoutMs} ms.`)), timeoutMs);
    abort = () => reject(new Error('Run cancelled while awaiting hook.'));
    signal?.addEventListener('abort', abort, { once: true });
  });
  try {
    return await Promise.race([Promise.resolve().then(work), interrupted]);
  } finally {
    clearTimeout(timer);
    if (abort) signal?.removeEventListener('abort', abort);
  }
}

/** Pause is acknowledged at a tool boundary, never halfway through browser input. */
export class RunControl {
  private requested = false;
  paused = false;
  private acknowledge: (() => void) | undefined;
  private acknowledgement: Promise<void> | undefined;
  private release: (() => void) | undefined;
  private ended = false;
  steer: ((text: string) => void) | undefined;

  constructor(private readonly changed: (paused: boolean) => void) {}

  pause(): Promise<void> {
    if (this.ended) return Promise.resolve();
    if (!this.acknowledgement) {
      this.requested = true;
      this.acknowledgement = new Promise((resolve) => {
        this.acknowledge = resolve;
      });
    }
    return this.acknowledgement;
  }

  async checkpoint(signal?: AbortSignal): Promise<void> {
    signal?.throwIfAborted();
    if (!this.requested || this.ended) return;
    const resumed = new Promise<void>((resolve) => {
      this.release = resolve;
    });
    this.paused = true;
    this.changed(true);
    this.acknowledge?.();
    const abort = () => this.resume();
    signal?.addEventListener('abort', abort, { once: true });
    if (signal?.aborted) abort();
    try {
      await resumed;
      signal?.throwIfAborted();
    } finally {
      signal?.removeEventListener('abort', abort);
    }
  }

  resume() {
    const wasPaused = this.paused;
    this.requested = false;
    this.paused = false;
    this.acknowledge?.();
    this.release?.();
    this.release = undefined;
    this.acknowledgement = undefined;
    this.acknowledge = undefined;
    if (wasPaused) this.changed(false);
  }

  finish() {
    this.ended = true;
    this.resume();
    this.steer = undefined;
  }
}

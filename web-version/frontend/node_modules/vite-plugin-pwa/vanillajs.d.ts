declare module 'virtual:pwa-register' {
  import type { RegisterSWOptions } from 'vite-plugin-pwa/types'

  export type { RegisterSWOptions }

  /**
   * Registers the service worker returning a callback to reload the current page when an update is found.
   *
   * @param options the options to register the service worker.
   * @return (reloadPage?: boolean) => Promise<void> From version 0.13.2+ `reloadPage` param is not used anymore.
   */
  export function registerSW(options?: RegisterSWOptions): (reloadPage?: boolean) => Promise<void>
}

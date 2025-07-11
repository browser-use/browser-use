declare module 'virtual:pwa-register/solid' {
  // eslint-disable-next-line ts/prefer-ts-expect-error
  // @ts-ignore ignore when solid-js is not installed
  import type { Accessor, Setter } from 'solid-js'
  import type { RegisterSWOptions } from 'vite-plugin-pwa/types'

  export type { RegisterSWOptions }

  export function useRegisterSW(options?: RegisterSWOptions): {
    needRefresh: [Accessor<boolean>, Setter<boolean>]
    offlineReady: [Accessor<boolean>, Setter<boolean>]
    /**
     * Reloads the current window to allow the service worker take the control.
     *
     * @param reloadPage From version 0.13.2+ this param is not used anymore.
     */
    updateServiceWorker: (reloadPage?: boolean) => Promise<void>
  }
}

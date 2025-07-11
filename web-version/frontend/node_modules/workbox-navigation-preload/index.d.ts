import { disable } from './disable.js';
import { enable } from './enable.js';
import { isSupported } from './isSupported.js';
import './_version.js';
interface NavigationPreloadState {
    enabled?: boolean;
    headerValue?: string;
}
interface NavigationPreloadManager {
    disable(): Promise<void>;
    enable(): Promise<void>;
    getState(): Promise<NavigationPreloadState>;
    setHeaderValue(value: string): Promise<void>;
}
declare global {
    interface ServiceWorkerRegistration {
        readonly navigationPreload: NavigationPreloadManager;
    }
}
/**
 * @module workbox-navigation-preload
 */
export { disable, enable, isSupported };

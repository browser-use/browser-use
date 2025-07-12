import './_version.js';
/**
 * Claim any currently available clients once the service worker
 * becomes active. This is normally used in conjunction with `skipWaiting()`.
 *
 * @memberof workbox-core
 */
declare function clientsClaim(): void;
export { clientsClaim };

import './_version.js';
/**
 * Sends a data object to a service worker via `postMessage` and resolves with
 * a response (if any).
 *
 * A response can be set in a message handler in the service worker by
 * calling `event.ports[0].postMessage(...)`, which will resolve the promise
 * returned by `messageSW()`. If no response is set, the promise will not
 * resolve.
 *
 * @param {ServiceWorker} sw The service worker to send the message to.
 * @param {Object} data An object to send to the service worker.
 * @return {Promise<Object|undefined>}
 * @memberof workbox-window
 */
declare function messageSW(sw: ServiceWorker, data: {}): Promise<any>;
export { messageSW };

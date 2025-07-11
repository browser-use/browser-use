import { RouteHandler } from 'workbox-core/types.js';
import './_version.js';
/**
 * Define a default `handler` that's called when no routes explicitly
 * match the incoming request.
 *
 * Without a default handler, unmatched requests will go against the
 * network as if there were no service worker present.
 *
 * @param {workbox-routing~handlerCallback} handler A callback
 * function that returns a Promise resulting in a Response.
 *
 * @memberof workbox-routing
 */
declare function setDefaultHandler(handler: RouteHandler): void;
export { setDefaultHandler };

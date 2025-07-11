import { RouteHandler } from 'workbox-core/types.js';
import './_version.js';
/**
 * If a Route throws an error while handling a request, this `handler`
 * will be called and given a chance to provide a response.
 *
 * @param {workbox-routing~handlerCallback} handler A callback
 * function that returns a Promise resulting in a Response.
 *
 * @memberof workbox-routing
 */
declare function setCatchHandler(handler: RouteHandler): void;
export { setCatchHandler };

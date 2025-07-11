import { HTTPMethod } from './utils/constants.js';
import { RouteHandler, RouteHandlerObject, RouteMatchCallback } from 'workbox-core/types.js';
import './_version.js';
/**
 * A `Route` consists of a pair of callback functions, "match" and "handler".
 * The "match" callback determine if a route should be used to "handle" a
 * request by returning a non-falsy value if it can. The "handler" callback
 * is called when there is a match and should return a Promise that resolves
 * to a `Response`.
 *
 * @memberof workbox-routing
 */
declare class Route {
    handler: RouteHandlerObject;
    match: RouteMatchCallback;
    method: HTTPMethod;
    catchHandler?: RouteHandlerObject;
    /**
     * Constructor for Route class.
     *
     * @param {workbox-routing~matchCallback} match
     * A callback function that determines whether the route matches a given
     * `fetch` event by returning a non-falsy value.
     * @param {workbox-routing~handlerCallback} handler A callback
     * function that returns a Promise resolving to a Response.
     * @param {string} [method='GET'] The HTTP method to match the Route
     * against.
     */
    constructor(match: RouteMatchCallback, handler: RouteHandler, method?: HTTPMethod);
    /**
     *
     * @param {workbox-routing-handlerCallback} handler A callback
     * function that returns a Promise resolving to a Response
     */
    setCatchHandler(handler: RouteHandler): void;
}
export { Route };

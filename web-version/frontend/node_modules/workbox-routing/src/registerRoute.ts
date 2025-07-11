/*
  Copyright 2019 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {logger} from 'workbox-core/_private/logger.js';
import {WorkboxError} from 'workbox-core/_private/WorkboxError.js';
import {RouteHandler, RouteMatchCallback} from 'workbox-core/types.js';

import {Route} from './Route.js';
import {RegExpRoute} from './RegExpRoute.js';
import {HTTPMethod} from './utils/constants.js';
import {getOrCreateDefaultRouter} from './utils/getOrCreateDefaultRouter.js';

import './_version.js';

/**
 * Easily register a RegExp, string, or function with a caching
 * strategy to a singleton Router instance.
 *
 * This method will generate a Route for you if needed and
 * call {@link workbox-routing.Router#registerRoute}.
 *
 * @param {RegExp|string|workbox-routing.Route~matchCallback|workbox-routing.Route} capture
 * If the capture param is a `Route`, all other arguments will be ignored.
 * @param {workbox-routing~handlerCallback} [handler] A callback
 * function that returns a Promise resulting in a Response. This parameter
 * is required if `capture` is not a `Route` object.
 * @param {string} [method='GET'] The HTTP method to match the Route
 * against.
 * @return {workbox-routing.Route} The generated `Route`.
 *
 * @memberof workbox-routing
 */
function registerRoute(
  capture: RegExp | string | RouteMatchCallback | Route,
  handler?: RouteHandler,
  method?: HTTPMethod,
): Route {
  let route;

  if (typeof capture === 'string') {
    const captureUrl = new URL(capture, location.href);

    if (process.env.NODE_ENV !== 'production') {
      if (!(capture.startsWith('/') || capture.startsWith('http'))) {
        throw new WorkboxError('invalid-string', {
          moduleName: 'workbox-routing',
          funcName: 'registerRoute',
          paramName: 'capture',
        });
      }

      // We want to check if Express-style wildcards are in the pathname only.
      // TODO: Remove this log message in v4.
      const valueToCheck = capture.startsWith('http')
        ? captureUrl.pathname
        : capture;

      // See https://github.com/pillarjs/path-to-regexp#parameters
      const wildcards = '[*:?+]';
      if (new RegExp(`${wildcards}`).exec(valueToCheck)) {
        logger.debug(
          `The '$capture' parameter contains an Express-style wildcard ` +
            `character (${wildcards}). Strings are now always interpreted as ` +
            `exact matches; use a RegExp for partial or wildcard matches.`,
        );
      }
    }

    const matchCallback: RouteMatchCallback = ({url}) => {
      if (process.env.NODE_ENV !== 'production') {
        if (
          url.pathname === captureUrl.pathname &&
          url.origin !== captureUrl.origin
        ) {
          logger.debug(
            `${capture} only partially matches the cross-origin URL ` +
              `${url.toString()}. This route will only handle cross-origin requests ` +
              `if they match the entire URL.`,
          );
        }
      }

      return url.href === captureUrl.href;
    };

    // If `capture` is a string then `handler` and `method` must be present.
    route = new Route(matchCallback, handler!, method);
  } else if (capture instanceof RegExp) {
    // If `capture` is a `RegExp` then `handler` and `method` must be present.
    route = new RegExpRoute(capture, handler!, method);
  } else if (typeof capture === 'function') {
    // If `capture` is a function then `handler` and `method` must be present.
    route = new Route(capture, handler!, method);
  } else if (capture instanceof Route) {
    route = capture;
  } else {
    throw new WorkboxError('unsupported-route-type', {
      moduleName: 'workbox-routing',
      funcName: 'registerRoute',
      paramName: 'capture',
    });
  }

  const defaultRouter = getOrCreateDefaultRouter();
  defaultRouter.registerRoute(route);

  return route;
}

export {registerRoute};

/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {assert} from 'workbox-core/_private/assert.js';
import {RouteHandler, RouteHandlerObject} from 'workbox-core/types.js';

import '../_version.js';

/**
 * @param {function()|Object} handler Either a function, or an object with a
 * 'handle' method.
 * @return {Object} An object with a handle method.
 *
 * @private
 */
export const normalizeHandler = (handler: RouteHandler): RouteHandlerObject => {
  if (handler && typeof handler === 'object') {
    if (process.env.NODE_ENV !== 'production') {
      assert!.hasMethod(handler, 'handle', {
        moduleName: 'workbox-routing',
        className: 'Route',
        funcName: 'constructor',
        paramName: 'handler',
      });
    }
    return handler;
  } else {
    if (process.env.NODE_ENV !== 'production') {
      assert!.isType(handler, 'function', {
        moduleName: 'workbox-routing',
        className: 'Route',
        funcName: 'constructor',
        paramName: 'handler',
      });
    }
    return {handle: handler};
  }
};

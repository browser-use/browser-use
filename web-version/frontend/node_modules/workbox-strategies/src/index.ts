/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {CacheFirst} from './CacheFirst.js';
import {CacheOnly} from './CacheOnly.js';
import {NetworkFirst, NetworkFirstOptions} from './NetworkFirst.js';
import {NetworkOnly, NetworkOnlyOptions} from './NetworkOnly.js';
import {StaleWhileRevalidate} from './StaleWhileRevalidate.js';
import {Strategy, StrategyOptions} from './Strategy.js';
import {StrategyHandler} from './StrategyHandler.js';
import './_version.js';

// See https://github.com/GoogleChrome/workbox/issues/2946
declare global {
  interface FetchEvent {
    // See https://github.com/GoogleChrome/workbox/issues/2974
    readonly preloadResponse: Promise<any>;
  }
}

/**
 * There are common caching strategies that most service workers will need
 * and use. This module provides simple implementations of these strategies.
 *
 * @module workbox-strategies
 */

export {
  CacheFirst,
  CacheOnly,
  NetworkFirst,
  NetworkFirstOptions,
  NetworkOnly,
  NetworkOnlyOptions,
  StaleWhileRevalidate,
  Strategy,
  StrategyHandler,
  StrategyOptions,
};

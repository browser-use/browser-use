/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
import { CacheFirst } from './CacheFirst.js';
import { CacheOnly } from './CacheOnly.js';
import { NetworkFirst } from './NetworkFirst.js';
import { NetworkOnly } from './NetworkOnly.js';
import { StaleWhileRevalidate } from './StaleWhileRevalidate.js';
import { Strategy } from './Strategy.js';
import { StrategyHandler } from './StrategyHandler.js';
import './_version.js';
/**
 * There are common caching strategies that most service workers will need
 * and use. This module provides simple implementations of these strategies.
 *
 * @module workbox-strategies
 */
export { CacheFirst, CacheOnly, NetworkFirst, NetworkOnly, StaleWhileRevalidate, Strategy, StrategyHandler, };

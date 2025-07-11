import { CacheFirst } from './CacheFirst.js';
import { CacheOnly } from './CacheOnly.js';
import { NetworkFirst, NetworkFirstOptions } from './NetworkFirst.js';
import { NetworkOnly, NetworkOnlyOptions } from './NetworkOnly.js';
import { StaleWhileRevalidate } from './StaleWhileRevalidate.js';
import { Strategy, StrategyOptions } from './Strategy.js';
import { StrategyHandler } from './StrategyHandler.js';
import './_version.js';
declare global {
    interface FetchEvent {
        readonly preloadResponse: Promise<any>;
    }
}
/**
 * There are common caching strategies that most service workers will need
 * and use. This module provides simple implementations of these strategies.
 *
 * @module workbox-strategies
 */
export { CacheFirst, CacheOnly, NetworkFirst, NetworkFirstOptions, NetworkOnly, NetworkOnlyOptions, StaleWhileRevalidate, Strategy, StrategyHandler, StrategyOptions, };

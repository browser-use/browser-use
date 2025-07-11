import { Strategy } from 'workbox-strategies/Strategy.js';
import './_version.js';
export interface WarmStrategyCacheOptions {
    urls: Array<string>;
    strategy: Strategy;
}
/**
 * @memberof workbox-recipes
 
 * @param {Object} options
 * @param {string[]} options.urls Paths to warm the strategy's cache with
 * @param {Strategy} options.strategy Strategy to use
 */
declare function warmStrategyCache(options: WarmStrategyCacheOptions): void;
export { warmStrategyCache };

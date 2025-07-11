import {Strategy} from 'workbox-strategies/Strategy.js';

import './_version.js';

export interface WarmStrategyCacheOptions {
  urls: Array<string>;
  strategy: Strategy;
}

// Give TypeScript the correct global.
declare let self: ServiceWorkerGlobalScope;

/**
 * @memberof workbox-recipes
 
 * @param {Object} options 
 * @param {string[]} options.urls Paths to warm the strategy's cache with
 * @param {Strategy} options.strategy Strategy to use
 */
function warmStrategyCache(options: WarmStrategyCacheOptions): void {
  self.addEventListener('install', (event) => {
    const done = options.urls.map(
      (path) =>
        options.strategy.handleAll({
          event,
          request: new Request(path),
        })[1],
    );

    event.waitUntil(Promise.all(done));
  });
}

export {warmStrategyCache};

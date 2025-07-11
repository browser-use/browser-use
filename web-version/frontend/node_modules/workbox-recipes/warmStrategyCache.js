import './_version.js';
/**
 * @memberof workbox-recipes
 
 * @param {Object} options
 * @param {string[]} options.urls Paths to warm the strategy's cache with
 * @param {Strategy} options.strategy Strategy to use
 */
function warmStrategyCache(options) {
    self.addEventListener('install', (event) => {
        const done = options.urls.map((path) => options.strategy.handleAll({
            event,
            request: new Request(path),
        })[1]);
        event.waitUntil(Promise.all(done));
    });
}
export { warmStrategyCache };

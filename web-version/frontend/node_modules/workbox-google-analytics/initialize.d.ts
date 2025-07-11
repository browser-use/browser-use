import './_version.js';
export interface GoogleAnalyticsInitializeOptions {
    cacheName?: string;
    parameterOverrides?: {
        [paramName: string]: string;
    };
    hitFilter?: (params: URLSearchParams) => void;
}
/**
 * @param {Object=} [options]
 * @param {Object} [options.cacheName] The cache name to store and retrieve
 *     analytics.js. Defaults to the cache names provided by `workbox-core`.
 * @param {Object} [options.parameterOverrides]
 *     [Measurement Protocol parameters](https://developers.google.com/analytics/devguides/collection/protocol/v1/parameters),
 *     expressed as key/value pairs, to be added to replayed Google Analytics
 *     requests. This can be used to, e.g., set a custom dimension indicating
 *     that the request was replayed.
 * @param {Function} [options.hitFilter] A function that allows you to modify
 *     the hit parameters prior to replaying
 *     the hit. The function is invoked with the original hit's URLSearchParams
 *     object as its only argument.
 *
 * @memberof workbox-google-analytics
 */
declare const initialize: (options?: GoogleAnalyticsInitializeOptions) => void;
export { initialize };

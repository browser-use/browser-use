import { PartialCacheNameDetails } from './_private/cacheNames.js';
import './_version.js';
/**
 * Modifies the default cache names used by the Workbox packages.
 * Cache names are generated as `<prefix>-<Cache Name>-<suffix>`.
 *
 * @param {Object} details
 * @param {Object} [details.prefix] The string to add to the beginning of
 *     the precache and runtime cache names.
 * @param {Object} [details.suffix] The string to add to the end of
 *     the precache and runtime cache names.
 * @param {Object} [details.precache] The cache name to use for precache
 *     caching.
 * @param {Object} [details.runtime] The cache name to use for runtime caching.
 * @param {Object} [details.googleAnalytics] The cache name to use for
 *     `workbox-google-analytics` caching.
 *
 * @memberof workbox-core
 */
declare function setCacheNameDetails(details: PartialCacheNameDetails): void;
export { setCacheNameDetails };

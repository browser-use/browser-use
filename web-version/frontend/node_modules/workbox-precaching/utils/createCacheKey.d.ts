import { PrecacheEntry } from '../_types.js';
import '../_version.js';
interface CacheKey {
    cacheKey: string;
    url: string;
}
/**
 * Converts a manifest entry into a versioned URL suitable for precaching.
 *
 * @param {Object|string} entry
 * @return {string} A URL with versioning info.
 *
 * @private
 * @memberof workbox-precaching
 */
export declare function createCacheKey(entry: PrecacheEntry | string): CacheKey;
export {};

import '../_version.js';
/**
 * Matches an item in the cache, ignoring specific URL params. This is similar
 * to the `ignoreSearch` option, but it allows you to ignore just specific
 * params (while continuing to match on the others).
 *
 * @private
 * @param {Cache} cache
 * @param {Request} request
 * @param {Object} matchOptions
 * @param {Array<string>} ignoreParams
 * @return {Promise<Response|undefined>}
 */
declare function cacheMatchIgnoreParams(cache: Cache, request: Request, ignoreParams: string[], matchOptions?: CacheQueryOptions): Promise<Response | undefined>;
export { cacheMatchIgnoreParams };

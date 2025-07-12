import { WorkboxPlugin } from 'workbox-core/types.js';
import { CacheableResponseOptions } from './CacheableResponse.js';
import './_version.js';
/**
 * A class implementing the `cacheWillUpdate` lifecycle callback. This makes it
 * easier to add in cacheability checks to requests made via Workbox's built-in
 * strategies.
 *
 * @memberof workbox-cacheable-response
 */
declare class CacheableResponsePlugin implements WorkboxPlugin {
    private readonly _cacheableResponse;
    /**
     * To construct a new CacheableResponsePlugin instance you must provide at
     * least one of the `config` properties.
     *
     * If both `statuses` and `headers` are specified, then both conditions must
     * be met for the `Response` to be considered cacheable.
     *
     * @param {Object} config
     * @param {Array<number>} [config.statuses] One or more status codes that a
     * `Response` can have and be considered cacheable.
     * @param {Object<string,string>} [config.headers] A mapping of header names
     * and expected values that a `Response` can have and be considered cacheable.
     * If multiple headers are provided, only one needs to be present.
     */
    constructor(config: CacheableResponseOptions);
    /**
     * @param {Object} options
     * @param {Response} options.response
     * @return {Response|null}
     * @private
     */
    cacheWillUpdate: WorkboxPlugin['cacheWillUpdate'];
}
export { CacheableResponsePlugin };

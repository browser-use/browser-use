import { PrecacheRouteOptions } from '../_types.js';
import '../_version.js';
/**
 * This function will take the request URL and manipulate it based on the
 * configuration options.
 *
 * @param {string} url
 * @param {Object} options
 * @return {string} Returns the URL in the cache that matches the request,
 * if possible.
 *
 * @private
 */
export declare const getCacheKeyForURL: (url: string, options: PrecacheRouteOptions) => string | void;

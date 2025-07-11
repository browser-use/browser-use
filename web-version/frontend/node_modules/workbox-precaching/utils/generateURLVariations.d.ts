import { PrecacheRouteOptions } from '../_types.js';
import '../_version.js';
/**
 * Generator function that yields possible variations on the original URL to
 * check, one at a time.
 *
 * @param {string} url
 * @param {Object} options
 *
 * @private
 * @memberof workbox-precaching
 */
export declare function generateURLVariations(url: string, { ignoreURLParametersMatching, directoryIndex, cleanURLs, urlManipulation, }?: PrecacheRouteOptions): Generator<string, void, unknown>;

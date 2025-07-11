import './_version.js';
export interface OfflineFallbackOptions {
    pageFallback?: string;
    imageFallback?: string;
    fontFallback?: string;
}
/**
 * An implementation of the [comprehensive fallbacks recipe]{@link https://developers.google.com/web/tools/workbox/guides/advanced-recipes#comprehensive_fallbacks}. Be sure to include the fallbacks in your precache injection
 *
 * @memberof workbox-recipes
 *
 * @param {Object} [options]
 * @param {string} [options.pageFallback] Precache name to match for pag fallbacks. Defaults to offline.html
 * @param {string} [options.imageFallback] Precache name to match for image fallbacks.
 * @param {string} [options.fontFallback] Precache name to match for font fallbacks.
 */
declare function offlineFallback(options?: OfflineFallbackOptions): void;
export { offlineFallback };

import './_version.js';
export interface GoogleFontCacheOptions {
    cachePrefix?: string;
    maxAgeSeconds?: number;
    maxEntries?: number;
}
/**
 * An implementation of the [Google fonts]{@link https://developers.google.com/web/tools/workbox/guides/common-recipes#google_fonts} caching recipe
 *
 * @memberof workbox-recipes
 *
 * @param {Object} [options]
 * @param {string} [options.cachePrefix] Cache prefix for caching stylesheets and webfonts. Defaults to google-fonts
 * @param {number} [options.maxAgeSeconds] Maximum age, in seconds, that font entries will be cached for. Defaults to 1 year
 * @param {number} [options.maxEntries] Maximum number of fonts that will be cached. Defaults to 30
 */
declare function googleFontsCache(options?: GoogleFontCacheOptions): void;
export { googleFontsCache };

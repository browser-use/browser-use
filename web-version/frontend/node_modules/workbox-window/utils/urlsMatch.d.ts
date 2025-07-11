import '../_version.js';
/**
 * Returns true if two URLs have the same `.href` property. The URLS can be
 * relative, and if they are the current location href is used to resolve URLs.
 *
 * @private
 * @param {string} url1
 * @param {string} url2
 * @return {boolean}
 */
export declare function urlsMatch(url1: string, url2: string): boolean;

import './_version.js';
/**
 * Adds an `activate` event listener which will clean up incompatible
 * precaches that were created by older versions of Workbox.
 *
 * @memberof workbox-precaching
 */
declare function cleanupOutdatedCaches(): void;
export { cleanupOutdatedCaches };

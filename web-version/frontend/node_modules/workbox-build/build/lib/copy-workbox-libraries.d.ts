/**
 * This copies over a set of runtime libraries used by Workbox into a
 * local directory, which should be deployed alongside your service worker file.
 *
 * As an alternative to deploying these local copies, you could instead use
 * Workbox from its official CDN URL.
 *
 * This method is exposed for the benefit of developers using
 * {@link workbox-build.injectManifest} who would
 * prefer not to use the CDN copies of Workbox. Developers using
 * {@link workbox-build.generateSW} don't need to
 * explicitly call this method.
 *
 * @param {string} destDirectory The path to the parent directory under which
 * the new directory of libraries will be created.
 * @return {Promise<string>} The name of the newly created directory.
 *
 * @alias workbox-build.copyWorkboxLibraries
 */
export declare function copyWorkboxLibraries(destDirectory: string): Promise<string>;

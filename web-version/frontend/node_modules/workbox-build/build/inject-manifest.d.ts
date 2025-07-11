import { BuildResult, InjectManifestOptions } from './types';
/**
 * This method creates a list of URLs to precache, referred to as a "precache
 * manifest", based on the options you provide.
 *
 * The manifest is injected into the `swSrc` file, and the placeholder string
 * `injectionPoint` determines where in the file the manifest should go.
 *
 * The final service worker file, with the manifest injected, is written to
 * disk at `swDest`.
 *
 * This method will not compile or bundle your `swSrc` file; it just handles
 * injecting the manifest.
 *
 * ```
 * // The following lists some common options; see the rest of the documentation
 * // for the full set of options and defaults.
 * const {count, size, warnings} = await injectManifest({
 *   dontCacheBustURLsMatching: [new RegExp('...')],
 *   globDirectory: '...',
 *   globPatterns: ['...', '...'],
 *   maximumFileSizeToCacheInBytes: ...,
 *   swDest: '...',
 *   swSrc: '...',
 * });
 * ```
 *
 * @memberof workbox-build
 */
export declare function injectManifest(config: InjectManifestOptions): Promise<BuildResult>;

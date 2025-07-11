import { BasePartial, FileDetails, ManifestEntry } from '../types';
/**
 * A `ManifestTransform` function can be used to modify the modify the `url` or
 * `revision` properties of some or all of the
 * {@link workbox-build.ManifestEntry} in the manifest.
 *
 * Deleting the `revision` property of an entry will cause
 * the corresponding `url` to be precached without cache-busting parameters
 * applied, which is to say, it implies that the URL itself contains
 * proper versioning info. If the `revision` property is present, it must be
 * set to a string.
 *
 * @example A transformation that prepended the origin of a CDN for any
 * URL starting with '/assets/' could be implemented as:
 *
 * const cdnTransform = async (manifestEntries) => {
 *   const manifest = manifestEntries.map(entry => {
 *     const cdnOrigin = 'https://example.com';
 *     if (entry.url.startsWith('/assets/')) {
 *       entry.url = cdnOrigin + entry.url;
 *     }
 *     return entry;
 *   });
 *   return {manifest, warnings: []};
 * };
 *
 * @example A transformation that nulls the revision field when the
 * URL contains an 8-character hash surrounded by '.', indicating that it
 * already contains revision information:
 *
 * const removeRevisionTransform = async (manifestEntries) => {
 *   const manifest = manifestEntries.map(entry => {
 *     const hashRegExp = /\.\w{8}\./;
 *     if (entry.url.match(hashRegExp)) {
 *       entry.revision = null;
 *     }
 *     return entry;
 *   });
 *   return {manifest, warnings: []};
 * };
 *
 * @callback ManifestTransform
 * @param {Array<workbox-build.ManifestEntry>} manifestEntries The full
 * array of entries, prior to the current transformation.
 * @param {Object} [compilation] When used in the webpack plugins, this param
 * will be set to the current `compilation`.
 * @return {Promise<workbox-build.ManifestTransformResult>}
 * The array of entries with the transformation applied, and optionally, any
 * warnings that should be reported back to the build tool.
 *
 * @memberof workbox-build
 */
interface ManifestTransformResultWithWarnings {
    count: number;
    size: number;
    manifestEntries: ManifestEntry[];
    warnings: string[];
}
export declare function transformManifest({ additionalManifestEntries, dontCacheBustURLsMatching, fileDetails, manifestTransforms, maximumFileSizeToCacheInBytes, modifyURLPrefix, transformParam, }: BasePartial & {
    fileDetails: Array<FileDetails>;
    transformParam?: unknown;
}): Promise<ManifestTransformResultWithWarnings>;
export {};

"use strict";
/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
Object.defineProperty(exports, "__esModule", { value: true });
exports.transformManifest = void 0;
const additional_manifest_entries_transform_1 = require("./additional-manifest-entries-transform");
const errors_1 = require("./errors");
const maximum_size_transform_1 = require("./maximum-size-transform");
const modify_url_prefix_transform_1 = require("./modify-url-prefix-transform");
const no_revision_for_urls_matching_transform_1 = require("./no-revision-for-urls-matching-transform");
async function transformManifest({ additionalManifestEntries, dontCacheBustURLsMatching, fileDetails, manifestTransforms, maximumFileSizeToCacheInBytes, modifyURLPrefix, transformParam, }) {
    const allWarnings = [];
    // Take the array of fileDetail objects and convert it into an array of
    // {url, revision, size} objects, with \ replaced with /.
    const normalizedManifest = fileDetails.map((fileDetails) => {
        return {
            url: fileDetails.file.replace(/\\/g, '/'),
            revision: fileDetails.hash,
            size: fileDetails.size,
        };
    });
    const transformsToApply = [];
    if (maximumFileSizeToCacheInBytes) {
        transformsToApply.push((0, maximum_size_transform_1.maximumSizeTransform)(maximumFileSizeToCacheInBytes));
    }
    if (modifyURLPrefix) {
        transformsToApply.push((0, modify_url_prefix_transform_1.modifyURLPrefixTransform)(modifyURLPrefix));
    }
    if (dontCacheBustURLsMatching) {
        transformsToApply.push((0, no_revision_for_urls_matching_transform_1.noRevisionForURLsMatchingTransform)(dontCacheBustURLsMatching));
    }
    // Run any manifestTransforms functions second-to-last.
    if (manifestTransforms) {
        transformsToApply.push(...manifestTransforms);
    }
    // Run additionalManifestEntriesTransform last.
    if (additionalManifestEntries) {
        transformsToApply.push((0, additional_manifest_entries_transform_1.additionalManifestEntriesTransform)(additionalManifestEntries));
    }
    let transformedManifest = normalizedManifest;
    for (const transform of transformsToApply) {
        const result = await transform(transformedManifest, transformParam);
        if (!('manifest' in result)) {
            throw new Error(errors_1.errors['bad-manifest-transforms-return-value']);
        }
        transformedManifest = result.manifest;
        allWarnings.push(...(result.warnings || []));
    }
    // Generate some metadata about the manifest before we clear out the size
    // properties from each entry.
    const count = transformedManifest.length;
    let size = 0;
    for (const manifestEntry of transformedManifest) {
        size += manifestEntry.size || 0;
        delete manifestEntry.size;
    }
    return {
        count,
        size,
        manifestEntries: transformedManifest,
        warnings: allWarnings,
    };
}
exports.transformManifest = transformManifest;

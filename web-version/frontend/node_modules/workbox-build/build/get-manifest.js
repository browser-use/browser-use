"use strict";
/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
Object.defineProperty(exports, "__esModule", { value: true });
exports.getManifest = void 0;
const get_file_manifest_entries_1 = require("./lib/get-file-manifest-entries");
const validate_options_1 = require("./lib/validate-options");
/**
 * This method returns a list of URLs to precache, referred to as a "precache
 * manifest", along with details about the number of entries and their size,
 * based on the options you provide.
 *
 * ```
 * // The following lists some common options; see the rest of the documentation
 * // for the full set of options and defaults.
 * const {count, manifestEntries, size, warnings} = await getManifest({
 *   dontCacheBustURLsMatching: [new RegExp('...')],
 *   globDirectory: '...',
 *   globPatterns: ['...', '...'],
 *   maximumFileSizeToCacheInBytes: ...,
 * });
 * ```
 *
 * @memberof workbox-build
 */
async function getManifest(config) {
    const options = (0, validate_options_1.validateGetManifestOptions)(config);
    return await (0, get_file_manifest_entries_1.getFileManifestEntries)(options);
}
exports.getManifest = getManifest;

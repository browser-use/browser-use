"use strict";
/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.generateSW = void 0;
const upath_1 = __importDefault(require("upath"));
const get_file_manifest_entries_1 = require("./lib/get-file-manifest-entries");
const rebase_path_1 = require("./lib/rebase-path");
const validate_options_1 = require("./lib/validate-options");
const write_sw_using_default_template_1 = require("./lib/write-sw-using-default-template");
/**
 * This method creates a list of URLs to precache, referred to as a "precache
 * manifest", based on the options you provide.
 *
 * It also takes in additional options that configures the service worker's
 * behavior, like any `runtimeCaching` rules it should use.
 *
 * Based on the precache manifest and the additional configuration, it writes
 * a ready-to-use service worker file to disk at `swDest`.
 *
 * ```
 * // The following lists some common options; see the rest of the documentation
 * // for the full set of options and defaults.
 * const {count, size, warnings} = await generateSW({
 *   dontCacheBustURLsMatching: [new RegExp('...')],
 *   globDirectory: '...',
 *   globPatterns: ['...', '...'],
 *   maximumFileSizeToCacheInBytes: ...,
 *   navigateFallback: '...',
 *   runtimeCaching: [{
 *     // Routing via a matchCallback function:
 *     urlPattern: ({request, url}) => ...,
 *     handler: '...',
 *     options: {
 *       cacheName: '...',
 *       expiration: {
 *         maxEntries: ...,
 *       },
 *     },
 *   }, {
 *     // Routing via a RegExp:
 *     urlPattern: new RegExp('...'),
 *     handler: '...',
 *     options: {
 *       cacheName: '...',
 *       plugins: [..., ...],
 *     },
 *   }],
 *   skipWaiting: ...,
 *   swDest: '...',
 * });
 * ```
 *
 * @memberof workbox-build
 */
async function generateSW(config) {
    const options = (0, validate_options_1.validateGenerateSWOptions)(config);
    let entriesResult;
    if (options.globDirectory) {
        // Make sure we leave swDest out of the precache manifest.
        options.globIgnores.push((0, rebase_path_1.rebasePath)({
            baseDirectory: options.globDirectory,
            file: options.swDest,
        }));
        // If we create an extra external runtime file, ignore that, too.
        // See https://rollupjs.org/guide/en/#outputchunkfilenames for naming.
        if (!options.inlineWorkboxRuntime) {
            const swDestDir = upath_1.default.dirname(options.swDest);
            const workboxRuntimeFile = upath_1.default.join(swDestDir, 'workbox-*.js');
            options.globIgnores.push((0, rebase_path_1.rebasePath)({
                baseDirectory: options.globDirectory,
                file: workboxRuntimeFile,
            }));
        }
        // We've previously asserted that options.globDirectory is set, so this
        // should be a safe cast.
        entriesResult = await (0, get_file_manifest_entries_1.getFileManifestEntries)(options);
    }
    else {
        entriesResult = {
            count: 0,
            manifestEntries: [],
            size: 0,
            warnings: [],
        };
    }
    const filePaths = await (0, write_sw_using_default_template_1.writeSWUsingDefaultTemplate)(Object.assign({
        manifestEntries: entriesResult.manifestEntries,
    }, options));
    return {
        filePaths,
        count: entriesResult.count,
        size: entriesResult.size,
        warnings: entriesResult.warnings,
    };
}
exports.generateSW = generateSW;

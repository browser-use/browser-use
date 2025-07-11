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
exports.injectManifest = void 0;
const assert_1 = __importDefault(require("assert"));
const fs_extra_1 = __importDefault(require("fs-extra"));
const fast_json_stable_stringify_1 = __importDefault(require("fast-json-stable-stringify"));
const upath_1 = __importDefault(require("upath"));
const errors_1 = require("./lib/errors");
const escape_regexp_1 = require("./lib/escape-regexp");
const get_file_manifest_entries_1 = require("./lib/get-file-manifest-entries");
const get_source_map_url_1 = require("./lib/get-source-map-url");
const rebase_path_1 = require("./lib/rebase-path");
const replace_and_update_source_map_1 = require("./lib/replace-and-update-source-map");
const translate_url_to_sourcemap_paths_1 = require("./lib/translate-url-to-sourcemap-paths");
const validate_options_1 = require("./lib/validate-options");
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
async function injectManifest(config) {
    const options = (0, validate_options_1.validateInjectManifestOptions)(config);
    // Make sure we leave swSrc and swDest out of the precache manifest.
    for (const file of [options.swSrc, options.swDest]) {
        options.globIgnores.push((0, rebase_path_1.rebasePath)({
            file,
            baseDirectory: options.globDirectory,
        }));
    }
    const globalRegexp = new RegExp((0, escape_regexp_1.escapeRegExp)(options.injectionPoint), 'g');
    const { count, size, manifestEntries, warnings } = await (0, get_file_manifest_entries_1.getFileManifestEntries)(options);
    let swFileContents;
    try {
        swFileContents = await fs_extra_1.default.readFile(options.swSrc, 'utf8');
    }
    catch (error) {
        throw new Error(`${errors_1.errors['invalid-sw-src']} ${error instanceof Error && error.message ? error.message : ''}`);
    }
    const injectionResults = swFileContents.match(globalRegexp);
    // See https://github.com/GoogleChrome/workbox/issues/2230
    const injectionPoint = options.injectionPoint ? options.injectionPoint : '';
    if (!injectionResults) {
        if (upath_1.default.resolve(options.swSrc) === upath_1.default.resolve(options.swDest)) {
            throw new Error(`${errors_1.errors['same-src-and-dest']} ${injectionPoint}`);
        }
        throw new Error(`${errors_1.errors['injection-point-not-found']} ${injectionPoint}`);
    }
    (0, assert_1.default)(injectionResults.length === 1, `${errors_1.errors['multiple-injection-points']} ${injectionPoint}`);
    const manifestString = (0, fast_json_stable_stringify_1.default)(manifestEntries);
    const filesToWrite = {};
    const url = (0, get_source_map_url_1.getSourceMapURL)(swFileContents);
    // See https://github.com/GoogleChrome/workbox/issues/2957
    const { destPath, srcPath, warning } = (0, translate_url_to_sourcemap_paths_1.translateURLToSourcemapPaths)(url, options.swSrc, options.swDest);
    if (warning) {
        warnings.push(warning);
    }
    // If our swSrc file contains a sourcemap, we would invalidate that
    // mapping if we just replaced injectionPoint with the stringified manifest.
    // Instead, we need to update the swDest contents as well as the sourcemap
    // (assuming it's a real file, not a data: URL) at the same time.
    // See https://github.com/GoogleChrome/workbox/issues/2235
    // and https://github.com/GoogleChrome/workbox/issues/2648
    if (srcPath && destPath) {
        const originalMap = (await fs_extra_1.default.readJSON(srcPath, {
            encoding: 'utf8',
        }));
        const { map, source } = await (0, replace_and_update_source_map_1.replaceAndUpdateSourceMap)({
            originalMap,
            jsFilename: upath_1.default.basename(options.swDest),
            originalSource: swFileContents,
            replaceString: manifestString,
            searchString: options.injectionPoint,
        });
        filesToWrite[options.swDest] = source;
        filesToWrite[destPath] = map;
    }
    else {
        // If there's no sourcemap associated with swSrc, a simple string
        // replacement will suffice.
        filesToWrite[options.swDest] = swFileContents.replace(globalRegexp, manifestString);
    }
    for (const [file, contents] of Object.entries(filesToWrite)) {
        try {
            await fs_extra_1.default.mkdirp(upath_1.default.dirname(file));
        }
        catch (error) {
            throw new Error(errors_1.errors['unable-to-make-sw-directory'] +
                ` '${error instanceof Error && error.message ? error.message : ''}'`);
        }
        await fs_extra_1.default.writeFile(file, contents);
    }
    return {
        count,
        size,
        warnings,
        // Use upath.resolve() to make all the paths absolute.
        filePaths: Object.keys(filesToWrite).map((f) => upath_1.default.resolve(f)),
    };
}
exports.injectManifest = injectManifest;

/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {RawSourceMap} from 'source-map';
import assert from 'assert';
import fse from 'fs-extra';
import stringify from 'fast-json-stable-stringify';
import upath from 'upath';

import {BuildResult, InjectManifestOptions} from './types';
import {errors} from './lib/errors';
import {escapeRegExp} from './lib/escape-regexp';
import {getFileManifestEntries} from './lib/get-file-manifest-entries';
import {getSourceMapURL} from './lib/get-source-map-url';
import {rebasePath} from './lib/rebase-path';
import {replaceAndUpdateSourceMap} from './lib/replace-and-update-source-map';
import {translateURLToSourcemapPaths} from './lib/translate-url-to-sourcemap-paths';
import {validateInjectManifestOptions} from './lib/validate-options';

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
export async function injectManifest(
  config: InjectManifestOptions,
): Promise<BuildResult> {
  const options = validateInjectManifestOptions(config);

  // Make sure we leave swSrc and swDest out of the precache manifest.
  for (const file of [options.swSrc, options.swDest]) {
    options.globIgnores!.push(
      rebasePath({
        file,
        baseDirectory: options.globDirectory,
      }),
    );
  }

  const globalRegexp = new RegExp(escapeRegExp(options.injectionPoint!), 'g');

  const {count, size, manifestEntries, warnings} = await getFileManifestEntries(
    options,
  );
  let swFileContents: string;
  try {
    swFileContents = await fse.readFile(options.swSrc, 'utf8');
  } catch (error) {
    throw new Error(
      `${errors['invalid-sw-src']} ${
        error instanceof Error && error.message ? error.message : ''
      }`,
    );
  }

  const injectionResults = swFileContents.match(globalRegexp);
  // See https://github.com/GoogleChrome/workbox/issues/2230
  const injectionPoint = options.injectionPoint ? options.injectionPoint : '';
  if (!injectionResults) {
    if (upath.resolve(options.swSrc) === upath.resolve(options.swDest)) {
      throw new Error(`${errors['same-src-and-dest']} ${injectionPoint}`);
    }
    throw new Error(`${errors['injection-point-not-found']} ${injectionPoint}`);
  }

  assert(
    injectionResults.length === 1,
    `${errors['multiple-injection-points']} ${injectionPoint}`,
  );

  const manifestString = stringify(manifestEntries);
  const filesToWrite: {[key: string]: string} = {};

  const url = getSourceMapURL(swFileContents);
  // See https://github.com/GoogleChrome/workbox/issues/2957
  const {destPath, srcPath, warning} = translateURLToSourcemapPaths(
    url,
    options.swSrc,
    options.swDest,
  );
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
    const originalMap = (await fse.readJSON(srcPath, {
      encoding: 'utf8',
    })) as RawSourceMap;

    const {map, source} = await replaceAndUpdateSourceMap({
      originalMap,
      jsFilename: upath.basename(options.swDest),
      originalSource: swFileContents,
      replaceString: manifestString,
      searchString: options.injectionPoint!,
    });

    filesToWrite[options.swDest] = source;
    filesToWrite[destPath] = map;
  } else {
    // If there's no sourcemap associated with swSrc, a simple string
    // replacement will suffice.
    filesToWrite[options.swDest] = swFileContents.replace(
      globalRegexp,
      manifestString,
    );
  }

  for (const [file, contents] of Object.entries(filesToWrite)) {
    try {
      await fse.mkdirp(upath.dirname(file));
    } catch (error: unknown) {
      throw new Error(
        errors['unable-to-make-sw-directory'] +
          ` '${error instanceof Error && error.message ? error.message : ''}'`,
      );
    }

    await fse.writeFile(file, contents);
  }

  return {
    count,
    size,
    warnings,
    // Use upath.resolve() to make all the paths absolute.
    filePaths: Object.keys(filesToWrite).map((f) => upath.resolve(f)),
  };
}

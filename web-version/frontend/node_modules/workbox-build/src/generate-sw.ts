/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import upath from 'upath';

import {BuildResult, GetManifestOptions, GenerateSWOptions} from './types';
import {getFileManifestEntries} from './lib/get-file-manifest-entries';
import {rebasePath} from './lib/rebase-path';
import {validateGenerateSWOptions} from './lib/validate-options';
import {writeSWUsingDefaultTemplate} from './lib/write-sw-using-default-template';

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
export async function generateSW(
  config: GenerateSWOptions,
): Promise<BuildResult> {
  const options = validateGenerateSWOptions(config);
  let entriesResult;

  if (options.globDirectory) {
    // Make sure we leave swDest out of the precache manifest.
    options.globIgnores!.push(
      rebasePath({
        baseDirectory: options.globDirectory,
        file: options.swDest,
      }),
    );

    // If we create an extra external runtime file, ignore that, too.
    // See https://rollupjs.org/guide/en/#outputchunkfilenames for naming.
    if (!options.inlineWorkboxRuntime) {
      const swDestDir = upath.dirname(options.swDest);
      const workboxRuntimeFile = upath.join(swDestDir, 'workbox-*.js');
      options.globIgnores!.push(
        rebasePath({
          baseDirectory: options.globDirectory,
          file: workboxRuntimeFile,
        }),
      );
    }

    // We've previously asserted that options.globDirectory is set, so this
    // should be a safe cast.
    entriesResult = await getFileManifestEntries(options as GetManifestOptions);
  } else {
    entriesResult = {
      count: 0,
      manifestEntries: [],
      size: 0,
      warnings: [],
    };
  }

  const filePaths = await writeSWUsingDefaultTemplate(
    Object.assign(
      {
        manifestEntries: entriesResult.manifestEntries,
      },
      options,
    ),
  );

  return {
    filePaths,
    count: entriesResult.count,
    size: entriesResult.size,
    warnings: entriesResult.warnings,
  };
}

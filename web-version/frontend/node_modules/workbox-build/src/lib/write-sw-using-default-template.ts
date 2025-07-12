/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import fse from 'fs-extra';
import upath from 'upath';

import {bundle} from './bundle';
import {errors} from './errors';
import {GenerateSWOptions, ManifestEntry} from '../types';
import {populateSWTemplate} from './populate-sw-template';

export async function writeSWUsingDefaultTemplate({
  babelPresetEnvTargets,
  cacheId,
  cleanupOutdatedCaches,
  clientsClaim,
  directoryIndex,
  disableDevLogs,
  ignoreURLParametersMatching,
  importScripts,
  inlineWorkboxRuntime,
  manifestEntries,
  mode,
  navigateFallback,
  navigateFallbackDenylist,
  navigateFallbackAllowlist,
  navigationPreload,
  offlineGoogleAnalytics,
  runtimeCaching,
  skipWaiting,
  sourcemap,
  swDest,
}: GenerateSWOptions & {manifestEntries: Array<ManifestEntry>}): Promise<
  Array<string>
> {
  const outputDir = upath.dirname(swDest);
  try {
    await fse.mkdirp(outputDir);
  } catch (error) {
    throw new Error(
      `${errors['unable-to-make-sw-directory']}. ` +
        `'${error instanceof Error && error.message ? error.message : ''}'`,
    );
  }

  const unbundledCode = populateSWTemplate({
    cacheId,
    cleanupOutdatedCaches,
    clientsClaim,
    directoryIndex,
    disableDevLogs,
    ignoreURLParametersMatching,
    importScripts,
    manifestEntries,
    navigateFallback,
    navigateFallbackDenylist,
    navigateFallbackAllowlist,
    navigationPreload,
    offlineGoogleAnalytics,
    runtimeCaching,
    skipWaiting,
  });

  try {
    const files = await bundle({
      babelPresetEnvTargets,
      inlineWorkboxRuntime,
      mode,
      sourcemap,
      swDest,
      unbundledCode,
    });

    const filePaths: Array<string> = [];

    for (const file of files) {
      const filePath = upath.resolve(file.name);
      filePaths.push(filePath);
      await fse.writeFile(filePath, file.contents);
    }

    return filePaths;
  } catch (error) {
    const err = error as NodeJS.ErrnoException;
    if (err.code === 'EISDIR') {
      // See https://github.com/GoogleChrome/workbox/issues/612
      throw new Error(errors['sw-write-failure-directory']);
    }
    throw new Error(`${errors['sw-write-failure']} '${err.message}'`);
  }
}

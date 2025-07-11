/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import template from 'lodash/template';

import {errors} from './errors';
import {GeneratePartial, ManifestEntry} from '../types';
import {ModuleRegistry} from './module-registry';
import {runtimeCachingConverter} from './runtime-caching-converter';
import {stringifyWithoutComments} from './stringify-without-comments';
import {swTemplate} from '../templates/sw-template';

export function populateSWTemplate({
  cacheId,
  cleanupOutdatedCaches,
  clientsClaim,
  directoryIndex,
  disableDevLogs,
  ignoreURLParametersMatching,
  importScripts,
  manifestEntries = [],
  navigateFallback,
  navigateFallbackDenylist,
  navigateFallbackAllowlist,
  navigationPreload,
  offlineGoogleAnalytics,
  runtimeCaching = [],
  skipWaiting,
}: GeneratePartial & {manifestEntries?: Array<ManifestEntry>}): string {
  // There needs to be at least something to precache, or else runtime caching.
  if (!(manifestEntries?.length > 0 || runtimeCaching.length > 0)) {
    throw new Error(errors['no-manifest-entries-or-runtime-caching']);
  }

  // These are all options that can be passed to the precacheAndRoute() method.
  const precacheOptions = {
    directoryIndex,
    // An array of RegExp objects can't be serialized by JSON.stringify()'s
    // default behavior, so if it's given, convert it manually.
    ignoreURLParametersMatching: ignoreURLParametersMatching
      ? ([] as Array<RegExp>)
      : undefined,
  };

  let precacheOptionsString = JSON.stringify(precacheOptions, null, 2);
  if (ignoreURLParametersMatching) {
    precacheOptionsString = precacheOptionsString.replace(
      `"ignoreURLParametersMatching": []`,
      `"ignoreURLParametersMatching": [` +
        `${ignoreURLParametersMatching.join(', ')}]`,
    );
  }

  let offlineAnalyticsConfigString: string | undefined = undefined;
  if (offlineGoogleAnalytics) {
    // If offlineGoogleAnalytics is a truthy value, we need to convert it to the
    // format expected by the template.
    offlineAnalyticsConfigString =
      offlineGoogleAnalytics === true
        ? // If it's the literal value true, then use an empty config string.
          '{}'
        : // Otherwise, convert the config object into a more complex string, taking
          // into account the fact that functions might need to be stringified.
          stringifyWithoutComments(offlineGoogleAnalytics);
  }

  const moduleRegistry = new ModuleRegistry();

  try {
    const populatedTemplate = template(swTemplate)({
      cacheId,
      cleanupOutdatedCaches,
      clientsClaim,
      disableDevLogs,
      importScripts,
      manifestEntries,
      navigateFallback,
      navigateFallbackDenylist,
      navigateFallbackAllowlist,
      navigationPreload,
      offlineAnalyticsConfigString,
      precacheOptionsString,
      runtimeCaching: runtimeCachingConverter(moduleRegistry, runtimeCaching),
      skipWaiting,
      use: moduleRegistry.use.bind(moduleRegistry),
    });

    const workboxImportStatements = moduleRegistry.getImportStatements();

    // We need the import statements for all of the Workbox runtime modules
    // prepended, so that the correct bundle can be created.
    return workboxImportStatements.join('\n') + populatedTemplate;
  } catch (error) {
    throw new Error(
      `${errors['populating-sw-tmpl-failed']} '${
        error instanceof Error && error.message ? error.message : ''
      }'`,
    );
  }
}

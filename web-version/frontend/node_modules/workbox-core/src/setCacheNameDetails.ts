/*
  Copyright 2019 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {assert} from './_private/assert.js';
import {cacheNames, PartialCacheNameDetails} from './_private/cacheNames.js';
import {WorkboxError} from './_private/WorkboxError.js';
import './_version.js';

/**
 * Modifies the default cache names used by the Workbox packages.
 * Cache names are generated as `<prefix>-<Cache Name>-<suffix>`.
 *
 * @param {Object} details
 * @param {Object} [details.prefix] The string to add to the beginning of
 *     the precache and runtime cache names.
 * @param {Object} [details.suffix] The string to add to the end of
 *     the precache and runtime cache names.
 * @param {Object} [details.precache] The cache name to use for precache
 *     caching.
 * @param {Object} [details.runtime] The cache name to use for runtime caching.
 * @param {Object} [details.googleAnalytics] The cache name to use for
 *     `workbox-google-analytics` caching.
 *
 * @memberof workbox-core
 */
function setCacheNameDetails(details: PartialCacheNameDetails): void {
  if (process.env.NODE_ENV !== 'production') {
    Object.keys(details).forEach((key) => {
      assert!.isType(details[key], 'string', {
        moduleName: 'workbox-core',
        funcName: 'setCacheNameDetails',
        paramName: `details.${key}`,
      });
    });

    if ('precache' in details && details['precache']!.length === 0) {
      throw new WorkboxError('invalid-cache-name', {
        cacheNameId: 'precache',
        value: details['precache'],
      });
    }

    if ('runtime' in details && details['runtime']!.length === 0) {
      throw new WorkboxError('invalid-cache-name', {
        cacheNameId: 'runtime',
        value: details['runtime'],
      });
    }

    if (
      'googleAnalytics' in details &&
      details['googleAnalytics'].length === 0
    ) {
      throw new WorkboxError('invalid-cache-name', {
        cacheNameId: 'googleAnalytics',
        value: details['googleAnalytics'],
      });
    }
  }

  cacheNames.updateDetails(details);
}

export {setCacheNameDetails};

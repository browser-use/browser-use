/*
  Copyright 2020 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {WorkboxPlugin, WorkboxPluginCallbackParam} from 'workbox-core/types.js';

import {PrecacheController} from '../PrecacheController.js';

import '../_version.js';

/**
 * A plugin, designed to be used with PrecacheController, to translate URLs into
 * the corresponding cache key, based on the current revision info.
 *
 * @private
 */
class PrecacheCacheKeyPlugin implements WorkboxPlugin {
  private readonly _precacheController: PrecacheController;

  constructor({precacheController}: {precacheController: PrecacheController}) {
    this._precacheController = precacheController;
  }

  cacheKeyWillBeUsed: WorkboxPlugin['cacheKeyWillBeUsed'] = async ({
    request,
    params,
  }: WorkboxPluginCallbackParam['cacheKeyWillBeUsed']) => {
    // Params is type any, can't change right now.
    /* eslint-disable */
    const cacheKey =
      params?.cacheKey ||
      this._precacheController.getCacheKeyForURL(request.url);
    /* eslint-enable */

    return cacheKey
      ? new Request(cacheKey, {headers: request.headers})
      : request;
  };
}

export {PrecacheCacheKeyPlugin};

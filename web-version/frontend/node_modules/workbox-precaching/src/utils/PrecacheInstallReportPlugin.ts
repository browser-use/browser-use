/*
  Copyright 2020 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {WorkboxPlugin, WorkboxPluginCallbackParam} from 'workbox-core/types.js';

import '../_version.js';

/**
 * A plugin, designed to be used with PrecacheController, to determine the
 * of assets that were updated (or not updated) during the install event.
 *
 * @private
 */
class PrecacheInstallReportPlugin implements WorkboxPlugin {
  updatedURLs: string[] = [];
  notUpdatedURLs: string[] = [];

  handlerWillStart: WorkboxPlugin['handlerWillStart'] = async ({
    request,
    state,
  }: WorkboxPluginCallbackParam['handlerWillStart']) => {
    // TODO: `state` should never be undefined...
    if (state) {
      state.originalRequest = request;
    }
  };

  cachedResponseWillBeUsed: WorkboxPlugin['cachedResponseWillBeUsed'] = async ({
    event,
    state,
    cachedResponse,
  }: WorkboxPluginCallbackParam['cachedResponseWillBeUsed']) => {
    if (event.type === 'install') {
      if (
        state &&
        state.originalRequest &&
        state.originalRequest instanceof Request
      ) {
        // TODO: `state` should never be undefined...
        const url = state.originalRequest.url;

        if (cachedResponse) {
          this.notUpdatedURLs.push(url);
        } else {
          this.updatedURLs.push(url);
        }
      }
    }
    return cachedResponse;
  };
}

export {PrecacheInstallReportPlugin};

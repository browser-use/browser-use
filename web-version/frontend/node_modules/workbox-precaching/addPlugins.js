/*
  Copyright 2019 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
import { getOrCreatePrecacheController } from './utils/getOrCreatePrecacheController.js';
import './_version.js';
/**
 * Adds plugins to the precaching strategy.
 *
 * @param {Array<Object>} plugins
 *
 * @memberof workbox-precaching
 */
function addPlugins(plugins) {
    const precacheController = getOrCreatePrecacheController();
    precacheController.strategy.plugins.push(...plugins);
}
export { addPlugins };

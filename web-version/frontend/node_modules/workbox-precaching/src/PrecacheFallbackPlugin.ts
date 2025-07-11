/*
  Copyright 2020 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {WorkboxPlugin} from 'workbox-core/types.js';

import {getOrCreatePrecacheController} from './utils/getOrCreatePrecacheController.js';
import {PrecacheController} from './PrecacheController.js';

import './_version.js';

/**
 * `PrecacheFallbackPlugin` allows you to specify an "offline fallback"
 * response to be used when a given strategy is unable to generate a response.
 *
 * It does this by intercepting the `handlerDidError` plugin callback
 * and returning a precached response, taking the expected revision parameter
 * into account automatically.
 *
 * Unless you explicitly pass in a `PrecacheController` instance to the
 * constructor, the default instance will be used. Generally speaking, most
 * developers will end up using the default.
 *
 * @memberof workbox-precaching
 */
class PrecacheFallbackPlugin implements WorkboxPlugin {
  private readonly _fallbackURL: string;
  private readonly _precacheController: PrecacheController;

  /**
   * Constructs a new PrecacheFallbackPlugin with the associated fallbackURL.
   *
   * @param {Object} config
   * @param {string} config.fallbackURL A precached URL to use as the fallback
   *     if the associated strategy can't generate a response.
   * @param {PrecacheController} [config.precacheController] An optional
   *     PrecacheController instance. If not provided, the default
   *     PrecacheController will be used.
   */
  constructor({
    fallbackURL,
    precacheController,
  }: {
    fallbackURL: string;
    precacheController?: PrecacheController;
  }) {
    this._fallbackURL = fallbackURL;
    this._precacheController =
      precacheController || getOrCreatePrecacheController();
  }

  /**
   * @return {Promise<Response>} The precache response for the fallback URL.
   *
   * @private
   */
  handlerDidError: WorkboxPlugin['handlerDidError'] = () =>
    this._precacheController.matchPrecache(this._fallbackURL);
}

export {PrecacheFallbackPlugin};

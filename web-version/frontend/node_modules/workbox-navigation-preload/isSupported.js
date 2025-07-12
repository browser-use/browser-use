/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
import './_version.js';
/**
 * @return {boolean} Whether or not the current browser supports enabling
 * navigation preload.
 *
 * @memberof workbox-navigation-preload
 */
function isSupported() {
    return Boolean(self.registration && self.registration.navigationPreload);
}
export { isSupported };

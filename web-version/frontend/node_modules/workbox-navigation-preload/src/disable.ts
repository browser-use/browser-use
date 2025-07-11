/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {logger} from 'workbox-core/_private/logger.js';
import {isSupported} from './isSupported.js';
import './_version.js';

// Give TypeScript the correct global.
declare let self: ServiceWorkerGlobalScope;

/**
 * If the browser supports Navigation Preload, then this will disable it.
 *
 * @memberof workbox-navigation-preload
 */
function disable(): void {
  if (isSupported()) {
    self.addEventListener('activate', (event: ExtendableEvent) => {
      event.waitUntil(
        self.registration.navigationPreload.disable().then(() => {
          if (process.env.NODE_ENV !== 'production') {
            logger.log(`Navigation preload is disabled.`);
          }
        }),
      );
    });
  } else {
    if (process.env.NODE_ENV !== 'production') {
      logger.log(`Navigation preload is not supported in this browser.`);
    }
  }
}

export {disable};

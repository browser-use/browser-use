/*
  Copyright 2019 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
import { cacheNames } from 'workbox-core/_private/cacheNames.js';
import { logger } from 'workbox-core/_private/logger.js';
import { deleteOutdatedCaches } from './utils/deleteOutdatedCaches.js';
import './_version.js';
/**
 * Adds an `activate` event listener which will clean up incompatible
 * precaches that were created by older versions of Workbox.
 *
 * @memberof workbox-precaching
 */
function cleanupOutdatedCaches() {
    // See https://github.com/Microsoft/TypeScript/issues/28357#issuecomment-436484705
    self.addEventListener('activate', ((event) => {
        const cacheName = cacheNames.getPrecacheName();
        event.waitUntil(deleteOutdatedCaches(cacheName).then((cachesDeleted) => {
            if (process.env.NODE_ENV !== 'production') {
                if (cachesDeleted.length > 0) {
                    logger.log(`The following out-of-date precaches were cleaned up ` +
                        `automatically:`, cachesDeleted);
                }
            }
        }));
    }));
}
export { cleanupOutdatedCaches };

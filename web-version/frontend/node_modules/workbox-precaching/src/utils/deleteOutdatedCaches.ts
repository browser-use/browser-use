/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import '../_version.js';

// Give TypeScript the correct global.
declare let self: ServiceWorkerGlobalScope;

const SUBSTRING_TO_FIND = '-precache-';

/**
 * Cleans up incompatible precaches that were created by older versions of
 * Workbox, by a service worker registered under the current scope.
 *
 * This is meant to be called as part of the `activate` event.
 *
 * This should be safe to use as long as you don't include `substringToFind`
 * (defaulting to `-precache-`) in your non-precache cache names.
 *
 * @param {string} currentPrecacheName The cache name currently in use for
 * precaching. This cache won't be deleted.
 * @param {string} [substringToFind='-precache-'] Cache names which include this
 * substring will be deleted (excluding `currentPrecacheName`).
 * @return {Array<string>} A list of all the cache names that were deleted.
 *
 * @private
 * @memberof workbox-precaching
 */
const deleteOutdatedCaches = async (
  currentPrecacheName: string,
  substringToFind: string = SUBSTRING_TO_FIND,
): Promise<string[]> => {
  const cacheNames = await self.caches.keys();

  const cacheNamesToDelete = cacheNames.filter((cacheName) => {
    return (
      cacheName.includes(substringToFind) &&
      cacheName.includes(self.registration.scope) &&
      cacheName !== currentPrecacheName
    );
  });

  await Promise.all(
    cacheNamesToDelete.map((cacheName) => self.caches.delete(cacheName)),
  );

  return cacheNamesToDelete;
};

export {deleteOutdatedCaches};

/*
  Copyright 2019 Google LLC
  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {timeout} from './timeout.js';
import '../_version.js';

// Give TypeScript the correct global.
declare let self: ServiceWorkerGlobalScope;

const MAX_RETRY_TIME = 2000;

/**
 * Returns a promise that resolves to a window client matching the passed
 * `resultingClientId`. For browsers that don't support `resultingClientId`
 * or if waiting for the resulting client to apper takes too long, resolve to
 * `undefined`.
 *
 * @param {string} [resultingClientId]
 * @return {Promise<Client|undefined>}
 * @private
 */
export async function resultingClientExists(
  resultingClientId?: string,
): Promise<Client | undefined> {
  if (!resultingClientId) {
    return;
  }

  let existingWindows = await self.clients.matchAll({type: 'window'});
  const existingWindowIds = new Set(existingWindows.map((w) => w.id));

  let resultingWindow;
  const startTime = performance.now();

  // Only wait up to `MAX_RETRY_TIME` to find a matching client.
  while (performance.now() - startTime < MAX_RETRY_TIME) {
    existingWindows = await self.clients.matchAll({type: 'window'});

    resultingWindow = existingWindows.find((w) => {
      if (resultingClientId) {
        // If we have a `resultingClientId`, we can match on that.
        return w.id === resultingClientId;
      } else {
        // Otherwise match on finding a window not in `existingWindowIds`.
        return !existingWindowIds.has(w.id);
      }
    });

    if (resultingWindow) {
      break;
    }

    // Sleep for 100ms and retry.
    await timeout(100);
  }

  return resultingWindow;
}

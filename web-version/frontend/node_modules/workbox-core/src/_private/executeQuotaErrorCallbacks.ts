/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {logger} from '../_private/logger.js';
import {quotaErrorCallbacks} from '../models/quotaErrorCallbacks.js';
import '../_version.js';

/**
 * Runs all of the callback functions, one at a time sequentially, in the order
 * in which they were registered.
 *
 * @memberof workbox-core
 * @private
 */
async function executeQuotaErrorCallbacks(): Promise<void> {
  if (process.env.NODE_ENV !== 'production') {
    logger.log(
      `About to run ${quotaErrorCallbacks.size} ` +
        `callbacks to clean up caches.`,
    );
  }

  for (const callback of quotaErrorCallbacks) {
    await callback();
    if (process.env.NODE_ENV !== 'production') {
      logger.log(callback, 'is complete.');
    }
  }

  if (process.env.NODE_ENV !== 'production') {
    logger.log('Finished running callbacks.');
  }
}

export {executeQuotaErrorCallbacks};

/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {logger} from 'workbox-core/_private/logger.js';
import '../_version.js';

/**
 * @param {string} groupTitle
 * @param {Array<string>} deletedURLs
 *
 * @private
 */
const logGroup = (groupTitle: string, deletedURLs: string[]) => {
  logger.groupCollapsed(groupTitle);

  for (const url of deletedURLs) {
    logger.log(url);
  }

  logger.groupEnd();
};

/**
 * @param {Array<string>} deletedURLs
 *
 * @private
 * @memberof workbox-precaching
 */
export function printCleanupDetails(deletedURLs: string[]): void {
  const deletionCount = deletedURLs.length;
  if (deletionCount > 0) {
    logger.groupCollapsed(
      `During precaching cleanup, ` +
        `${deletionCount} cached ` +
        `request${deletionCount === 1 ? ' was' : 's were'} deleted.`,
    );
    logGroup('Deleted Cache Requests', deletedURLs);
    logger.groupEnd();
  }
}

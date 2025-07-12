/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {logger} from 'workbox-core/_private/logger.js';
import {getFriendlyURL} from 'workbox-core/_private/getFriendlyURL.js';
import '../_version.js';

export const messages = {
  strategyStart: (strategyName: string, request: Request): string =>
    `Using ${strategyName} to respond to '${getFriendlyURL(request.url)}'`,
  printFinalResponse: (response?: Response): void => {
    if (response) {
      logger.groupCollapsed(`View the final response here.`);
      logger.log(response || '[No response returned]');
      logger.groupEnd();
    }
  },
};

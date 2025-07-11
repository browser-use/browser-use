/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {WorkboxSW} from './controllers/WorkboxSW.mjs';
import './_version.mjs';

/**
 * @namespace workbox
 */

// Don't export anything, just expose a global.
self.workbox = new WorkboxSW();

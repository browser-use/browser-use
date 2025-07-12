/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {concatenate} from './concatenate.js';
import {concatenateToResponse} from './concatenateToResponse.js';
import {isSupported} from './isSupported.js';
import {strategy, StreamsHandlerCallback} from './strategy.js';

import './_version.js';

/**
 * @module workbox-streams
 */

export {
  concatenate,
  concatenateToResponse,
  isSupported,
  strategy,
  StreamsHandlerCallback,
};

export * from './_types.js';

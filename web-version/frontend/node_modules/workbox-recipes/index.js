/*
  Copyright 2020 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
import { googleFontsCache } from './googleFontsCache';
import { imageCache } from './imageCache';
import { staticResourceCache, } from './staticResourceCache';
import { pageCache } from './pageCache';
import { offlineFallback } from './offlineFallback';
import { warmStrategyCache } from './warmStrategyCache';
import './_version.js';
/**
 * @module workbox-recipes
 */
export { googleFontsCache, imageCache, offlineFallback, pageCache, staticResourceCache, warmStrategyCache, };

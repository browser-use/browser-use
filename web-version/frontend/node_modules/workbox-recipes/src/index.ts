/*
  Copyright 2020 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {googleFontsCache, GoogleFontCacheOptions} from './googleFontsCache';
import {imageCache, ImageCacheOptions} from './imageCache';
import {
  staticResourceCache,
  StaticResourceOptions,
} from './staticResourceCache';
import {pageCache, PageCacheOptions} from './pageCache';
import {offlineFallback, OfflineFallbackOptions} from './offlineFallback';
import {warmStrategyCache, WarmStrategyCacheOptions} from './warmStrategyCache';

import './_version.js';

/**
 * @module workbox-recipes
 */

export {
  GoogleFontCacheOptions,
  googleFontsCache,
  imageCache,
  ImageCacheOptions,
  offlineFallback,
  OfflineFallbackOptions,
  pageCache,
  PageCacheOptions,
  staticResourceCache,
  StaticResourceOptions,
  warmStrategyCache,
  WarmStrategyCacheOptions,
};

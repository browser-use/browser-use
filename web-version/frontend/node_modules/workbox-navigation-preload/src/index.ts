/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {disable} from './disable.js';
import {enable} from './enable.js';
import {isSupported} from './isSupported.js';
import './_version.js';

// See https://github.com/GoogleChrome/workbox/issues/2946
interface NavigationPreloadState {
  enabled?: boolean;
  headerValue?: string;
}

interface NavigationPreloadManager {
  disable(): Promise<void>;
  enable(): Promise<void>;
  getState(): Promise<NavigationPreloadState>;
  setHeaderValue(value: string): Promise<void>;
}

declare global {
  interface ServiceWorkerRegistration {
    readonly navigationPreload: NavigationPreloadManager;
  }
}

/**
 * @module workbox-navigation-preload
 */

export {disable, enable, isSupported};

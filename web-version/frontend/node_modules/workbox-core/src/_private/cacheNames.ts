/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import '../_version.js';

declare let registration: ServiceWorkerRegistration | undefined;

export interface CacheNameDetails {
  googleAnalytics: string;
  precache: string;
  prefix: string;
  runtime: string;
  suffix: string;
}

export interface PartialCacheNameDetails {
  [propName: string]: string;
}

export type CacheNameDetailsProp =
  | 'googleAnalytics'
  | 'precache'
  | 'prefix'
  | 'runtime'
  | 'suffix';

const _cacheNameDetails: CacheNameDetails = {
  googleAnalytics: 'googleAnalytics',
  precache: 'precache-v2',
  prefix: 'workbox',
  runtime: 'runtime',
  suffix: typeof registration !== 'undefined' ? registration.scope : '',
};

const _createCacheName = (cacheName: string): string => {
  return [_cacheNameDetails.prefix, cacheName, _cacheNameDetails.suffix]
    .filter((value) => value && value.length > 0)
    .join('-');
};

const eachCacheNameDetail = (fn: (key: CacheNameDetailsProp) => void): void => {
  for (const key of Object.keys(_cacheNameDetails)) {
    fn(key as CacheNameDetailsProp);
  }
};

export const cacheNames = {
  updateDetails: (details: PartialCacheNameDetails): void => {
    eachCacheNameDetail((key: CacheNameDetailsProp): void => {
      if (typeof details[key] === 'string') {
        _cacheNameDetails[key] = details[key];
      }
    });
  },
  getGoogleAnalyticsName: (userCacheName?: string): string => {
    return userCacheName || _createCacheName(_cacheNameDetails.googleAnalytics);
  },
  getPrecacheName: (userCacheName?: string): string => {
    return userCacheName || _createCacheName(_cacheNameDetails.precache);
  },
  getPrefix: (): string => {
    return _cacheNameDetails.prefix;
  },
  getRuntimeName: (userCacheName?: string): string => {
    return userCacheName || _createCacheName(_cacheNameDetails.runtime);
  },
  getSuffix: (): string => {
    return _cacheNameDetails.suffix;
  },
};

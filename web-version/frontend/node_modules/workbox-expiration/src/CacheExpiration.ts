/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/

import {assert} from 'workbox-core/_private/assert.js';
import {dontWaitFor} from 'workbox-core/_private/dontWaitFor.js';
import {logger} from 'workbox-core/_private/logger.js';
import {WorkboxError} from 'workbox-core/_private/WorkboxError.js';

import {CacheTimestampsModel} from './models/CacheTimestampsModel.js';

import './_version.js';

interface CacheExpirationConfig {
  maxEntries?: number;
  maxAgeSeconds?: number;
  matchOptions?: CacheQueryOptions;
}

/**
 * The `CacheExpiration` class allows you define an expiration and / or
 * limit on the number of responses stored in a
 * [`Cache`](https://developer.mozilla.org/en-US/docs/Web/API/Cache).
 *
 * @memberof workbox-expiration
 */
class CacheExpiration {
  private _isRunning = false;
  private _rerunRequested = false;
  private readonly _maxEntries?: number;
  private readonly _maxAgeSeconds?: number;
  private readonly _matchOptions?: CacheQueryOptions;
  private readonly _cacheName: string;
  private readonly _timestampModel: CacheTimestampsModel;

  /**
   * To construct a new CacheExpiration instance you must provide at least
   * one of the `config` properties.
   *
   * @param {string} cacheName Name of the cache to apply restrictions to.
   * @param {Object} config
   * @param {number} [config.maxEntries] The maximum number of entries to cache.
   * Entries used the least will be removed as the maximum is reached.
   * @param {number} [config.maxAgeSeconds] The maximum age of an entry before
   * it's treated as stale and removed.
   * @param {Object} [config.matchOptions] The [`CacheQueryOptions`](https://developer.mozilla.org/en-US/docs/Web/API/Cache/delete#Parameters)
   * that will be used when calling `delete()` on the cache.
   */
  constructor(cacheName: string, config: CacheExpirationConfig = {}) {
    if (process.env.NODE_ENV !== 'production') {
      assert!.isType(cacheName, 'string', {
        moduleName: 'workbox-expiration',
        className: 'CacheExpiration',
        funcName: 'constructor',
        paramName: 'cacheName',
      });

      if (!(config.maxEntries || config.maxAgeSeconds)) {
        throw new WorkboxError('max-entries-or-age-required', {
          moduleName: 'workbox-expiration',
          className: 'CacheExpiration',
          funcName: 'constructor',
        });
      }

      if (config.maxEntries) {
        assert!.isType(config.maxEntries, 'number', {
          moduleName: 'workbox-expiration',
          className: 'CacheExpiration',
          funcName: 'constructor',
          paramName: 'config.maxEntries',
        });
      }

      if (config.maxAgeSeconds) {
        assert!.isType(config.maxAgeSeconds, 'number', {
          moduleName: 'workbox-expiration',
          className: 'CacheExpiration',
          funcName: 'constructor',
          paramName: 'config.maxAgeSeconds',
        });
      }
    }

    this._maxEntries = config.maxEntries;
    this._maxAgeSeconds = config.maxAgeSeconds;
    this._matchOptions = config.matchOptions;
    this._cacheName = cacheName;
    this._timestampModel = new CacheTimestampsModel(cacheName);
  }

  /**
   * Expires entries for the given cache and given criteria.
   */
  async expireEntries(): Promise<void> {
    if (this._isRunning) {
      this._rerunRequested = true;
      return;
    }
    this._isRunning = true;

    const minTimestamp = this._maxAgeSeconds
      ? Date.now() - this._maxAgeSeconds * 1000
      : 0;

    const urlsExpired = await this._timestampModel.expireEntries(
      minTimestamp,
      this._maxEntries,
    );

    // Delete URLs from the cache
    const cache = await self.caches.open(this._cacheName);
    for (const url of urlsExpired) {
      await cache.delete(url, this._matchOptions);
    }

    if (process.env.NODE_ENV !== 'production') {
      if (urlsExpired.length > 0) {
        logger.groupCollapsed(
          `Expired ${urlsExpired.length} ` +
            `${urlsExpired.length === 1 ? 'entry' : 'entries'} and removed ` +
            `${urlsExpired.length === 1 ? 'it' : 'them'} from the ` +
            `'${this._cacheName}' cache.`,
        );
        logger.log(
          `Expired the following ${urlsExpired.length === 1 ? 'URL' : 'URLs'}:`,
        );
        urlsExpired.forEach((url) => logger.log(`    ${url}`));
        logger.groupEnd();
      } else {
        logger.debug(`Cache expiration ran and found no entries to remove.`);
      }
    }

    this._isRunning = false;
    if (this._rerunRequested) {
      this._rerunRequested = false;
      dontWaitFor(this.expireEntries());
    }
  }

  /**
   * Update the timestamp for the given URL. This ensures the when
   * removing entries based on maximum entries, most recently used
   * is accurate or when expiring, the timestamp is up-to-date.
   *
   * @param {string} url
   */
  async updateTimestamp(url: string): Promise<void> {
    if (process.env.NODE_ENV !== 'production') {
      assert!.isType(url, 'string', {
        moduleName: 'workbox-expiration',
        className: 'CacheExpiration',
        funcName: 'updateTimestamp',
        paramName: 'url',
      });
    }

    await this._timestampModel.setTimestamp(url, Date.now());
  }

  /**
   * Can be used to check if a URL has expired or not before it's used.
   *
   * This requires a look up from IndexedDB, so can be slow.
   *
   * Note: This method will not remove the cached entry, call
   * `expireEntries()` to remove indexedDB and Cache entries.
   *
   * @param {string} url
   * @return {boolean}
   */
  async isURLExpired(url: string): Promise<boolean> {
    if (!this._maxAgeSeconds) {
      if (process.env.NODE_ENV !== 'production') {
        throw new WorkboxError(`expired-test-without-max-age`, {
          methodName: 'isURLExpired',
          paramName: 'maxAgeSeconds',
        });
      }
      return false;
    } else {
      const timestamp = await this._timestampModel.getTimestamp(url);
      const expireOlderThan = Date.now() - this._maxAgeSeconds * 1000;
      return timestamp !== undefined ? timestamp < expireOlderThan : true;
    }
  }

  /**
   * Removes the IndexedDB object store used to keep track of cache expiration
   * metadata.
   */
  async delete(): Promise<void> {
    // Make sure we don't attempt another rerun if we're called in the middle of
    // a cache expiration.
    this._rerunRequested = false;
    await this._timestampModel.expireEntries(Infinity); // Expires all.
  }
}

export {CacheExpiration};

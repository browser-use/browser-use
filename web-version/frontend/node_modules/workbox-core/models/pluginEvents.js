/*
  Copyright 2018 Google LLC

  Use of this source code is governed by an MIT-style
  license that can be found in the LICENSE file or at
  https://opensource.org/licenses/MIT.
*/
import '../_version.js';
export var pluginEvents;
(function (pluginEvents) {
    pluginEvents["CACHE_DID_UPDATE"] = "cacheDidUpdate";
    pluginEvents["CACHE_KEY_WILL_BE_USED"] = "cacheKeyWillBeUsed";
    pluginEvents["CACHE_WILL_UPDATE"] = "cacheWillUpdate";
    pluginEvents["CACHED_RESPONSE_WILL_BE_USED"] = "cachedResponseWillBeUsed";
    pluginEvents["FETCH_DID_FAIL"] = "fetchDidFail";
    pluginEvents["FETCH_DID_SUCCEED"] = "fetchDidSucceed";
    pluginEvents["REQUEST_WILL_FETCH"] = "requestWillFetch";
})(pluginEvents || (pluginEvents = {}));

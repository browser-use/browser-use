/*******************************************************************************

    uBlock Origin - a browser extension to block requests.
    Copyright (C) 2019-present Raymond Hill

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see {http://www.gnu.org/licenses/}.

    Home: https://github.com/gorhill/uBlock
*/

(function() {
    'use strict';
    if ( amznads ) {
        return;
    }
    var w = window;
    var noopfn = function() {
        ;
    }.bind();
    var amznads = {
        appendScriptTag: noopfn,
        appendTargetingToAdServerUrl: noopfn,
        appendTargetingToQueryString: noopfn,
        clearTargetingFromGPTAsync: noopfn,
        doAllTasks: noopfn,
        doGetAdsAsync: noopfn,
        doTask: noopfn,
        detectIframeAndGetURL: noopfn,
        getAds: noopfn,
        getAdsAsync: noopfn,
        getAdForSlot: noopfn,
        getAdsCallback: noopfn,
        getDisplayAds: noopfn,
        getDisplayAdsAsync: noopfn,
        getDisplayAdsCallback: noopfn,
        getKeys: noopfn,
        getReferrerURL: noopfn,
        getScriptSource: noopfn,
        getTargeting: noopfn,
        getTokens: noopfn,
        getValidMilliseconds: noopfn,
        getVideoAds: noopfn,
        getVideoAdsAsync: noopfn,
        getVideoAdsCallback: noopfn,
        handleCallBack: noopfn,
        hasAds: noopfn,
        renderAd: noopfn,
        saveAds: noopfn,
        setTargeting: noopfn,
        setTargetingForGPTAsync: noopfn,
        setTargetingForGPTSync: noopfn,
        tryGetAdsAsync: noopfn,
        updateAds: noopfn
    };
    w.amznads = amznads;
    w.amzn_ads = w.amzn_ads || noopfn;
    w.aax_write = w.aax_write || noopfn;
    w.aax_render_ad = w.aax_render_ad || noopfn;
})();

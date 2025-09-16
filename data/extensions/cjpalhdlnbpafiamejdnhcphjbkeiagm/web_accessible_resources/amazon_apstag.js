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

// https://www.reddit.com/r/uBlockOrigin/comments/ghjqph/
// https://github.com/NanoMeow/QuickReports/issues/3717
// https://www.reddit.com/r/uBlockOrigin/comments/qyx7en/

// https://searchfox.org/mozilla-central/source/browser/extensions/webcompat/shims/apstag.js
//   Import queue-related initialization code.

(function() {
    'use strict';
    const w = window;
    const noopfn = function() {
        ; // jshint ignore:line
    }.bind();
    const _Q = w.apstag && w.apstag._Q || [];
    const apstag = {
        _Q,
        fetchBids: function(a, b) {
            if ( typeof b === 'function' ) {
                b([]);
            }
        },
        init: noopfn,
        setDisplayBids: noopfn,
        targetingKeys: noopfn,
    };
    w.apstag = apstag;
    _Q.push = function(prefix, args) {
        try {
            switch (prefix) {
            case 'f':
                apstag.fetchBids(...args);
                break;
            }
        } catch (e) {
            console.trace(e);
        }
    };
    for ( const cmd of _Q ) {
        _Q.push(cmd);
    }
})();

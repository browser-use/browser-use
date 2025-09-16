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
    const noopfn = function() {
    };
    const w = window;
    w.ga = w.ga || noopfn;
    const dl = w.dataLayer;
    if ( dl instanceof Object === false ) { return; }
    if ( dl.hide instanceof Object && typeof dl.hide.end === 'function' ) {
        dl.hide.end();
    }
    if ( typeof dl.push === 'function' ) {
        dl.push = function(o) {
            if (
                o instanceof Object &&
                typeof o.eventCallback === 'function'
            ) {
                setTimeout(o.eventCallback, 1);
            }
        };
    }
})();

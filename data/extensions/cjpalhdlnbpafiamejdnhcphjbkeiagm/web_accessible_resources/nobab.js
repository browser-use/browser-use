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
    const signatures = [
        [ 'blockadblock' ],
        [ 'babasbm' ],
        [ /getItem\('babn'\)/ ],
        [
            'getElementById',
            'String.fromCharCode',
            'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789',
            'charAt',
            'DOMContentLoaded',
            'AdBlock',
            'addEventListener',
            'doScroll',
            'fromCharCode',
            '<<2|r>>4',
            'sessionStorage',
            'clientWidth',
            'localStorage',
            'Math',
            'random'
        ],
    ];
    const check = function(s) {
        for ( let i = 0; i < signatures.length; i++ ) {
            const tokens = signatures[i];
            let match = 0;
            for ( let j = 0; j < tokens.length; j++ ) {
                const token = tokens[j];
                const pos = token instanceof RegExp
                    ? s.search(token)
                    : s.indexOf(token);
                if ( pos !== -1 ) { match += 1; }
            }
            if ( (match / tokens.length) >= 0.8 ) { return true; }
        }
        return false;
    };
    window.eval = new Proxy(window.eval, {              // jshint ignore: line
        apply: function(target, thisArg, args) {
            const a = args[0];
            if ( typeof a !== 'string' || !check(a) ) {
                return target.apply(thisArg, args);
            }
            if ( document.body ) {
                document.body.style.removeProperty('visibility');
            }
            let el = document.getElementById('babasbmsgx');
            if ( el ) {
                el.parentNode.removeChild(el);
            }
        }
    });
    window.setTimeout = new Proxy(window.setTimeout, {
        apply: function(target, thisArg, args) {
            const a = args[0];
            if (
                typeof a !== 'string' ||
                /\.bab_elementid.$/.test(a) === false
            ) {
                return target.apply(thisArg, args);
            }
        }
    });
})();

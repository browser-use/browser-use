/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2014-present Raymond Hill

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

/******************************************************************************/

// Injected into specific webpages, those which have been pre-selected
// because they are known to contain:
// https://ublockorigin.github.io/uAssets/update-lists?listkeys=[...]

/******************************************************************************/

(( ) => {
// >>>>> start of local scope

/******************************************************************************/

if ( document instanceof HTMLDocument === false ) { return; }

// Maybe uBO has gone away meanwhile.
if ( typeof vAPI !== 'object' || vAPI === null ) { return; }

function updateStockLists(target) {
    if ( vAPI instanceof Object === false ) {
        document.removeEventListener('click', updateStockLists);
        return;
    }
    try {
        const updateURL = new URL(target.href);
        if ( updateURL.hostname !== 'ublockorigin.github.io') { return; }
        if ( updateURL.pathname !== '/uAssets/update-lists.html') { return; }
        const listkeys = updateURL.searchParams.get('listkeys') || '';
        if ( listkeys === '' ) { return; }
        let auto = true;
        const manual = updateURL.searchParams.get('manual');
        if ( manual === '1' ) {
            auto = false;
        } else if ( /^\d{6}$/.test(`${manual}`) ) {
            const year = parseInt(manual.slice(0,2)) || 0;
            const month = parseInt(manual.slice(2,4)) || 0;
            const day = parseInt(manual.slice(4,6)) || 0;
            if ( year !== 0 && month !== 0 && day !== 0 ) {
                const date = new Date();
                date.setUTCFullYear(2000 + year, month - 1, day);
                date.setUTCHours(0);
                const then = date.getTime() / 1000 / 3600;
                const now = Date.now() / 1000 / 3600;
                auto = then < (now - 48) || then > (now + 48);
            }
        }
        vAPI.messaging.send('scriptlets', {
            what: 'updateLists',
            listkeys,
            auto,
        });
        return true;
    } catch {
    }
}

// https://github.com/easylist/EasyListHebrew/issues/89
//   Ensure trusted events only.

document.addEventListener('click', ev => {
    if ( ev.button !== 0 || ev.isTrusted === false ) { return; }
    const target = ev.target.closest('a');
    if ( target instanceof HTMLAnchorElement === false ) { return; }
    if ( updateStockLists(target) === true ) {
        ev.stopPropagation();
        ev.preventDefault();
    }
});

/******************************************************************************/

// <<<<< end of local scope
})();








/*******************************************************************************

    DO NOT:
    - Remove the following code
    - Add code beyond the following code
    Reason:
    - https://github.com/gorhill/uBlock/pull/3721
    - uBO never uses the return value from injected content scripts

**/

void 0;

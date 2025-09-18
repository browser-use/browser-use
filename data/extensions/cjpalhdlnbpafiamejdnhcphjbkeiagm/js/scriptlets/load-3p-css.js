/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2020-present Raymond Hill

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

(( ) => {
    if ( typeof vAPI !== 'object' ) { return; }

    if ( vAPI.dynamicReloadToken === undefined ) {
        vAPI.dynamicReloadToken = vAPI.randomToken();
    }

    for ( const sheet of Array.from(document.styleSheets) ) {
        let loaded = false;
        try {
            loaded = sheet.rules.length !== 0;
        } catch {
        }
        if ( loaded ) { continue; }
        const link = sheet.ownerNode || null;
        if ( link === null || link.localName !== 'link' ) { continue; }
        if ( link.hasAttribute(vAPI.dynamicReloadToken) ) { continue; }
        const clone = link.cloneNode(true);
        clone.setAttribute(vAPI.dynamicReloadToken, '');
        link.replaceWith(clone);
    }
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

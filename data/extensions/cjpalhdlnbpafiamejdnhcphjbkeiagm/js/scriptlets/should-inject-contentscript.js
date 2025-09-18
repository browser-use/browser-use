/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2018-present Raymond Hill

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

// If content scripts are already injected, we need to respond with `false`,
// to "should inject content scripts?"
//
// https://github.com/uBlockOrigin/uBlock-issues/issues/403
//   If the content script was not bootstrapped, give it another try.

(( ) => {
    try {
        const status = vAPI.uBO !== true;
        if ( status === false && vAPI.bootstrap ) {
            self.requestIdleCallback(( ) => vAPI?.bootstrap?.());
        }
        return status;
    } catch {
    }
    return true;
})();

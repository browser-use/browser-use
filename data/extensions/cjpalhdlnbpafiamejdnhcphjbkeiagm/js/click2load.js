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
/******************************************************************************/

(( ) => {

/******************************************************************************/

if ( typeof vAPI !== 'object' ) { return; }

const url = new URL(self.location.href);
const actualURL = url.searchParams.get('url');
const frameURL = url.searchParams.get('aliasURL') || actualURL;
const frameURLElem = document.getElementById('frameURL');

frameURLElem.children[0].textContent = actualURL;

frameURLElem.children[1].href = frameURL;
frameURLElem.children[1].title = frameURL;

document.body.setAttribute('title', actualURL);

document.body.addEventListener('click', ev => {
    if ( ev.isTrusted === false ) { return; }
    if ( ev.target.closest('#frameURL') !== null ) { return; }
    vAPI.messaging.send('default', {
        what: 'clickToLoad',
        frameURL,
    }).then(ok => {
        if ( ok !== true ) { return; }
        self.location.replace(frameURL);
    });
});

/******************************************************************************/

})();

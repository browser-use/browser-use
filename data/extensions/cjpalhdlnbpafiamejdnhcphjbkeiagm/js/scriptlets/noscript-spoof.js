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

// Code below has been imported from uMatrix and modified to fit uBO:
// https://github.com/gorhill/uMatrix/blob/3f8794dd899a05e066c24066c6c0a2515d5c60d2/src/js/contentscript.js#L464-L531

/******************************************************************************/

// https://github.com/gorhill/uMatrix/issues/232
//   Force `display` property, Firefox is still affected by the issue.

(( ) => {
    const noscripts = document.querySelectorAll('noscript');
    if ( noscripts.length === 0 ) { return; }

    const reMetaContent = /^\s*(\d+)\s*;\s*url=(?:"([^"]+)"|'([^']+)'|(.+))/i;
    const reSafeURL = /^https?:\/\//;
    const reNoscript = /(^|[ >+~])noscript([ >+~]|$)/g;
    const className = vAPI.sessionId;
    let redirectTimer;

    const autoRefresh = function(root) {
        const meta = root.querySelector('meta[http-equiv="refresh"][content]');
        if ( meta === null ) { return; }
        const match = reMetaContent.exec(meta.getAttribute('content'));
        if ( match === null ) { return; }
        const refreshURL = (match[2] || match[3] || match[4] || '').trim();
        let url;
        try {
            url = new URL(refreshURL, document.baseURI);
        } catch {
            return;
        }
        if ( reSafeURL.test(url.href) === false ) { return; }
        redirectTimer = setTimeout(( ) => {
            location.assign(url.href);
        }, parseInt(match[1], 10) * 1000 + 1);
        meta.parentNode.removeChild(meta);
    };

    const morphNoscript = function(from) {
        const fragment = new DocumentFragment();
        const inHead = from.closest('head');
        if ( /^application\/(?:xhtml\+)?xml/.test(document.contentType) ) {
            while ( from.firstChild !== null ) {
                fragment.append(from.firstChild);
            }
            return fragment;
        }
        const parser = new DOMParser();
        const doc = parser.parseFromString(
            `<span class="${className}" style="display: none; !important">${from.textContent}</span>`,
            'text/html'
        );
        for ( const elem of doc.querySelectorAll(inHead ? 'span > *' : 'span') ) {
            fragment.append(document.adoptNode(elem));
        }
        return fragment;
    };

    for ( const noscript of noscripts ) {
        const fragment = morphNoscript(noscript);
        if ( redirectTimer === undefined ) {
            autoRefresh(fragment);
        }
        noscript.replaceWith(fragment);
    }

    for ( const sheet of document.styleSheets ) {
        try {
            for ( const rule of sheet.cssRules ) {
                if ( reNoscript.test(rule.selectorText) === false ) { continue; }
                rule.selectorText =
                    rule.selectorText.replace(reNoscript, `$1span.${className}$2`);
            }
        } catch {
        }
    }

    for ( const span of document.querySelectorAll(`.${className}`) ) {
        span.style.setProperty('display', 'inline', 'important');
    }
})();

/******************************************************************************/

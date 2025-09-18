/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2023-present Raymond Hill

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

/* globals CodeMirror, uBlockDashboard, beautifier */

import { dom, qs$ } from './dom.js';
import { getActualTheme } from './theme.js';

/******************************************************************************/

const urlToDocMap = new Map();
const params = new URLSearchParams(document.location.search);
let currentURL = '';

const cmEditor = new CodeMirror(qs$('#content'), {
    autofocus: true,
    gutters: [ 'CodeMirror-linenumbers' ],
    lineNumbers: true,
    lineWrapping: true,
    maximizable: false,
    matchBrackets: true,
    styleActiveLine: {
        nonEmpty: true,
    },
});

uBlockDashboard.patchCodeMirrorEditor(cmEditor);

vAPI.messaging.send('dom', { what: 'uiStyles' }).then(response => {
    if ( typeof response !== 'object' || response === null ) { return; }
    if ( getActualTheme(response.uiTheme) === 'dark' ) {
        dom.cl.add('#content .cm-s-default', 'cm-s-night');
        dom.cl.remove('#content .cm-s-default', 'cm-s-default');
    }
});

// Convert resource URLs into clickable links to code viewer
cmEditor.addOverlay({
    re: /\b(?:href|src)=["']([^"']+)["']/g,
    match: null,
    token: function(stream) {
        if ( stream.sol() ) {
            this.re.lastIndex = 0;
            this.match = this.re.exec(stream.string);
        }
        if ( this.match === null ) {
            stream.skipToEnd();
            return null;
        }
        const end = this.re.lastIndex - 1;
        const beg = end - this.match[1].length;
        if ( stream.pos < beg ) {
            stream.pos = beg;
            return null;
        }
        if ( stream.pos < end ) {
            stream.pos = end;
            return 'href';
        }
        if ( stream.pos < this.re.lastIndex ) {
            stream.pos = this.re.lastIndex;
            this.match = this.re.exec(stream.string);
            return null;
        }
        stream.skipToEnd();
        return null;
    },
});

urlToDocMap.set('', cmEditor.getDoc());

/******************************************************************************/

async function fetchResource(url) {
    let response, text;
    const fetchOptions = {
        method: 'GET',
        referrer: '',
    };
    if ( urlToDocMap.has(url) ) {
        fetchOptions.cache = 'reload';
    }
    try {
        response = await fetch(url, fetchOptions);
        text = await response.text();
    } catch(reason) {
        text = String(reason);
    }
    let mime = response && response.headers.get('Content-Type') || '';
    mime = mime.replace(/\s*;.*$/, '').trim();
    const beautifierOptions = {
        end_with_newline: true,
        indent_size: 3,
        js: {
            max_preserve_newlines: 3,
        }
    };
    switch ( mime ) {
    case 'text/css':
        text = beautifier.css(text, beautifierOptions);
        break;
    case 'text/html':
    case 'application/xhtml+xml':
    case 'application/xml':
    case 'image/svg+xml':
        text = beautifier.html(text, beautifierOptions);
        break;
    case 'text/javascript':
    case 'application/javascript':
    case 'application/x-javascript':
        text = beautifier.js(text, beautifierOptions);
        break;
    case 'application/json':
        text = beautifier.js(text, beautifierOptions);
        break;
    default:
        break;
    }
    return { mime, text };
}

/******************************************************************************/

function addPastURLs(url) {
    const list = qs$('#pastURLs');
    let current;
    for ( let i = 0; i < list.children.length; i++ ) {
        const span = list.children[i];
        dom.cl.remove(span, 'selected');
        if ( span.textContent !== url ) { continue; }
        current = span;
    }
    if ( url === '' ) { return; }
    if ( current === undefined ) {
        current = document.createElement('span');
        current.textContent = url;
        list.prepend(current);
    }
    dom.cl.add(current, 'selected');
}

/******************************************************************************/

function setInputURL(url) {
    const input = qs$('#header input[type="url"]');
    if ( url === input.value ) { return; }
    dom.attr(input, 'value', url);
    input.value = url;
}

/******************************************************************************/

async function setURL(resourceURL) {
    // For convenience, remove potentially existing quotes around the URL
    if ( /^(["']).+\1$/.test(resourceURL) ) {
        resourceURL = resourceURL.slice(1, -1);
    }
    let afterURL;
    if ( resourceURL !== '' ) {
        try {
            const url = new URL(resourceURL, currentURL || undefined);
            url.hash = '';
            afterURL = url.href;
        } catch {
        }
        if ( afterURL === undefined ) { return; }
    } else {
        afterURL = '';
    }
    if ( afterURL !== '' && /^https?:\/\/./.test(afterURL) === false ) {
        return;
    }
    if ( afterURL === currentURL ) {
        if ( afterURL !== resourceURL ) {
            setInputURL(afterURL);
        }
        return;
    }
    let afterDoc = urlToDocMap.get(afterURL);
    if ( afterDoc === undefined ) {
        const r = await fetchResource(afterURL) || { mime: '', text: '' };
        afterDoc = new CodeMirror.Doc(r.text, r.mime || '');
        urlToDocMap.set(afterURL, afterDoc);
    }
    swapDoc(afterDoc);
    currentURL = afterURL;
    setInputURL(afterURL);
    const a = qs$('.cm-search-widget .sourceURL');
    dom.attr(a, 'href', afterURL);
    dom.attr(a, 'title', afterURL);
    addPastURLs(afterURL);
    // For unknown reasons, calling focus() synchronously does not work...
    vAPI.defer.once(1).then(( ) => { cmEditor.focus(); });
}

/******************************************************************************/

function removeURL(url) {
    if ( url === '' ) { return; }
    const list = qs$('#pastURLs');
    let foundAt = -1;
    for ( let i = 0; i < list.children.length; i++ ) {
        const span = list.children[i];
        if ( span.textContent !== url ) { continue; }
        foundAt = i;
    }
    if ( foundAt === -1 ) { return; }
    list.children[foundAt].remove();
    if ( foundAt >= list.children.length ) {
        foundAt = list.children.length - 1;
    }
    const afterURL = foundAt !== -1
        ? list.children[foundAt].textContent
        : '';
    setURL(afterURL);
    urlToDocMap.delete(url);
}

/******************************************************************************/

function swapDoc(doc) {
    const r = cmEditor.swapDoc(doc);
    if ( self.searchThread ) {
        self.searchThread.setHaystack(cmEditor.getValue());
    }
    const input = qs$('.cm-search-widget-input input[type="search"]');
    if ( input.value !== '' ) {
        qs$('.cm-search-widget').dispatchEvent(new Event('input'));
    }
    return r;
}

/******************************************************************************/

async function start() {
    await setURL(params.get('url'));

    dom.on('#header input[type="url"]', 'change', ev => {
        setURL(ev.target.value);
    });

    dom.on('#reloadURL', 'click', ( ) => {
        const input = qs$('#header input[type="url"]');
        const url = input.value;
        const beforeDoc = swapDoc(new CodeMirror.Doc('', ''));
        fetchResource(url).then(r => {
            if ( urlToDocMap.has(url) === false ) { return; }
            const afterDoc = r !== undefined
                ? new CodeMirror.Doc(r.text, r.mime || '')
                : beforeDoc;
            urlToDocMap.set(url, afterDoc);
            if ( currentURL !== url ) { return; }
            swapDoc(afterDoc);
        });
    });

    dom.on('#removeURL', 'click', ( ) => {
        removeURL(qs$('#header input[type="url"]').value);
    });

    dom.on('#pastURLs', 'mousedown', 'span', ev => {
        setURL(ev.target.textContent);
    });

    dom.on('#content', 'click', '.cm-href', ev => {
        const target = ev.target;
        const urlParts = [ target.textContent ];
        let previous = target;
        for (;;) {
            previous = previous.previousSibling;
            if ( previous === null ) { break; }
            if ( previous.nodeType !== 1 ) { break; }
            if ( previous.classList.contains('cm-href') === false ) { break; }
            urlParts.unshift(previous.textContent);
        }
        let next = target;
        for (;;) {
            next = next.nextSibling;
            if ( next === null ) { break; }
            if ( next.nodeType !== 1 ) { break; }
            if ( next.classList.contains('cm-href') === false ) { break; }
            urlParts.push(next.textContent);
        }
        setURL(urlParts.join(''));
    });
}

start();

/******************************************************************************/

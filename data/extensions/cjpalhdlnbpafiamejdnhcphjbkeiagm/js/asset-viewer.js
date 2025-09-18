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

/* global CodeMirror, uBlockDashboard */

import './codemirror/ubo-static-filtering.js';
import { dom, qs$ } from './dom.js';

/******************************************************************************/

(async ( ) => {
    const subscribeURL = new URL(document.location);
    const subscribeParams = subscribeURL.searchParams;
    const assetKey = subscribeParams.get('url');
    if ( assetKey === null ) { return; }

    const subscribeElem = subscribeParams.get('subscribe') !== null
        ? qs$('#subscribe')
        : null;
    if ( subscribeElem !== null && subscribeURL.hash !== '#subscribed' ) {
        const title = subscribeParams.get('title');
        const promptElem = qs$('#subscribePrompt');
        dom.text(promptElem.children[0], title);
        const a = promptElem.children[1];
        dom.text(a, assetKey);
        dom.attr(a, 'href', assetKey);
        dom.cl.remove(subscribeElem, 'hide');
    }

    const cmEditor = new CodeMirror(qs$('#content'), {
        autofocus: true,
        foldGutter: true,
        gutters: [
            'CodeMirror-linenumbers',
            { className: 'CodeMirror-lintgutter', style: 'width: 11px' },
        ],
        lineNumbers: true,
        lineWrapping: true,
        matchBrackets: true,
        maxScanLines: 1,
        maximizable: false,
        readOnly: true,
        styleActiveLine: {
            nonEmpty: true,
        },
    });

    uBlockDashboard.patchCodeMirrorEditor(cmEditor);

    vAPI.messaging.send('dashboard', {
        what: 'getAutoCompleteDetails'
    }).then(hints => {
        if ( hints instanceof Object === false ) { return; }
        cmEditor.setOption('uboHints', hints);
    });

    vAPI.messaging.send('dashboard', {
        what: 'getTrustedScriptletTokens',
    }).then(tokens => {
        cmEditor.setOption('trustedScriptletTokens', tokens);
    });

    const details = await vAPI.messaging.send('default', {
        what : 'getAssetContent',
        url: assetKey,
    });
    cmEditor.setOption('trustedSource', details.trustedSource === true);
    cmEditor.setValue(details && details.content || '');

    if ( subscribeElem !== null ) {
        dom.on('#subscribeButton', 'click', ( ) => {
            dom.cl.add(subscribeElem, 'hide');
            vAPI.messaging.send('scriptlets', {
                what: 'applyFilterListSelection',
                toImport: assetKey,
            }).then(( ) => {
                vAPI.messaging.send('scriptlets', {
                    what: 'reloadAllFilters'
                });
            });
        }, { once: true });
    }

    if ( details.sourceURL ) {
        const a = qs$('.cm-search-widget .sourceURL');
        dom.attr(a, 'href', details.sourceURL);
        dom.attr(a, 'title', details.sourceURL);
    }

    dom.cl.remove(dom.body, 'loading');
})();

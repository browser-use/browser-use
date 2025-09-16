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
// >>>>> start of local scope

/******************************************************************************/

// Worker context

if (
    self.WorkerGlobalScope instanceof Object &&
    self instanceof self.WorkerGlobalScope
) {
    let content = '';

    const doSearch = function(details) {
        const reEOLs = /\n\r|\r\n|\n|\r/g;
        const t1 = Date.now() + 750;

        let reSearch;
        try {
            reSearch = new RegExp(details.pattern, details.flags);
        } catch {
            return;
        }

        const response = [];
        const maxOffset = content.length;
        let iLine = 0;
        let iOffset = 0;
        let size = 0;
        while ( iOffset < maxOffset ) {
            // Find next match
            const match = reSearch.exec(content);
            if ( match === null ) { break; }
            // Find number of line breaks between last and current match.
            reEOLs.lastIndex = 0;
            const eols = content.slice(iOffset, match.index).match(reEOLs);
            if ( Array.isArray(eols) ) {
                iLine += eols.length;
            }
            // Store line
            response.push(iLine);
            size += 1;
            // Find next line break.
            reEOLs.lastIndex = reSearch.lastIndex;
            const eol = reEOLs.exec(content);
            iOffset = eol !== null
                ? reEOLs.lastIndex
                : content.length;
            reSearch.lastIndex = iOffset;
            iLine += 1;
            // Quit if this takes too long
            if ( (size & 0x3FF) === 0 && Date.now() >= t1 ) { break; }
        }

        return response;
    };

    self.onmessage = function(e) {
        const msg = e.data;

        switch ( msg.what ) {
        case 'setHaystack':
            content = msg.content;
            break;

        case 'doSearch': {
            const response = doSearch(msg);
            self.postMessage({ id: msg.id, response });
            break;
        }
        default:
            break;
        }
    };

    return;
}

/******************************************************************************/

// Main context

{
    const workerTTL = { min: 5 };
    const pendingResponses = new Map();
    const workerTTLTimer = vAPI.defer.create(( ) => {
        shutdown();
    });

    let worker;
    let messageId = 1;

    const onWorkerMessage = function(e) {
        const msg = e.data;
        const resolver = pendingResponses.get(msg.id);
        if ( resolver === undefined ) { return; }
        pendingResponses.delete(msg.id);
        resolver(msg.response);
    };

    const cancelPendingTasks = function() {
        for ( const resolver of pendingResponses.values() ) {
            resolver();
        }
        pendingResponses.clear();
    };

    const destroy = function() {
        shutdown();
        self.searchThread = undefined;
    };

    const shutdown = function() {
        if ( worker === undefined ) { return; }
        workerTTLTimer.off();
        worker.terminate();
        worker.onmessage = undefined;
        worker = undefined;
        cancelPendingTasks();
    };

    const init = function() {
        if ( self.searchThread instanceof Object === false ) { return; }
        if ( worker === undefined ) {
            worker = new Worker('js/codemirror/search-thread.js');
            worker.onmessage = onWorkerMessage;
        }
        workerTTLTimer.offon(workerTTL);
    };

    const needHaystack = function() {
        return worker instanceof Object === false;
    };

    const setHaystack = function(content) {
        init();
        worker.postMessage({ what: 'setHaystack', content });
    };

    const search = function(query, overwrite = true) {
        init();
        if ( worker instanceof Object === false ) {
            return Promise.resolve();
        }
        if ( overwrite ) {
            cancelPendingTasks();
        }
        const id = messageId++;
        worker.postMessage({
            what: 'doSearch',
            id,
            pattern: query.source,
            flags: query.flags,
            isRE: query instanceof RegExp
        });
        return new Promise(resolve => {
            pendingResponses.set(id, resolve);
        });
    };

    self.addEventListener(
        'beforeunload',
        ( ) => { destroy(); },
        { once: true }
    );

    self.searchThread = { needHaystack, setHaystack, search, shutdown };
}

/******************************************************************************/

// <<<<< end of local scope
})();

/******************************************************************************/

void 0;

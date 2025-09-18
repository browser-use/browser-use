/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2015-present Raymond Hill

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

import * as sfp from './static-filtering-parser.js';
import {
    domainFromHostname,
    hostnameFromURI,
} from './uri-utils.js';
import { CompiledListWriter } from './static-filtering-io.js';
import { i18n$ } from './i18n.js';
import staticNetFilteringEngine from './static-net-filtering.js';
import µb from './background.js';

/******************************************************************************/

const pendingResponses = new Map();

let worker = null;
let needLists = true;
let messageId = 1;

const onWorkerMessage = function(e) {
    const msg = e.data;
    const resolver = pendingResponses.get(msg.id);
    pendingResponses.delete(msg.id);
    resolver(msg.response);
};

const stopWorker = function() {
    workerTTLTimer.off();
    if ( worker === null ) { return; }
    worker.terminate();
    worker = null;
    needLists = true;
    for ( const resolver of pendingResponses.values() ) {
        resolver();
    }
    pendingResponses.clear();
};

const workerTTLTimer = vAPI.defer.create(stopWorker);
const workerTTL = { min: 1.5 };

const initWorker = function() {
    if ( worker === null ) {
        worker = new Worker('js/reverselookup-worker.js');
        worker.onmessage = onWorkerMessage;
    }

    // The worker will be shutdown after n minutes without being used.
    workerTTLTimer.offon(workerTTL);

    if ( needLists === false ) {
        return Promise.resolve();
    }
    needLists = false;

    const entries = new Map();

    const onListLoaded = function(details) {
        const entry = entries.get(details.assetKey);

        // https://github.com/gorhill/uBlock/issues/536
        // Use assetKey when there is no filter list title.

        worker.postMessage({
            what: 'setList',
            details: {
                assetKey: details.assetKey,
                title: entry.title || details.assetKey,
                supportURL: entry.supportURL,
                content: details.content
            }
        });
    };

    for ( const listKey in µb.availableFilterLists ) {
        if ( Object.hasOwn(µb.availableFilterLists, listKey) === false ) {
            continue;
        }
        const entry = µb.availableFilterLists[listKey];
        if ( entry.off === true ) { continue; }
        entries.set(listKey, {
            title: listKey !== µb.userFiltersPath ?
                entry.title :
                i18n$('1pPageName'),
            supportURL: entry.supportURL || ''
        });
    }
    if ( entries.size === 0 ) {
        return Promise.resolve();
    }

    const promises = [];
    for ( const listKey of entries.keys() ) {
        promises.push(
            µb.getCompiledFilterList(listKey).then(details => {
                onListLoaded(details);
            })
        );
    }
    return Promise.all(promises);
};

const fromNetFilter = async function(rawFilter) {
    if ( typeof rawFilter !== 'string' || rawFilter === '' ) { return; }

    const writer = new CompiledListWriter();
    const parser = new sfp.AstFilterParser({
        trustedSource: true,
        maxTokenLength: staticNetFilteringEngine.MAX_TOKEN_LENGTH,
        nativeCssHas: vAPI.webextFlavor.env.includes('native_css_has'),
    });
    parser.parse(rawFilter);

    const compiler = staticNetFilteringEngine.createCompiler();
    if ( compiler.compile(parser, writer) === false ) { return; }

    await initWorker();

    const id = messageId++;
    worker.postMessage({
        what: 'fromNetFilter',
        id,
        compiledFilter: writer.last(),
        rawFilter,
    });

    return new Promise(resolve => {
        pendingResponses.set(id, resolve);
    });
};

const fromExtendedFilter = async function(details) {
    if (
        typeof details.rawFilter !== 'string' ||
        details.rawFilter === ''
    ) {
        return;
    }

    await initWorker();

    const id = messageId++;
    const hostname = hostnameFromURI(details.url);

    const parser = new sfp.AstFilterParser({
        trustedSource: true,
        nativeCssHas: vAPI.webextFlavor.env.includes('native_css_has'),
    });
    parser.parse(details.rawFilter);
    let needle;
    if ( parser.isScriptletFilter() ) {
        needle = JSON.stringify(parser.getScriptletArgs());
    } else if ( parser.isResponseheaderFilter() ) {
        needle = parser.getResponseheaderName();
    }

    worker.postMessage({
        what: 'fromExtendedFilter',
        id,
        url: details.url,
        domain: domainFromHostname(hostname),
        ignoreGeneric:
            staticNetFilteringEngine.matchRequestReverse(
                'generichide',
                details.url
            ) === 2,
        ignoreSpecific:
            staticNetFilteringEngine.matchRequestReverse(
                'specifichide',
                details.url
            ) === 2,
        rawFilter: details.rawFilter,
        needle,
    });

    return new Promise(resolve => {
        pendingResponses.set(id, resolve);
    });
};

// This tells the worker that filter lists may have changed.

const resetLists = function() {
    needLists = true;
    if ( worker === null ) { return; }
    worker.postMessage({ what: 'resetLists' });
};

/******************************************************************************/

export const staticFilteringReverseLookup = {
    fromNetFilter,
    fromExtendedFilter,
    resetLists,
    shutdown: stopWorker
};

/******************************************************************************/

/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2017-present Raymond Hill

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

import { StaticExtFilteringHostnameDB } from './static-ext-filtering-db.js';
import { entityFromHostname } from './uri-utils.js';
import logger from './logger.js';
import { sessionFirewall } from './filtering-engines.js';
import µb from './background.js';

/******************************************************************************/

const pselectors = new Map();
const duplicates = new Set();

const filterDB = new StaticExtFilteringHostnameDB();

let acceptedCount = 0;
let discardedCount = 0;
let docRegister;

const htmlFilteringEngine = {
    get acceptedCount() {
        return acceptedCount;
    },
    get discardedCount() {
        return discardedCount;
    },
    getFilterCount() {
        return filterDB.size;
    },
};

const regexFromString = (s, exact = false) => {
    if ( s === '' ) { return /^/; }
    const match = /^\/(.+)\/([i]?)$/.exec(s);
    if ( match !== null ) {
        return new RegExp(match[1], match[2] || undefined);
    }
    const reStr = s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return new RegExp(exact ? `^${reStr}$` : reStr, 'i');
};

class PSelectorVoidTask {
    constructor(task) {
        console.info(`[uBO] HTML filtering: :${task[0]}() operator is not supported`);
    }
    transpose() {
    }
}
class PSelectorHasTextTask {
    constructor(task) {
        this.needle = regexFromString(task[1]);
    }
    transpose(node, output) {
        if ( this.needle.test(node.textContent) ) {
            output.push(node);
        }
    }
}

const PSelectorIfTask = class {
    constructor(task) {
        this.pselector = new PSelector(task[1]);
    }
    transpose(node, output) {
        if ( this.pselector.test(node) === this.target ) {
            output.push(node);
        }
    }
};
PSelectorIfTask.prototype.target = true;

class PSelectorIfNotTask extends PSelectorIfTask {
}
PSelectorIfNotTask.prototype.target = false;

class PSelectorMinTextLengthTask {
    constructor(task) {
        this.min = task[1];
    }
    transpose(node, output) {
        if ( node.textContent.length >= this.min ) {
            output.push(node);
        }
    }
}

class PSelectorSpathTask {
    constructor(task) {
        this.spath = task[1];
        this.nth = /^(?:\s*[+~]|:)/.test(this.spath);
        if ( this.nth ) { return; }
        if ( /^\s*>/.test(this.spath) ) {
            this.spath = `:scope ${this.spath.trim()}`;
        }
    }
    transpose(node, output) {
        const nodes = this.nth
            ? PSelectorSpathTask.qsa(node, this.spath)
            : node.querySelectorAll(this.spath);
        for ( const node of nodes ) {
            output.push(node);
        }
    }
    // Helper method for other operators.
    static qsa(node, selector) {
        const parent = node.parentElement;
        if ( parent === null ) { return []; }
        let pos = 1;
        for (;;) {
            node = node.previousElementSibling;
            if ( node === null ) { break; }
            pos += 1;
        }
        return parent.querySelectorAll(
            `:scope > :nth-child(${pos})${selector}`
        );
    }
}

class PSelectorUpwardTask {
    constructor(task) {
        const arg = task[1];
        if ( typeof arg === 'number' ) {
            this.i = arg;
        } else {
            this.s = arg;
        }
    }
    transpose(node, output) {
        if ( this.s !== '' ) {
            const parent = node.parentElement;
            if ( parent === null ) { return; }
            node = parent.closest(this.s);
            if ( node === null ) { return; }
        } else {
            let nth = this.i;
            for (;;) {
                node = node.parentElement;
                if ( node === null ) { return; }
                nth -= 1;
                if ( nth === 0 ) { break; }
            }
        }
        output.push(node);
    }
}
PSelectorUpwardTask.prototype.i = 0;
PSelectorUpwardTask.prototype.s = '';

class PSelectorXpathTask {
    constructor(task) {
        this.xpe = task[1];
    }
    transpose(node, output) {
        const xpr = docRegister.evaluate(
            this.xpe,
            node,
            null,
            XPathResult.UNORDERED_NODE_SNAPSHOT_TYPE,
            null
        );
        let j = xpr.snapshotLength;
        while ( j-- ) {
            const node = xpr.snapshotItem(j);
            if ( node.nodeType === 1 ) {
                output.push(node);
            }
        }
    }
}

class PSelector {
    constructor(o) {
        this.raw = o.raw;
        this.selector = o.selector;
        this.tasks = [];
        if ( !o.tasks ) { return; }
        for ( const task of o.tasks ) {
            const ctor = this.operatorToTaskMap.get(task[0]) || PSelectorVoidTask;
            const pselector = new ctor(task);
            this.tasks.push(pselector);
        }
    }
    prime(input) {
        const root = input || docRegister;
        if ( this.selector === '' ) { return [ root ]; }
        if ( input !== docRegister && /^ ?[>+~]/.test(this.selector) ) {
            return Array.from(PSelectorSpathTask.qsa(input, this.selector));
        }
        return Array.from(root.querySelectorAll(this.selector));
    }
    exec(input) {
        let nodes = this.prime(input);
        for ( const task of this.tasks ) {
            if ( nodes.length === 0 ) { break; }
            const transposed = [];
            for ( const node of nodes ) {
                task.transpose(node, transposed);
            }
            nodes = transposed;
        }
        return nodes;
    }
    test(input) {
        const nodes = this.prime(input);
        for ( const node of nodes ) {
            let output = [ node ];
            for ( const task of this.tasks ) {
                const transposed = [];
                for ( const node of output ) {
                    task.transpose(node, transposed);
                }
                output = transposed;
                if ( output.length === 0 ) { break; }
            }
            if ( output.length !== 0 ) { return true; }
        }
        return false;
    }
}
PSelector.prototype.operatorToTaskMap = new Map([
    [ 'has', PSelectorIfTask ],
    [ 'has-text', PSelectorHasTextTask ],
    [ 'if', PSelectorIfTask ],
    [ 'if-not', PSelectorIfNotTask ],
    [ 'min-text-length', PSelectorMinTextLengthTask ],
    [ 'not', PSelectorIfNotTask ],
    [ 'nth-ancestor', PSelectorUpwardTask ],
    [ 'spath', PSelectorSpathTask ],
    [ 'upward', PSelectorUpwardTask ],
    [ 'xpath', PSelectorXpathTask ],
]);

function logOne(details, exception, selector) {
    µb.filteringContext
        .duplicate()
        .fromTabId(details.tabId)
        .setRealm('extended')
        .setType('dom')
        .setURL(details.url)
        .setDocOriginFromURL(details.url)
        .setFilter({
            source: 'extended',
            raw: `${exception === 0 ? '##' : '#@#'}^${selector}`,
        })
        .toLogger();
}

function applyProceduralSelector(details, selector) {
    let pselector = pselectors.get(selector);
    if ( pselector === undefined ) {
        pselector = new PSelector(JSON.parse(selector));
        pselectors.set(selector, pselector);
    }
    const nodes = pselector.exec();
    let modified = false;
    for ( const node of nodes ) {
        node.remove();
        modified = true;
    }
    if ( modified && logger.enabled ) {
        logOne(details, 0, pselector.raw);
    }
    return modified;
}

function applyCSSSelector(details, selector) {
    const nodes = docRegister.querySelectorAll(selector);
    let modified = false;
    for ( const node of nodes ) {
        node.remove();
        modified = true;
    }
    if ( modified && logger.enabled ) {
        logOne(details, 0, selector);
    }
    return modified;
}

function logError(writer, msg) {
    logger.writeOne({
        realm: 'message',
        type: 'error',
        text: msg.replace('{who}', writer.properties.get('name') || '?')
    });
}

htmlFilteringEngine.reset = function() {
    filterDB.clear();
    pselectors.clear();
    duplicates.clear();
    acceptedCount = 0;
    discardedCount = 0;
};

htmlFilteringEngine.freeze = function() {
    duplicates.clear();
    filterDB.collectGarbage();
};

htmlFilteringEngine.compile = function(parser, writer) {
    const isException = parser.isException();
    const { raw, compiled } = parser.result;
    if ( compiled === undefined ) {
        return logError(writer, `Invalid HTML filter in {who}: ##${raw}`);
    }

    writer.select('HTML_FILTERS');

    // Only exception filters are allowed to be global.
    if ( parser.hasOptions() === false ) {
        if ( isException ) {
            writer.push([ 64, '', 1, compiled ]);
        }
        return;
    }

    const compiledFilters = [];
    let hasOnlyNegated = true;
    for ( const { hn, not, bad } of parser.getExtFilterDomainIterator() ) {
        if ( bad ) { continue; }
        const prefix = ((isException ? 1 : 0) ^ (not ? 1 : 0)) ? '-' : '+';
        if ( not === false ) {
            hasOnlyNegated = false;
        }
        compiledFilters.push([ 64, hn, `${prefix}${compiled}` ]);
    }

    // Not allowed since it's equivalent to forbidden generic HTML filters
    if ( isException === false && hasOnlyNegated ) {
        return logError(writer, `Invalid HTML filter in {who}: ##${raw}`);
    }

    writer.pushMany(compiledFilters);
};

htmlFilteringEngine.fromCompiledContent = function(reader) {
    // Don't bother loading filters if stream filtering is not supported.
    if ( µb.canFilterResponseData === false ) { return; }

    reader.select('HTML_FILTERS');

    while ( reader.next() ) {
        acceptedCount += 1;
        const fingerprint = reader.fingerprint();
        if ( duplicates.has(fingerprint) ) {
            discardedCount += 1;
            continue;
        }
        duplicates.add(fingerprint);
        const args = reader.args();
        filterDB.store(args[1], args[2]);
    }
};

htmlFilteringEngine.retrieve = function(fctxt) {
    const all = new Set();
    const hostname = fctxt.getHostname();
    filterDB.retrieveSpecifics(all, hostname);
    const entity = entityFromHostname(hostname, fctxt.getDomain());
    filterDB.retrieveSpecifics(all, entity);
    filterDB.retrieveSpecificsByRegex(all, hostname, fctxt.url);
    filterDB.retrieveGenerics(all);
    if ( all.size === 0 ) { return; }

    // https://github.com/gorhill/uBlock/issues/2835
    //   Do not filter if the site is under an `allow` rule.
    if ( µb.userSettings.advancedUserEnabled ) {
        if ( sessionFirewall.evaluateCellZY(hostname, hostname, '*') === 2 ) { return; }
    }

    // Split filters in different groups
    const plains = new Set();
    const procedurals = new Set();
    for ( const s of all ) {
        if ( s.charCodeAt(0) === 0x2D /* - */ ) { continue; }
        const selector = s.slice(1);
        const isProcedural = selector.startsWith('{');
        if ( all.has(`-${selector}`) ) {
            logOne(fctxt, 1, isProcedural ? JSON.parse(selector).raw : selector);
        } else if ( isProcedural ) {
            procedurals.add(selector);
        } else {
            plains.add(selector);
        }
    }

    if ( plains.size === 0 && procedurals.size === 0 ) { return; }

    return { plains, procedurals };
};

htmlFilteringEngine.apply = function(doc, details, selectors) {
    docRegister = doc;
    let modified = false;
    for ( const selector of selectors.plains ) {
        if ( applyCSSSelector(details, selector) ) {
            modified = true;
        }
    }
    for ( const selector of selectors.procedurals ) {
        if ( applyProceduralSelector(details, selector) ) {
            modified = true;
        }
    }
    docRegister = undefined;
    return modified;
};

htmlFilteringEngine.toSelfie = function() {
    return filterDB.toSelfie();
};

htmlFilteringEngine.fromSelfie = function(selfie) {
    filterDB.fromSelfie(selfie);
    pselectors.clear();
};

/******************************************************************************/

export default htmlFilteringEngine;

/******************************************************************************/

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
import { redirectEngine as reng } from './redirect-engine.js';

/******************************************************************************/

// For debugging convenience: all the top function calls will appear
// at the bottom of a generated content script
const codeSorter = (a, b) => {
    if ( a.startsWith('try') ) { return 1; }
    if ( b.startsWith('try') ) { return -1; }
    return 0;
};

const normalizeRawFilter = (parser, sourceIsTrusted = false) => {
    const args = parser.getScriptletArgs();
    if ( args.length !== 0 ) {
        let token = `${args[0]}.js`;
        if ( reng.aliases.has(token) ) {
            token = reng.aliases.get(token);
        }
        if ( parser.isException() !== true ) {
            if ( sourceIsTrusted !== true ) {
                if ( reng.tokenRequiresTrust(token) ) { return; }
            }
        }
        args[0] = token.slice(0, -3);
    }
    return JSON.stringify(args);
};

const lookupScriptlet = (rawToken, mainMap, isolatedMap, debug = false) => {
    if ( mainMap.has(rawToken) || isolatedMap.has(rawToken) ) { return; }
    const args = JSON.parse(rawToken);
    const token = `${args[0]}.js`;
    const details = reng.contentFromName(token, 'text/javascript');
    if ( details === undefined ) { return; }
    const targetWorldMap = details.world !== 'ISOLATED' ? mainMap : isolatedMap;
    const match = /^function\s+([^(\s]+)\s*\(/.exec(details.js);
    const fname = match && match[1];
    const content = patchScriptlet(fname, details.js, args.slice(1));
    if ( fname ) {
        targetWorldMap.set(token, details.js);
    }
    const dependencies = details.dependencies || [];
    while ( dependencies.length !== 0 ) {
        const token = dependencies.shift();
        if ( targetWorldMap.has(token) ) { continue; }
        const details = reng.contentFromName(token, 'fn/javascript') ||
            reng.contentFromName(token, 'text/javascript');
        if ( details === undefined ) { continue; }
        targetWorldMap.set(token, details.js);
        if ( Array.isArray(details.dependencies) === false ) { continue; }
        dependencies.push(...details.dependencies);
    }
    targetWorldMap.set(rawToken, [
        'try {',
            `\t${content}`,
        '} catch (e) {',
            debug ? '\tconsole.error(e);' : '',
        '}',
    ].join('\n'));
};

// Fill-in scriptlet argument placeholders.
const patchScriptlet = (fname, content, arglist) => {
    if ( fname ) {
        content = `${fname}({{args}});`;
    } else {
        for ( let i = 0; i < arglist.length; i++ ) {
            content = content.replace(`{{${i+1}}}`, arglist[i]);
        }
    }
    return content.replace('{{args}}',
        JSON.stringify(arglist).slice(1,-1).replace(/\$/g, '$$$')
    );
};

const requote = s => {
    if ( /^(["'`]).*\1$|,|^$/.test(s) === false ) { return s; }
    if ( s.includes("'") === false ) { return `'${s}'`; }
    if ( s.includes('"') === false ) { return `"${s}"`; }
    if ( s.includes('`') === false ) { return `\`${s}\``; }
    return `'${s.replace(/'/g, "\\'")}'`;
};

const decompile = (json, isException) => {
    const prefix = isException ? '#@#' : '##';
    const args = JSON.parse(json);
    return `${prefix}+js(${args.map(s => requote(s)).join(', ')})`;
};

/******************************************************************************/

export class ScriptletFilteringEngine {
    constructor() {
        this.acceptedCount = 0;
        this.discardedCount = 0;
        this.scriptletDB = new StaticExtFilteringHostnameDB();
        this.duplicates = new Set();
    }

    getFilterCount() {
        return this.scriptletDB.size;
    }

    reset() {
        this.scriptletDB.clear();
        this.duplicates.clear();
        this.acceptedCount = 0;
        this.discardedCount = 0;
    }

    freeze() {
        this.duplicates.clear();
        this.scriptletDB.collectGarbage();
    }

    // parser: instance of AstFilterParser from static-filtering-parser.js
    // writer: instance of CompiledListWriter from static-filtering-io.js
    compile(parser, writer) {
        writer.select('SCRIPTLET_FILTERS');

        // Only exception filters are allowed to be global.
        const isException = parser.isException();
        const normalized = normalizeRawFilter(parser, writer.properties.get('trustedSource'));

        // Can fail if there is a mismatch with trust requirement
        if ( normalized === undefined ) { return; }

        // Tokenless is meaningful only for exception filters.
        if ( normalized === '[]' && isException === false ) { return; }

        if ( parser.hasOptions() === false ) {
            if ( isException ) {
                writer.push([ 32, '', `-${normalized}` ]);
            }
            return;
        }

        // https://github.com/gorhill/uBlock/issues/3375
        //   Ignore instances of exception filter with negated hostnames,
        //   because there is no way to create an exception to an exception.

        for ( const { hn, not, bad } of parser.getExtFilterDomainIterator() ) {
            if ( bad ) { continue; }
            const prefix = ((isException ? 1 : 0) ^ (not ? 1 : 0)) ? '-' : '+';
            writer.push([ 32, hn, `${prefix}${normalized}` ]);
        }
    }

    // writer: instance of CompiledListReader from static-filtering-io.js
    fromCompiledContent(reader) {
        reader.select('SCRIPTLET_FILTERS');

        while ( reader.next() ) {
            this.acceptedCount += 1;
            const fingerprint = reader.fingerprint();
            if ( this.duplicates.has(fingerprint) ) {
                this.discardedCount += 1;
                continue;
            }
            this.duplicates.add(fingerprint);
            const args = reader.args();
            this.scriptletDB.store(args[1], args[2]);
        }
    }

    toSelfie() {
        return this.scriptletDB.toSelfie();
    }

    fromSelfie(selfie) {
        this.scriptletDB.fromSelfie(selfie);
        return true;
    }

    retrieve(request, options = {}) {
        if ( this.scriptletDB.size === 0 ) { return; }

        const all = new Set();
        const { ancestors = [], domain, hostname } = request;

        this.scriptletDB.retrieveSpecifics(all, hostname);
        const entity = entityFromHostname(hostname, domain);
        this.scriptletDB.retrieveSpecifics(all, entity);
        this.scriptletDB.retrieveSpecificsByRegex(all, hostname, request.url);
        this.scriptletDB.retrieveGenerics(all);
        const visitedAncestors = [];
        for ( const ancestor of ancestors ) {
            const { domain, hostname } = ancestor;
            if ( visitedAncestors.includes(hostname) ) { continue; }
            visitedAncestors.push(hostname);
            this.scriptletDB.retrieveSpecifics(all, `${hostname}>>`);
            const entity = entityFromHostname(hostname, domain);
            if ( entity !== '' ) {
                this.scriptletDB.retrieveSpecifics(all, `${entity}>>`);
            }
        }
        if ( all.size === 0 ) { return; }

        // Wholly disable scriptlet injection?
        if ( all.has('-[]') ) {
            return { filters: [ '#@#+js()' ] };
        }

        // Split filters in different groups
        const scriptlets = new Set();
        const exceptions = new Set();
        for ( const s of all ) {
            if ( s.charCodeAt(0) === 0x2D /* - */ ) { continue; }
            const selector = s.slice(1);
            if ( all.has(`-${selector}`) ) {
                exceptions.add(selector);
            } else {
                scriptlets.add(selector);
            }
        }

        const mainWorldMap = new Map();
        const isolatedWorldMap = new Map();

        for ( const token of scriptlets ) {
            lookupScriptlet(token, mainWorldMap, isolatedWorldMap, options.debug);
        }

        if ( scriptlets.size !== 0 ) {
            if ( mainWorldMap.size === 0 ) {
                if ( isolatedWorldMap.size === 0 ) { return; }
            }
        }

        const mainWorldCode = [];
        for ( const js of mainWorldMap.values() ) {
            mainWorldCode.push(js);
        }
        mainWorldCode.sort(codeSorter);

        const isolatedWorldCode = [];
        for ( const js of isolatedWorldMap.values() ) {
            isolatedWorldCode.push(js);
        }
        isolatedWorldCode.sort(codeSorter);

        const scriptletDetails = {
            mainWorld: mainWorldCode.join('\n\n'),
            isolatedWorld: isolatedWorldCode.join('\n\n'),
            filters: [
                ...Array.from(scriptlets).map(a => decompile(a, false)),
                ...Array.from(exceptions).map(a => decompile(a, true)),
            ],
        };

        const scriptletGlobals = options.scriptletGlobals || {};

        if ( options.debug ) {
            scriptletGlobals.canDebug = true;
        }

        const scriptletGlobalsJSON = JSON.stringify(scriptletGlobals, null, 4);

        return {
            mainWorld: scriptletDetails.mainWorld === '' ? '' : [
                '(function() {',
                '// >>>> start of private namespace',
                '',
                options.debugScriptlets ? 'debugger;' : ';',
                '',
                // For use by scriptlets to share local data among themselves
                `const scriptletGlobals = ${scriptletGlobalsJSON};`,
                '',
                scriptletDetails.mainWorld,
                '',
                '// <<<< end of private namespace',
                '})();',
            ].join('\n'),
            isolatedWorld: scriptletDetails.isolatedWorld === '' ? '' : [
                'function() {',
                '// >>>> start of private namespace',
                '',
                options.debugScriptlets ? 'debugger;' : ';',
                '',
                // For use by scriptlets to share local data among themselves
                `const scriptletGlobals = ${scriptletGlobalsJSON};`,
                '',
                scriptletDetails.isolatedWorld,
                '',
                '// <<<< end of private namespace',
                '}',
            ].join('\n'),
            filters: scriptletDetails.filters,
        };
    }
}

/******************************************************************************/

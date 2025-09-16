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

import * as s14e from './s14e-serializer.js';
import { dom, qs$ } from './dom.js';

/******************************************************************************/

const reFoldable = /^ *(?=\+ \S)/;

/******************************************************************************/

CodeMirror.registerGlobalHelper(
    'fold',
    'ubo-dump',
    ( ) => true,
    (cm, start) => {
        const startLineNo = start.line;
        const startLine = cm.getLine(startLineNo);
        let endLineNo = startLineNo;
        let endLine = startLine;
        const match = reFoldable.exec(startLine);
        if ( match === null ) { return; }
        const foldCandidate = '  ' + match[0];
        const lastLineNo = cm.lastLine();
        let nextLineNo = startLineNo + 1;
        while ( nextLineNo < lastLineNo ) {
            const nextLine = cm.getLine(nextLineNo);
            // TODO: use regex to find folding end
            if ( nextLine.startsWith(foldCandidate) === false && nextLine !== ']' ) {
                if ( startLineNo >= endLineNo ) { return; }
                return {
                    from: CodeMirror.Pos(startLineNo, startLine.length),
                    to: CodeMirror.Pos(endLineNo, endLine.length)
                };
            }
            endLine = nextLine;
            endLineNo = nextLineNo;
            nextLineNo += 1;
        }
    }
);

const cmEditor = new CodeMirror(qs$('#console'), {
    autofocus: true,
    foldGutter: true,
    gutters: [ 'CodeMirror-linenumbers', 'CodeMirror-foldgutter' ],
    lineNumbers: true,
    lineWrapping: true,
    mode: 'ubo-dump',
    styleActiveLine: true,
    undoDepth: 5,
});

uBlockDashboard.patchCodeMirrorEditor(cmEditor);

/******************************************************************************/

function log(text) {
    cmEditor.replaceRange(text.trim() + '\n\n', { line: 0, ch: 0 });
}

/******************************************************************************/

function toDNRText(raw) {
    const result = s14e.deserialize(raw);
    if ( typeof result === 'string' ) { return result; }
    const { network } = result;
    const replacer = (k, v) => {
        if ( k.startsWith('__') ) { return; }
        if ( Array.isArray(v) ) {
            return v.sort();
        }
        if ( v instanceof Object ) {
            const sorted = {};
            for ( const kk of Object.keys(v).sort() ) {
                sorted[kk] = v[kk];
            }
            return sorted;
        }
        return v;
    };
    const isUnsupported = rule =>
        rule._error !== undefined;
    const isRegex = rule =>
        rule.condition !== undefined &&
        rule.condition.regexFilter !== undefined;
    const isRedirect = rule =>
        rule.action !== undefined &&
        rule.action.type === 'redirect' &&
        rule.action.redirect.extensionPath !== undefined;
    const isCsp = rule =>
        rule.action !== undefined &&
        rule.action.type === 'modifyHeaders';
    const isRemoveparam = rule =>
        rule.action !== undefined &&
        rule.action.type === 'redirect' &&
        rule.action.redirect.transform !== undefined;
    const { ruleset } = network;
    const good = ruleset.filter(rule =>
        isUnsupported(rule) === false &&
        isRegex(rule) === false &&
        isRedirect(rule) === false &&
        isCsp(rule) === false &&
        isRemoveparam(rule) === false
    );
    const unsupported = ruleset.filter(rule =>
        isUnsupported(rule)
    );
    const regexes = ruleset.filter(rule =>
        isUnsupported(rule) === false &&
        isRegex(rule) &&
        isRedirect(rule) === false &&
        isCsp(rule) === false &&
        isRemoveparam(rule) === false
    );
    const redirects = ruleset.filter(rule =>
        isUnsupported(rule) === false &&
        isRedirect(rule)
    );
    const headers = ruleset.filter(rule =>
        isUnsupported(rule) === false &&
        isCsp(rule)
    );
    const removeparams = ruleset.filter(rule =>
        isUnsupported(rule) === false &&
        isRemoveparam(rule)
    );
    const out = [
        `dnrRulesetFromRawLists(${JSON.stringify(result.listNames, null, 2)})`,
        `Run time: ${result.runtime} ms`,
        `Filters count: ${network.filterCount}`,
        `Accepted filter count: ${network.acceptedFilterCount}`,
        `Rejected filter count: ${network.rejectedFilterCount}`,
        `Un-DNR-able filter count: ${unsupported.length}`,
        `Resulting DNR rule count: ${ruleset.length}`,
    ];
    out.push(`+ Good filters (${good.length}): ${JSON.stringify(good, replacer, 2)}`);
    out.push(`+ Regex-based filters (${regexes.length}): ${JSON.stringify(regexes, replacer, 2)}`);
    out.push(`+ 'redirect=' filters (${redirects.length}): ${JSON.stringify(redirects, replacer, 2)}`);
    out.push(`+ 'csp=' filters (${headers.length}): ${JSON.stringify(headers, replacer, 2)}`);
    out.push(`+ 'removeparam=' filters (${removeparams.length}): ${JSON.stringify(removeparams, replacer, 2)}`);
    out.push(`+ Unsupported filters (${unsupported.length}): ${JSON.stringify(unsupported, replacer, 2)}`);
    out.push(`+ generichide exclusions (${network.generichideExclusions.length}): ${JSON.stringify(network.generichideExclusions, replacer, 2)}`);
    if ( result.specificCosmetic ) {
        out.push(`+ Cosmetic filters: ${result.specificCosmetic.size}`);
        for ( const details of result.specificCosmetic ) {
            out.push(`    ${JSON.stringify(details)}`);
        }
    } else {
        out.push('  Cosmetic filters: 0');
    }
    return out.join('\n');
}


/******************************************************************************/

dom.on('#console-clear', 'click', ( ) => {
    cmEditor.setValue('');
});

dom.on('#console-fold', 'click', ( ) => {
    const unfolded = [];
    let maxUnfolded = -1;
    cmEditor.eachLine(handle => {
        const match = reFoldable.exec(handle.text);
        if ( match === null ) { return; }
        const depth = match[0].length;
        const line = handle.lineNo();
        const isFolded = cmEditor.isFolded({ line, ch: handle.text.length });
        if ( isFolded === true ) { return; }
        unfolded.push({ line, depth });
        maxUnfolded = Math.max(maxUnfolded, depth);
    });
    if ( maxUnfolded === -1 ) { return; }
    cmEditor.startOperation();
    for ( const details of unfolded ) {
        if ( details.depth !== maxUnfolded ) { continue; }
        cmEditor.foldCode(details.line, null, 'fold');
    }
    cmEditor.endOperation();
});

dom.on('#console-unfold', 'click', ( ) => {
    const folded = [];
    let minFolded = Number.MAX_SAFE_INTEGER;
    cmEditor.eachLine(handle => {
        const match = reFoldable.exec(handle.text);
        if ( match === null ) { return; }
        const depth = match[0].length;
        const line = handle.lineNo();
        const isFolded = cmEditor.isFolded({ line, ch: handle.text.length });
        if ( isFolded !== true ) { return; }
        folded.push({ line, depth });
        minFolded = Math.min(minFolded, depth);
    });
    if ( minFolded === Number.MAX_SAFE_INTEGER ) { return; }
    cmEditor.startOperation();
    for ( const details of folded ) {
        if ( details.depth !== minFolded ) { continue; }
        cmEditor.foldCode(details.line, null, 'unfold');
    }
    cmEditor.endOperation();
});

dom.on('#snfe-dump', 'click', ev => {
    const button = ev.target;
    dom.attr(button, 'disabled', '');
    vAPI.messaging.send('devTools', {
        what: 'snfeDump',
    }).then(result => {
        log(result);
        dom.attr(button, 'disabled', null);
    });
});

dom.on('#snfe-todnr', 'click', ev => {
    const button = ev.target;
    dom.attr(button, 'disabled', '');
    vAPI.messaging.send('devTools', {
        what: 'snfeToDNR',
    }).then(result => {
        log(toDNRText(result));
        dom.attr(button, 'disabled', null);
    });
});

dom.on('#cfe-dump', 'click', ev => {
    const button = ev.target;
    dom.attr(button, 'disabled', '');
    vAPI.messaging.send('devTools', {
        what: 'cfeDump',
    }).then(result => {
        log(result);
        dom.attr(button, 'disabled', null);
    });
});

dom.on('#purge-all-caches', 'click', ( ) => {
    vAPI.messaging.send('devTools', {
        what: 'purgeAllCaches'
    }).then(result => {
        log(result);
    });
});

vAPI.messaging.send('dashboard', {
    what: 'getAppData',
}).then(appData => {
    if ( appData.canBenchmark !== true ) { return; }
    dom.attr('#snfe-benchmark', 'disabled', null);
    dom.on('#snfe-benchmark', 'click', ev => {
        const button = ev.target;
        dom.attr(button, 'disabled', '');
        vAPI.messaging.send('devTools', {
            what: 'snfeBenchmark',
        }).then(result => {
            log(result);
            dom.attr(button, 'disabled', null);
        });
    });
    dom.attr('#cfe-benchmark', 'disabled', null);
    dom.on('#cfe-benchmark', 'click', ev => {
        const button = ev.target;
        dom.attr(button, 'disabled', '');
        vAPI.messaging.send('devTools', {
            what: 'cfeBenchmark',
        }).then(result => {
            log(result);
            dom.attr(button, 'disabled', null);
        });
    });
    dom.attr('#sfe-benchmark', 'disabled', null);
    dom.on('#sfe-benchmark', 'click', ev => {
        const button = ev.target;
        dom.attr(button, 'disabled', '');
        vAPI.messaging.send('devTools', {
            what: 'sfeBenchmark',
        }).then(result => {
            log(result);
            dom.attr(button, 'disabled', null);
        });
    });
});

/******************************************************************************/

async function snfeQuery(lineNo, query) {
    const doc = cmEditor.getDoc();
    const lineHandle = doc.getLineHandle(lineNo)
    const result = await vAPI.messaging.send('devTools', {
        what: 'snfeQuery',
        query
    });
    if ( typeof result !== 'string' ) { return; }
    cmEditor.startOperation();
    const nextLineNo = doc.getLineNumber(lineHandle) + 1;
    doc.replaceRange(`${result}\n`, { line: nextLineNo, ch: 0 });
    cmEditor.endOperation();
}

cmEditor.on('beforeChange', (cm, details) => {
    if ( details.origin !== '+input' ) { return; }
    if ( details.text.length !== 2 ) { return; }
    if ( details.text[1] !== '' ) { return; }
    const lineNo = details.from.line;
    const line = cm.getLine(lineNo);
    if ( details.from.ch !== line.length ) { return; }
    if ( line.startsWith('snfe?') === false ) { return; }
    const fields = line.slice(5).split(/\s+/);
    const query = {};
    for ( const field of fields ) {
        if ( field === '' ) { continue; }
        if ( /[/.]/.test(field) ) {
            if ( query.url === undefined ) {
                query.url = field;
            } else if ( query.from === undefined ) {
                query.from = field;
            }
        } else if ( query.type === undefined ) {
            query.type = field;
        }
    }
    if ( query.url === undefined ) { return; }
    snfeQuery(lineNo, query);
});

/******************************************************************************/

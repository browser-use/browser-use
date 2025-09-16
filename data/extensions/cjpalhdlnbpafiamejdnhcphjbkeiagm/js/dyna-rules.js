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

    Home: https://github.com/gorhill/uMatrix
*/

/* global CodeMirror, diff_match_patch, uBlockDashboard */

import './codemirror/ubo-dynamic-filtering.js';
import { dom, qs$, qsa$ } from './dom.js';
import { hostnameFromURI } from './uri-utils.js';
import { i18n$ } from './i18n.js';
import publicSuffixList from '../lib/publicsuffixlist/publicsuffixlist.js';

/******************************************************************************/

const hostnameToDomainMap = new Map();

const mergeView = new CodeMirror.MergeView(
    qs$('.codeMirrorMergeContainer'),
    {
        allowEditingOriginals: true,
        connect: 'align',
        inputStyle: 'contenteditable',
        lineNumbers: true,
        lineWrapping: false,
        origLeft: '',
        revertButtons: true,
        value: '',
    }
);
mergeView.editor().setOption('styleActiveLine', true);
mergeView.editor().setOption('lineNumbers', false);
mergeView.leftOriginal().setOption('readOnly', 'nocursor');

uBlockDashboard.patchCodeMirrorEditor(mergeView.editor());

const thePanes = {
    orig: {
        doc: mergeView.leftOriginal(),
        original: [],
        modified: [],
    },
    edit: {
        doc: mergeView.editor(),
        original: [],
        modified: [],
    },
};

let cleanEditToken = 0;
let cleanEditText = '';

/******************************************************************************/

// The following code is to take care of properly internationalizing
// the tooltips of the arrows used by the CodeMirror merge view. These
// are hard-coded by CodeMirror ("Push to left", "Push to right"). An
// observer is necessary because there is no hook for uBO to overwrite
// reliably the default title attribute assigned by CodeMirror.

{
    const i18nCommitStr = i18n$('rulesCommit');
    const i18nRevertStr = i18n$('rulesRevert');
    const commitArrowSelector = '.CodeMirror-merge-copybuttons-left .CodeMirror-merge-copy-reverse:not([title="' + i18nCommitStr + '"])';
    const revertArrowSelector = '.CodeMirror-merge-copybuttons-left .CodeMirror-merge-copy:not([title="' + i18nRevertStr + '"])';

    dom.attr('.CodeMirror-merge-scrolllock', 'title', i18n$('genericMergeViewScrollLock'));

    const translate = function() {
        let elems = qsa$(commitArrowSelector);
        for ( const elem of elems ) {
            dom.attr(elem, 'title', i18nCommitStr);
        }
        elems = qsa$(revertArrowSelector);
        for ( const elem of elems ) {
            dom.attr(elem, 'title', i18nRevertStr);
        }
    };

    const mergeGapObserver = new MutationObserver(translate);

    mergeGapObserver.observe(
        qs$('.CodeMirror-merge-copybuttons-left'),
        { attributes: true, attributeFilter: [ 'title' ], subtree: true }
    );
}

/******************************************************************************/

const getDiffer = (( ) => {
    let differ;
    return ( ) => {
        if ( differ === undefined ) { differ = new diff_match_patch(); }
        return differ;
    };
})();

/******************************************************************************/

// Borrowed from...
// https://github.com/codemirror/CodeMirror/blob/3e1bb5fff682f8f6cbfaef0e56c61d62403d4798/addon/search/search.js#L22
// ... and modified as needed.

const updateOverlay = (( ) => {
    let reFilter;
    const mode = {
        token: function(stream) {
            if ( reFilter !== undefined ) {
                reFilter.lastIndex = stream.pos;
                let match = reFilter.exec(stream.string);
                if ( match !== null ) {
                    if ( match.index === stream.pos ) {
                        stream.pos += match[0].length || 1;
                        return 'searching';
                    }
                    stream.pos = match.index;
                    return;
                }
            }
            stream.skipToEnd();
        }
    };
    return function() {
        const f = presentationState.filter;
        reFilter = typeof f === 'string' && f !== ''
            ? new RegExp(f.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi')
            : undefined;
        return mode;
    };
})();

const toggleOverlay = (( ) => {
    let overlay = null;

    return function() {
        if ( overlay !== null ) {
            mergeView.leftOriginal().removeOverlay(overlay);
            mergeView.editor().removeOverlay(overlay);
            overlay = null;
        }
        if ( presentationState.filter !== '' ) {
            overlay = updateOverlay();
            mergeView.leftOriginal().addOverlay(overlay);
            mergeView.editor().addOverlay(overlay);
        }
        rulesToDoc(true);
        savePresentationState();
    };
})();

/******************************************************************************/

// Incrementally update text in a CodeMirror editor for best user experience:
// - Scroll position preserved
// - Minimum amount of text updated

function rulesToDoc(clearHistory) {
    const orig = thePanes.orig.doc;
    const edit = thePanes.edit.doc;
    orig.startOperation();
    edit.startOperation();

    for ( const key in thePanes ) {
        if ( Object.hasOwn(thePanes, key) === false ) { continue; }
        const doc = thePanes[key].doc;
        const rules = filterRules(key);
        if (
            clearHistory ||
            doc.lineCount() === 1 && doc.getValue() === '' ||
            rules.length === 0
        ) {
            doc.setValue(rules.length !== 0 ? rules.join('\n') + '\n' : '');
            continue;
        }
        // https://github.com/uBlockOrigin/uBlock-issues/issues/593
        //   Ensure the text content always ends with an empty line to avoid
        //   spurious diff entries.
        // https://github.com/uBlockOrigin/uBlock-issues/issues/657
        //   Diff against unmodified beforeText so that the last newline can
        //   be reported in the diff and thus appended if needed.
        let beforeText = doc.getValue();
        let afterText = rules.join('\n').trim();
        if ( afterText !== '' ) { afterText += '\n'; }
        const diffs = getDiffer().diff_main(beforeText, afterText);
        let i = diffs.length;
        let iedit = beforeText.length;
        while ( i-- ) {
            const diff = diffs[i];
            if ( diff[0] === 0 ) {
                iedit -= diff[1].length;
                continue;
            }
            const end = doc.posFromIndex(iedit);
            if ( diff[0] === 1 ) {
                doc.replaceRange(diff[1], end, end);
                continue;
            }
            /* diff[0] === -1 */
            iedit -= diff[1].length;
            const beg = doc.posFromIndex(iedit);
            doc.replaceRange('', beg, end);
        }
    }

    // Mark ellipses as read-only
    const marks = edit.getAllMarks();
    for ( const mark of marks ) {
        if ( mark.uboEllipsis !== true ) { continue; }
        mark.clear();
    }
    if ( presentationState.isCollapsed ) {
        for ( let iline = 0, n = edit.lineCount(); iline < n; iline++ ) {
            if ( edit.getLine(iline) !== '...' ) { continue; }
            const mark = edit.markText(
                { line: iline, ch: 0 },
                { line: iline + 1, ch: 0 },
                { atomic: true, readOnly: true }
            );
            mark.uboEllipsis = true;
        }
    }

    orig.endOperation();
    edit.endOperation();
    cleanEditText = mergeView.editor().getValue().trim();
    cleanEditToken = mergeView.editor().changeGeneration();

    if ( clearHistory !== true ) { return; }

    mergeView.editor().clearHistory();
    const chunks = mergeView.leftChunks();
    if ( chunks.length === 0 ) { return; }
    const ldoc = thePanes.orig.doc;
    const { clientHeight } = ldoc.getScrollInfo();
    const line = Math.min(chunks[0].editFrom, chunks[0].origFrom);
    ldoc.setCursor(line, 0);
    ldoc.scrollIntoView(
        { line, ch: 0 },
        (clientHeight - ldoc.defaultTextHeight()) / 2
    );
}

/******************************************************************************/

function filterRules(key) {
    const filter = qs$('#ruleFilter input').value;
    const rules = thePanes[key].modified;
    if ( filter === '' ) { return rules; }
    const out = [];
    for ( const rule of rules ) {
        if ( rule.indexOf(filter) === -1 ) { continue; }
        out.push(rule);
    }
    return out;
}

/******************************************************************************/

async function applyDiff(permanent, toAdd, toRemove) {
    const details = await vAPI.messaging.send('dashboard', {
        what: 'modifyRuleset',
        permanent: permanent,
        toAdd: toAdd,
        toRemove: toRemove,
    });
    thePanes.orig.original = details.permanentRules;
    thePanes.edit.original = details.sessionRules;
    onPresentationChanged();
}

/******************************************************************************/

// CodeMirror quirk: sometimes fromStart.ch and/or toStart.ch is undefined.
// When this happens, use 0.

mergeView.options.revertChunk = function(
    mv,
    from, fromStart, fromEnd,
    to, toStart, toEnd
) {
    // https://github.com/gorhill/uBlock/issues/3611
    if ( dom.attr(dom.body, 'dir') === 'rtl' ) {
        let tmp = from; from = to; to = tmp;
        tmp = fromStart; fromStart = toStart; toStart = tmp;
        tmp = fromEnd; fromEnd = toEnd; toEnd = tmp;
    }
    if ( typeof fromStart.ch !== 'number' ) { fromStart.ch = 0; }
    if ( fromEnd.ch !== 0 ) { fromEnd.line += 1; }
    const toAdd = from.getRange(
        { line: fromStart.line, ch: 0 },
        { line: fromEnd.line, ch: 0 }
    );
    if ( typeof toStart.ch !== 'number' ) { toStart.ch = 0; }
    if ( toEnd.ch !== 0 ) { toEnd.line += 1; }
    const toRemove = to.getRange(
        { line: toStart.line, ch: 0 },
        { line: toEnd.line, ch: 0 }
    );
    applyDiff(from === mv.editor(), toAdd, toRemove);
};

/******************************************************************************/

function handleImportFilePicker() {
    const fileReaderOnLoadHandler = function() {
        if ( typeof this.result !== 'string' || this.result === '' ) { return; }
        // https://github.com/chrisaljoudi/uBlock/issues/757
        // Support RequestPolicy rule syntax
        let result = this.result;
        let matches = /\[origins-to-destinations\]([^[]+)/.exec(result);
        if ( matches && matches.length === 2 ) {
            result = matches[1].trim()
                               .replace(/\|/g, ' ')
                               .replace(/\n/g, ' * noop\n');
        }
        applyDiff(false, result, '');
    };
    const file = this.files[0];
    if ( file === undefined || file.name === '' ) { return; }
    if ( file.type.indexOf('text') !== 0 ) { return; }
    const fr = new FileReader();
    fr.onload = fileReaderOnLoadHandler;
    fr.readAsText(file);
}

/******************************************************************************/

function startImportFilePicker() {
    const input = qs$('#importFilePicker');
    // Reset to empty string, this will ensure an change event is properly
    // triggered if the user pick a file, even if it is the same as the last
    // one picked.
    input.value = '';
    input.click();
}

/******************************************************************************/

function exportUserRulesToFile() {
    const filename = i18n$('rulesDefaultFileName')
        .replace('{{datetime}}', uBlockDashboard.dateNowToSensibleString())
        .replace(/ +/g, '_');
    vAPI.download({
        url: 'data:text/plain,' + encodeURIComponent(
            mergeView.leftOriginal().getValue().trim() + '\n'
        ),
        filename: filename,
        saveAs: true
    });
}

/******************************************************************************/

{
    let timer;

    dom.on('#ruleFilter input', 'input', ( ) => {
        if ( timer !== undefined ) { self.cancelIdleCallback(timer); }
        timer = self.requestIdleCallback(( ) => {
            timer = undefined;
            if ( mergeView.editor().isClean(cleanEditToken) === false ) { return; }
            const filter = qs$('#ruleFilter input').value;
            if ( filter === presentationState.filter ) { return; }
            presentationState.filter = filter;
            toggleOverlay();
        }, { timeout: 773 });
    });
}

/******************************************************************************/

const onPresentationChanged = (( ) => {
    const reSwRule = /^([^/]+): ([^/ ]+) ([^ ]+)/;
    const reRule   = /^([^ ]+) ([^/ ]+) ([^ ]+ [^ ]+)/;
    const reUrlRule = /^([^ ]+) ([^ ]+) ([^ ]+ [^ ]+)/;

    const sortNormalizeHn = function(hn) {
        let domain = hostnameToDomainMap.get(hn);
        if ( domain === undefined ) {
            domain = /(\d|\])$/.test(hn)
                ? hn
                : publicSuffixList.getDomain(hn);
            hostnameToDomainMap.set(hn, domain);
        }
        let normalized = domain || hn;
        if ( hn.length !== domain.length ) {
            const subdomains = hn.slice(0, hn.length - domain.length - 1);
            normalized += '.' + (
                subdomains.includes('.')
                    ? subdomains.split('.').reverse().join('.')
                    : subdomains
            );
        }
        return normalized;
    };

    const slotFromRule = rule => {
        let type, srcHn, desHn, extra;
        let match = reSwRule.exec(rule);
        if ( match !== null ) {
            type = ' ' + match[1];
            srcHn = sortNormalizeHn(match[2]);
            desHn = srcHn;
            extra = match[3];
        } else if ( (match = reRule.exec(rule)) !== null ) {
            type = '\x10FFFE';
            srcHn = sortNormalizeHn(match[1]);
            desHn = sortNormalizeHn(match[2]);
            extra = match[3];
        } else if ( (match = reUrlRule.exec(rule)) !== null ) {
            type = '\x10FFFF';
            srcHn = sortNormalizeHn(match[1]);
            desHn = sortNormalizeHn(hostnameFromURI(match[2]));
            extra = match[3];
        }
        if ( presentationState.sortType === 0 ) {
            return { rule, token: `${type} ${srcHn} ${desHn} ${extra}` };
        }
        if ( presentationState.sortType === 1 ) {
            return { rule, token: `${srcHn} ${type} ${desHn} ${extra}` };
        }
        return { rule, token: `${desHn} ${type} ${srcHn} ${extra}` };
    };

    const sort = rules => {
        const slots = [];
        for ( let i = 0; i < rules.length; i++ ) {
            slots.push(slotFromRule(rules[i], 1));
        }
        slots.sort((a, b) => a.token.localeCompare(b.token));
        for ( let i = 0; i < rules.length; i++ ) {
            rules[i] = slots[i].rule;
        }
    };

    const collapse = ( ) => {
        if ( presentationState.isCollapsed !== true ) { return; }
        const diffs = getDiffer().diff_main(
            thePanes.orig.modified.join('\n'),
            thePanes.edit.modified.join('\n')
        );
        const ll = []; let lellipsis = false;
        const rr = []; let rellipsis = false;
        for ( let i = 0; i < diffs.length; i++ ) {
            const diff =  diffs[i];
            if ( diff[0] === 0 ) {
                lellipsis = rellipsis = true;
                continue;
            }
            if ( diff[0] < 0 ) {
                if ( lellipsis ) {
                    ll.push('...');
                    if ( rellipsis ) { rr.push('...'); }
                    lellipsis = rellipsis = false;
                }
                ll.push(diff[1].trim());
                continue;
            }
            /* diff[0] > 0 */
            if ( rellipsis ) {
                rr.push('...');
                if ( lellipsis ) { ll.push('...'); }
                lellipsis = rellipsis = false;
            }
            rr.push(diff[1].trim());
        }
        if ( lellipsis ) { ll.push('...'); }
        if ( rellipsis ) { rr.push('...'); }
        thePanes.orig.modified = ll;
        thePanes.edit.modified = rr;
    };

    dom.on('#ruleFilter select', 'input', ev => {
        presentationState.sortType = parseInt(ev.target.value, 10) || 0;
        savePresentationState();
        onPresentationChanged(true);
    });
    dom.on('#ruleFilter #diffCollapse', 'click', ev => {
        presentationState.isCollapsed = dom.cl.toggle(ev.target, 'active');
        savePresentationState();
        onPresentationChanged(true);
    });

    return function onPresentationChanged(clearHistory) {
        const origPane = thePanes.orig;
        const editPane = thePanes.edit;
        origPane.modified = origPane.original.slice();
        editPane.modified = editPane.original.slice();
        {
            const mode = origPane.doc.getMode();
            mode.sortType = presentationState.sortType;
            mode.setHostnameToDomainMap(hostnameToDomainMap);
            mode.setPSL(publicSuffixList);
        }
        {
            const mode = editPane.doc.getMode();
            mode.sortType = presentationState.sortType;
            mode.setHostnameToDomainMap(hostnameToDomainMap);
            mode.setPSL(publicSuffixList);
        }
        sort(origPane.modified);
        sort(editPane.modified);
        collapse();
        rulesToDoc(clearHistory);
        onTextChanged(clearHistory);
    };
})();

/******************************************************************************/

const onTextChanged = (( ) => {
    let timer;

    const process = details => {
        timer = undefined;
        const diff = qs$('#diff');
        let isClean = mergeView.editor().isClean(cleanEditToken);
        if (
            details === undefined &&
            isClean === false &&
            mergeView.editor().getValue().trim() === cleanEditText
        ) {
            cleanEditToken = mergeView.editor().changeGeneration();
            isClean = true;
        }
        const isDirty = mergeView.leftChunks().length !== 0;
        dom.cl.toggle(dom.body, 'editing', isClean === false);
        dom.cl.toggle(diff, 'dirty', isDirty);
        dom.cl.toggle('#editSaveButton', 'disabled', isClean);
        dom.cl.toggle('#exportButton,#importButton', 'disabled', isClean === false);
        dom.cl.toggle('#revertButton,#commitButton', 'disabled', isClean === false || isDirty === false);
        const input = qs$('#ruleFilter input');
        if ( isClean ) {
            dom.attr(input, 'disabled', null);
            CodeMirror.commands.save = undefined;
        } else {
            dom.attr(input, 'disabled', '');
            CodeMirror.commands.save = editSaveHandler;
        }
    };

    return function onTextChanged(now) {
        if ( timer !== undefined ) { self.cancelIdleCallback(timer); }
        timer = now ? process() : self.requestIdleCallback(process, { timeout: 57 });
    };
})();

/******************************************************************************/

function revertAllHandler() {
    const toAdd = [], toRemove = [];
    const left = mergeView.leftOriginal();
    const edit = mergeView.editor();
    for ( const chunk of mergeView.leftChunks() ) {
        const addedLines = left.getRange(
            { line: chunk.origFrom, ch: 0 },
            { line: chunk.origTo, ch: 0 }
        );
        const removedLines = edit.getRange(
            { line: chunk.editFrom, ch: 0 },
            { line: chunk.editTo, ch: 0 }
        );
        toAdd.push(addedLines.trim());
        toRemove.push(removedLines.trim());
    }
    applyDiff(false, toAdd.join('\n'), toRemove.join('\n'));
}

/******************************************************************************/

function commitAllHandler() {
    const toAdd = [], toRemove = [];
    const left = mergeView.leftOriginal();
    const edit = mergeView.editor();
    for ( const chunk of mergeView.leftChunks() ) {
        const addedLines = edit.getRange(
            { line: chunk.editFrom, ch: 0 },
            { line: chunk.editTo, ch: 0 }
        );
        const removedLines = left.getRange(
            { line: chunk.origFrom, ch: 0 },
            { line: chunk.origTo, ch: 0 }
        );
        toAdd.push(addedLines.trim());
        toRemove.push(removedLines.trim());
    }
    applyDiff(true, toAdd.join('\n'), toRemove.join('\n'));
}

/******************************************************************************/

function editSaveHandler() {
    const editor = mergeView.editor();
    const editText = editor.getValue().trim();
    if ( editText === cleanEditText ) {
        onTextChanged(true);
        return;
    }
    const toAdd = [], toRemove = [];
    const diffs = getDiffer().diff_main(cleanEditText, editText);
    for ( const diff of diffs ) {
        if ( diff[0] === 1 ) {
            toAdd.push(diff[1]);
        } else if ( diff[0] === -1 ) {
            toRemove.push(diff[1]);
        }
    }
    applyDiff(false, toAdd.join(''), toRemove.join(''));
}

/******************************************************************************/

self.cloud.onPush = function() {
    return thePanes.orig.original.join('\n');
};

self.cloud.onPull = function(data, append) {
    if ( typeof data !== 'string' ) { return; }
    applyDiff(
        false,
        data,
        append ? '' : mergeView.editor().getValue().trim()
    );
};

/******************************************************************************/

self.wikilink = 'https://github.com/gorhill/uBlock/wiki/Dashboard:-My-rules';

self.hasUnsavedData = function() {
    return mergeView.editor().isClean(cleanEditToken) === false;
};

/******************************************************************************/

const presentationState = {
    sortType: 0,
    isCollapsed: false,
    filter: '',
};

const savePresentationState = ( ) => {
    vAPI.localStorage.setItem('dynaRulesPresentationState', presentationState);
};

vAPI.localStorage.getItemAsync('dynaRulesPresentationState').then(details => {
    if ( details instanceof Object === false ) { return; }
    if ( typeof details.sortType === 'number' ) {
        presentationState.sortType = details.sortType;
        qs$('#ruleFilter select').value = `${details.sortType}`;
    }
    if ( typeof details.isCollapsed === 'boolean' ) {
        presentationState.isCollapsed = details.isCollapsed;
        dom.cl.toggle('#ruleFilter #diffCollapse', 'active', details.isCollapsed);
    }
    if ( typeof details.filter === 'string' ) {
        presentationState.filter = details.filter;
        qs$('#ruleFilter input').value = details.filter;
        toggleOverlay();
    }
});

/******************************************************************************/

vAPI.messaging.send('dashboard', {
    what: 'getRules',
}).then(details => {
    thePanes.orig.original = details.permanentRules;
    thePanes.edit.original = details.sessionRules;
    publicSuffixList.fromSelfie(details.pslSelfie);
    onPresentationChanged(true);
});

// Handle user interaction
dom.on('#importButton', 'click', startImportFilePicker);
dom.on('#importFilePicker', 'change', handleImportFilePicker);
dom.on('#exportButton', 'click', exportUserRulesToFile);
dom.on('#revertButton', 'click', revertAllHandler);
dom.on('#commitButton', 'click', commitAllHandler);
dom.on('#editSaveButton', 'click', editSaveHandler);

// https://groups.google.com/forum/#!topic/codemirror/UQkTrt078Vs
mergeView.editor().on('updateDiff', ( ) => {
    onTextChanged();
});

/******************************************************************************/

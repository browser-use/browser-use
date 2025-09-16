// The following code is heavily based on the standard CodeMirror
// search addon found at: https://codemirror.net/addon/search/search.js
// I added/removed and modified code in order to get a closer match to a
// browser's built-in find-in-page feature which are just enough for
// uBlock Origin.
//
// This file was originally wholly imported from:
// https://github.com/codemirror/CodeMirror/blob/3e1bb5fff682f8f6cbfaef0e56c61d62403d4798/addon/search/search.js
//
// And has been modified over time to better suit uBO's usage and coding style:
// https://github.com/gorhill/uBlock/commits/master/src/js/codemirror/search.js
//
// The original copyright notice is reproduced below:

// =====
// CodeMirror, copyright (c) by Marijn Haverbeke and others
// Distributed under an MIT license: http://codemirror.net/LICENSE

// Define search commands. Depends on dialog.js or another
// implementation of the openDialog method.

// Replace works a little oddly -- it will do the replace on the next
// Ctrl-G (or whatever is bound to findNext) press. You prevent a
// replace by making sure the match is no longer selected when hitting
// Ctrl-G.
// =====

import { dom, qs$ } from '../dom.js';
import { i18n$ } from '../i18n.js';

{
    const CodeMirror = self.CodeMirror;

    CodeMirror.defineOption('maximizable', true, (cm, maximizable) => {
        if ( typeof maximizable !== 'boolean' ) { return; }
        const wrapper = cm.getWrapperElement();
        if ( wrapper === null ) { return; }
        const container = wrapper.closest('.codeMirrorContainer');
        if ( container === null ) { return; }
        container.dataset.maximizable = `${maximizable}`;
    });

    const searchOverlay = function(query, caseInsensitive) {
        if ( typeof query === 'string' )
            query = new RegExp(
                query.replace(/[-[\]/{}()*+?.\\^$|]/g, '\\$&'),
                caseInsensitive ? 'gi' : 'g'
            );
        else if ( !query.global )
            query = new RegExp(query.source, query.ignoreCase ? 'gi' : 'g');

        return {
            token: function(stream) {
                query.lastIndex = stream.pos;
                const match = query.exec(stream.string);
                if ( match && match.index === stream.pos ) {
                    stream.pos += match[0].length || 1;
                    return 'searching';
                } else if ( match ) {
                    stream.pos = match.index;
                } else {
                    stream.skipToEnd();
                }
            }
        };
    };

    const searchWidgetKeydownHandler = function(cm, ev) {
        const keyName = CodeMirror.keyName(ev);
        if ( !keyName ) { return; }
        CodeMirror.lookupKey(
            keyName,
            cm.getOption('keyMap'),
            function(command) {
                if ( widgetCommandHandler(cm, command) ) {
                    ev.preventDefault();
                    ev.stopPropagation();
                }
            }
        );
    };

    const searchWidgetInputHandler = function(cm, ev) {
        const state = getSearchState(cm);
        if ( ev.isTrusted !== true ) {
            if ( state.queryText === '' ) {
                clearSearch(cm);
            } else {
                cm.operation(function() {
                    startSearch(cm, state);
                });
            }
            return;
        }
        if ( queryTextFromSearchWidget(cm) === state.queryText ) { return; }
        state.queryTimer.offon(350);
    };

    const searchWidgetClickHandler = (ev, cm) => {
        if ( ev.button !== 0 ) { return; }
        const target = ev.target;
        const tcl = target.classList;
        if ( tcl.contains('cm-search-widget-up') ) {
            findNext(cm, -1);
        } else if ( tcl.contains('cm-search-widget-down') ) {
            findNext(cm, 1);
        } else if ( tcl.contains('cm-linter-widget-up') ) {
            findNextError(cm, -1);
        } else if ( tcl.contains('cm-linter-widget-down') ) {
            findNextError(cm, 1);
        } else if ( tcl.contains('cm-maximize') ) {
            const container = target.closest('.codeMirrorContainer');
            if ( container !== null ) {
                container.classList.toggle('cm-maximized');
            }
        }
        if ( target.localName !== 'input' ) {
            cm.focus();
        }
    };

    const queryTextFromSearchWidget = function(cm) {
        return getSearchState(cm).widget.querySelector('input[type="search"]').value;
    };

    const queryTextToSearchWidget = function(cm, q) {
        const input = getSearchState(cm).widget.querySelector('input[type="search"]');
        if ( typeof q === 'string' && q !== input.value ) {
            input.value = q;
        }
        input.setSelectionRange(0, input.value.length);
        input.focus();
    };

    const SearchState = function(cm) {
        this.query = null;
        this.panel = null;
        const widgetParent = document.querySelector('.cm-search-widget-template').cloneNode(true);
        this.widget = widgetParent.children[0];
        this.widget.addEventListener('keydown', searchWidgetKeydownHandler.bind(null, cm));
        this.widget.addEventListener('input', searchWidgetInputHandler.bind(null, cm));
        this.widget.addEventListener('click', ev => {
            searchWidgetClickHandler(ev, cm);
        });
        if ( typeof cm.addPanel === 'function' ) {
            this.panel = cm.addPanel(this.widget);
        }
        this.queryText = '';
        this.dirty = true;
        this.lines = [];
        cm.on('changes', (cm, changes) => {
            for ( const change of changes ) {
                if ( change.text.length !== 0 || change.removed !== 0 ) {
                    this.dirty = true;
                    break;
                }
            }
        });
        cm.on('cursorActivity', cm => {
            updateCount(cm);
        });
        this.queryTimer = vAPI.defer.create(( ) => {
            findCommit(cm, 0);
        });
    };

    // We want the search widget to behave as if the focus was on the
    // CodeMirror editor.

    const reSearchCommands = /^(?:find|findNext|findPrev|newlineAndIndent)$/;

    const widgetCommandHandler = function(cm, command) {
        if ( reSearchCommands.test(command) === false ) { return false; }
        const queryText = queryTextFromSearchWidget(cm);
        if ( command === 'find' ) {
            queryTextToSearchWidget(cm);
            return true;
        }
        if ( queryText.length !== 0 ) {
            findNext(cm, command === 'findPrev' ? -1 : 1);
        }
        return true;
    };

    const getSearchState = function(cm) {
        return cm.state.search || (cm.state.search = new SearchState(cm));
    };

    const queryCaseInsensitive = function(query) {
        return typeof query === 'string' && query === query.toLowerCase();
    };

    // Heuristic: if the query string is all lowercase, do a case insensitive search.
    const getSearchCursor = function(cm, query, pos) {
        return cm.getSearchCursor(
            query,
            pos,
            { caseFold: queryCaseInsensitive(query), multiline: false }
        );
    };

    // https://github.com/uBlockOrigin/uBlock-issues/issues/658
    //   Modified to backslash-escape ONLY widely-used control characters.
    const parseString = function(string) {
        return string.replace(/\\[nrt\\]/g, match => {
            if ( match === '\\n' ) { return '\n'; }
            if ( match === '\\r' ) { return '\r'; }
            if ( match === '\\t' ) { return '\t'; }
            if ( match === '\\\\' ) { return '\\'; }
            return match;
        });
    };

    const reEscape = /[.*+\-?^${}()|[\]\\]/g;

    // Must always return a RegExp object.
    //
    // Assume case-sensitivity if there is at least one uppercase in plain
    // query text.
    const parseQuery = function(query) {
        let flags = 'i';
        let reParsed = query.match(/^\/(.+)\/([iu]*)$/);
        if ( reParsed !== null ) {
            try {
                const re = new RegExp(reParsed[1], reParsed[2]);
                query = re.source;
                flags = re.flags;
            }
            catch {
                reParsed = null;
            }
        }
        if ( reParsed === null ) {
            if ( /[A-Z]/.test(query) ) { flags = ''; }
            query = parseString(query).replace(reEscape, '\\$&');
        }
        if ( typeof query === 'string' ? query === '' : query.test('') ) {
            query = 'x^';
        }
        return new RegExp(query, 'gm' + flags);
    };

    let intlNumberFormat;

    const formatNumber = function(n) {
        if ( intlNumberFormat === undefined ) {
            intlNumberFormat = null;
            if ( Intl.NumberFormat instanceof Function ) {
                const intl = new Intl.NumberFormat(undefined, {
                    notation: 'compact',
                    maximumSignificantDigits: 3
                });
                if ( intl.resolvedOptions().notation ) {
                    intlNumberFormat = intl;
                }
            }
        }
        return n > 10000 && intlNumberFormat instanceof Object
            ? intlNumberFormat.format(n)
            : n.toLocaleString();
    };

    const updateCount = function(cm) {
        const state = getSearchState(cm);
        const lines = state.lines;
        const current = cm.getCursor().line;
        let l = 0;
        let r = lines.length;
        let i = -1;
        while ( l < r ) {
            i = l + r >>> 1;
            const candidate = lines[i];
            if ( current === candidate ) { break; }
            if ( current < candidate ) {
                r = i;
            } else /* if ( current > candidate ) */ {
                l = i + 1;
            }
        }
        let text = '';
        if ( i !== -1 ) {
            text = formatNumber(i + 1);
            if ( lines[i] !== current ) {
                text = '~' + text;
            }
            text = text + '\xA0/\xA0';
        }
        const count = lines.length;
        text += formatNumber(count);
        const span = state.widget.querySelector('.cm-search-widget-count');
        span.textContent = text;
        span.title = count.toLocaleString();
    };

    const startSearch = function(cm, state) {
        state.query = parseQuery(state.queryText);
        if ( state.overlay !== undefined ) {
            cm.removeOverlay(state.overlay, queryCaseInsensitive(state.query));
        }
        state.overlay = searchOverlay(state.query, queryCaseInsensitive(state.query));
        cm.addOverlay(state.overlay);
        if ( state.dirty || self.searchThread.needHaystack() ) {
            self.searchThread.setHaystack(cm.getValue());
            state.dirty = false;
        }
        self.searchThread.search(state.query).then(lines => {
            if ( Array.isArray(lines) === false ) { return; }
            state.lines = lines;
            const count = lines.length;
            updateCount(cm);
            if ( state.annotate !== undefined ) {
                state.annotate.clear();
                state.annotate = undefined;
            }
            if ( count === 0 ) { return; }
            state.annotate = cm.annotateScrollbar('CodeMirror-search-match');
            const annotations = [];
            let lineBeg = -1;
            let lineEnd = -1;
            for ( const line of lines ) {
                if ( lineBeg === -1 ) {
                    lineBeg = line;
                    lineEnd = line + 1;
                    continue;
                } else if ( line === lineEnd ) {
                    lineEnd = line + 1;
                    continue;
                }
                annotations.push({
                    from: { line: lineBeg, ch: 0 },
                    to: { line: lineEnd, ch: 0 }
                });
                lineBeg = -1;
            }
            if ( lineBeg !== -1 ) {
                annotations.push({
                    from: { line: lineBeg, ch: 0 },
                    to: { line: lineEnd, ch: 0 }
                });
            }
            state.annotate.update(annotations);
        });
        state.widget.setAttribute('data-query', state.queryText);
    };

    const findNext = function(cm, dir, callback) {
        cm.operation(function() {
            const state = getSearchState(cm);
            if ( !state.query ) { return; }
            let cursor = getSearchCursor(
                cm,
                state.query,
                dir <= 0 ? cm.getCursor('from') : cm.getCursor('to')
            );
            const previous = dir < 0;
            if (!cursor.find(previous)) {
                cursor = getSearchCursor(
                    cm,
                    state.query,
                    previous
                        ? CodeMirror.Pos(cm.lastLine())
                        : CodeMirror.Pos(cm.firstLine(), 0)
                );
                if (!cursor.find(previous)) return;
            }
            cm.setSelection(cursor.from(), cursor.to());
            const { clientHeight } = cm.getScrollInfo();
            cm.scrollIntoView(
                { from: cursor.from(), to: cursor.to() },
                clientHeight >>> 1
            );
            if (callback) callback(cursor.from(), cursor.to());
        });
    };

    const findNextError = function(cm, dir) {
        const doc = cm.getDoc();
        const cursor = cm.getCursor('from');
        const cursorLine = cursor.line;
        const start = dir < 0 ? 0 : cursorLine + 1;
        const end = dir < 0 ? cursorLine : doc.lineCount();
        let found = -1;
        doc.eachLine(start, end, lineHandle => {
            const markers = lineHandle.gutterMarkers || null;
            if ( markers === null ) { return; }
            const marker = markers['CodeMirror-lintgutter'];
            if ( marker === undefined ) { return; }
            if ( marker.dataset.error !== 'y' ) { return; }
            const line = lineHandle.lineNo();
            if ( dir < 0 ) {
                found = line;
                return;
            }
            found = line;
            return true;
        });
        if ( found === -1 || found === cursorLine ) { return; }
        cm.getDoc().setCursor(found);
        const { clientHeight } = cm.getScrollInfo();
        cm.scrollIntoView({ line: found, ch: 0 }, clientHeight >>> 1);
    };

    const clearSearch = function(cm, hard) {
        cm.operation(function() {
            const state = getSearchState(cm);
            if ( state.query ) {
                state.query = state.queryText = null;
            }
            state.lines = [];
            if ( state.overlay !== undefined ) {
                cm.removeOverlay(state.overlay);
                state.overlay = undefined;
            }
            if ( state.annotate ) {
                state.annotate.clear();
                state.annotate = undefined;
            }
            state.widget.removeAttribute('data-query');
            if ( hard ) {
                state.panel.clear();
                state.panel = null;
                state.widget = null;
                cm.state.search = null;
            }
        });
    };

    const findCommit = function(cm, dir) {
        const state = getSearchState(cm);
        state.queryTimer.off();
        const queryText = queryTextFromSearchWidget(cm);
        if ( queryText === state.queryText ) { return; }
        state.queryText = queryText;
        if ( state.queryText === '' ) {
            clearSearch(cm);
        } else {
            cm.operation(function() {
                startSearch(cm, state);
                findNext(cm, dir);
            });
        }
    };

    const findCommand = function(cm) {
        let queryText = cm.getSelection() || undefined;
        if ( !queryText ) {
            const word = cm.findWordAt(cm.getCursor());
            queryText = cm.getRange(word.anchor, word.head);
            if ( /^\W|\W$/.test(queryText) ) {
                queryText = undefined;
            }
            cm.setCursor(word.anchor);
        }
        queryTextToSearchWidget(cm, queryText);
        findCommit(cm, 1);
    };

    const findNextCommand = function(cm) {
        const state = getSearchState(cm);
        if ( state.query ) { return findNext(cm, 1); }
    };

    const findPrevCommand = function(cm) {
        const state = getSearchState(cm);
        if ( state.query ) { return findNext(cm, -1); }
    };

    {
        const searchWidgetTemplate = [
            '<div class="cm-search-widget-template" style="display:none;">',
              '<div class="cm-search-widget">',
                '<span class="cm-maximize"><svg viewBox="0 0 40 40"><path d="M4,16V4h12M24,4H36V16M4,24V36H16M36,24V36H24" /><path d="M14 2.5v12h-12M38 14h-12v-12M14 38v-12h-12M26 38v-12h12" /></svg></span>&ensp;',
                '<span class="cm-search-widget-input">',
                    '<span class="searchfield">',
                        '<input type="search" spellcheck="false" placeholder="">',
                        '<span class="fa-icon">search</span>',
                    '</span>&ensp;',
                  '<span class="cm-search-widget-up cm-search-widget-button fa-icon">angle-up</span>&nbsp;',
                  '<span class="cm-search-widget-down cm-search-widget-button fa-icon fa-icon-vflipped">angle-up</span>&ensp;',
                  '<span class="cm-search-widget-count"></span>',
                '</span>',
                '<span class="cm-linter-widget" data-lint="0">',
                  '<span class="cm-linter-widget-count"></span>&ensp;',
                  '<span class="cm-linter-widget-up cm-search-widget-button fa-icon">angle-up</span>&nbsp;',
                  '<span class="cm-linter-widget-down cm-search-widget-button fa-icon fa-icon-vflipped">angle-up</span>&ensp;',
                '</span>',
                '<span>',
                    '<a class="fa-icon sourceURL" href>external-link</a>',
                '</span>',
              '</div>',
            '</div>',
        ].join('\n');
        const domParser = new DOMParser();
        const doc = domParser.parseFromString(searchWidgetTemplate, 'text/html');
        const widgetTemplate = document.adoptNode(doc.body.firstElementChild);
        document.body.appendChild(widgetTemplate);
    }

    CodeMirror.commands.find = findCommand;
    CodeMirror.commands.findNext = findNextCommand;
    CodeMirror.commands.findPrev = findPrevCommand;

    CodeMirror.defineInitHook(function(cm) {
        getSearchState(cm);
        cm.on('linterDone', details => {
            const linterWidget = qs$('.cm-linter-widget');
            const count = details.errorCount;
            if ( linterWidget.dataset.lint === `${count}` ) { return; }
            linterWidget.dataset.lint = `${count}`;
            dom.text(
                qs$(linterWidget, '.cm-linter-widget-count'),
                i18n$('linterMainReport').replace('{{count}}', count.toLocaleString())
            );
        });
    });
}

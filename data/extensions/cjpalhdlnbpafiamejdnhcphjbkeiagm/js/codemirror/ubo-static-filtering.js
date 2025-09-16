/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2018-present Raymond Hill

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

/* global CodeMirror */

/******************************************************************************/

import * as sfp from '../static-filtering-parser.js';
import { dom, qs$ } from '../dom.js';
import { tokenizableStrFromRegex } from '../regex-analyzer.js';

/******************************************************************************/

const redirectNames = new Map();
const scriptletNames = new Map();
const preparseDirectiveEnv = [];
const preparseDirectiveHints = [];
const originHints = [];
let hintHelperRegistered = false;

/******************************************************************************/

CodeMirror.defineOption('trustedSource', false, (cm, trusted) => {
    if ( typeof trusted !== 'boolean' ) { return; }
    self.dispatchEvent(new CustomEvent('trustedSource', {
        detail: { cm, trusted },
    }));
});

CodeMirror.defineOption('trustedScriptletTokens', undefined, (cm, tokens) => {
    if ( tokens === undefined || tokens === null ) { return; }
    if ( typeof tokens[Symbol.iterator] !== 'function' ) { return; }
    self.dispatchEvent(new CustomEvent('trustedScriptletTokens', {
        detail: new Set(tokens),
    }));
});

/******************************************************************************/

const uBOStaticFilteringMode = (( ) => {
    const redirectTokenStyle = (mode, node) => {
        const rawToken = mode.astParser.getNodeString(node || mode.currentWalkerNode);
        const { token } = sfp.parseRedirectValue(rawToken);
        return redirectNames.has(token) ? 'value' : 'value warning';
    };

    const nodeHasError = (mode, node) => {
        return mode.astParser.getNodeFlags(
            node || mode.currentWalkerNode, sfp.NODE_FLAG_ERROR
        ) !== 0;
    };

    const reGoodRegexToken = /[^\x01%0-9A-Za-z][%0-9A-Za-z]{7,}|[^\x01%0-9A-Za-z][%0-9A-Za-z]{1,6}[^\x01%0-9A-Za-z]/;

    const colorFromAstNode = mode => {
        if ( mode.astParser.nodeIsEmptyString(mode.currentWalkerNode) ) { return '+'; }
        if ( nodeHasError(mode) ) { return 'error'; }
        const nodeType = mode.astParser.getNodeType(mode.currentWalkerNode);
        switch ( nodeType ) {
        case sfp.NODE_TYPE_WHITESPACE:
            return '';
        case sfp.NODE_TYPE_COMMENT:
            if ( mode.astWalker.canGoDown() ) { break; }
            return 'comment';
        case sfp.NODE_TYPE_COMMENT_URL:
            return 'comment link';
        case sfp.NODE_TYPE_IGNORE:
            return 'comment';
        case sfp.NODE_TYPE_PREPARSE_DIRECTIVE:
        case sfp.NODE_TYPE_PREPARSE_DIRECTIVE_VALUE:
            return 'directive';
        case sfp.NODE_TYPE_PREPARSE_DIRECTIVE_IF_VALUE: {
            const raw = mode.astParser.getNodeString(mode.currentWalkerNode);
            const state = sfp.utils.preparser.evaluateExpr(raw, preparseDirectiveEnv);
            return state ? 'positive strong' : 'negative strong';
        }
        case sfp.NODE_TYPE_EXT_OPTIONS_ANCHOR:
            return mode.astParser.getFlags(sfp.AST_FLAG_IS_EXCEPTION)
                ? 'tag strong'
                : 'def strong';
        case sfp.NODE_TYPE_EXT_DECORATION:
            return 'def';
        case sfp.NODE_TYPE_EXT_PATTERN_RAW:
            if ( mode.astWalker.canGoDown() ) { break; }
            return 'variable';
        case sfp.NODE_TYPE_EXT_PATTERN_COSMETIC:
        case sfp.NODE_TYPE_EXT_PATTERN_HTML:
            return 'variable';
        case sfp.NODE_TYPE_EXT_PATTERN_RESPONSEHEADER:
        case sfp.NODE_TYPE_EXT_PATTERN_SCRIPTLET:
            if ( mode.astWalker.canGoDown() ) { break; }
            return 'variable';
        case sfp.NODE_TYPE_EXT_PATTERN_SCRIPTLET_TOKEN: {
            const token = mode.astParser.getNodeString(mode.currentWalkerNode);
            if ( scriptletNames.has(token) === false ) {
                return 'warning';
            }
            return 'variable';
        }
        case sfp.NODE_TYPE_EXT_PATTERN_SCRIPTLET_ARG:
            return 'variable';
        case sfp.NODE_TYPE_NET_EXCEPTION:
            return 'tag strong';
        case sfp.NODE_TYPE_NET_PATTERN:
            if ( mode.astWalker.canGoDown() ) { break; }
            if ( mode.astParser.isRegexPattern() ) {
                const s = mode.astParser.getNodeString(mode.currentWalkerNode);
                const tokenizable = tokenizableStrFromRegex(s);
                if ( reGoodRegexToken.test(tokenizable) === false ) {
                    return 'variable warning';
                }
                return 'variable notice';
            }
            return 'variable';
        case sfp.NODE_TYPE_NET_PATTERN_PART:
            return 'variable';
        case sfp.NODE_TYPE_NET_PATTERN_PART_SPECIAL:
            return 'keyword strong';
        case sfp.NODE_TYPE_NET_PATTERN_PART_UNICODE:
            return 'variable unicode';
        case sfp.NODE_TYPE_NET_PATTERN_LEFT_HNANCHOR:
        case sfp.NODE_TYPE_NET_PATTERN_LEFT_ANCHOR:
        case sfp.NODE_TYPE_NET_PATTERN_RIGHT_ANCHOR:
        case sfp.NODE_TYPE_NET_OPTION_NAME_NOT:
            return 'keyword strong';
        case sfp.NODE_TYPE_NET_OPTIONS_ANCHOR:
        case sfp.NODE_TYPE_NET_OPTION_SEPARATOR:
            mode.lastNetOptionType = 0;
            return 'def strong';
        case sfp.NODE_TYPE_NET_OPTION_NAME_UNKNOWN:
            mode.lastNetOptionType = 0;
            return 'error';
        case sfp.NODE_TYPE_NET_OPTION_NAME_1P:
        case sfp.NODE_TYPE_NET_OPTION_NAME_STRICT1P:
        case sfp.NODE_TYPE_NET_OPTION_NAME_3P:
        case sfp.NODE_TYPE_NET_OPTION_NAME_STRICT3P:
        case sfp.NODE_TYPE_NET_OPTION_NAME_ALL:
        case sfp.NODE_TYPE_NET_OPTION_NAME_BADFILTER:
        case sfp.NODE_TYPE_NET_OPTION_NAME_CNAME:
        case sfp.NODE_TYPE_NET_OPTION_NAME_CSP:
        case sfp.NODE_TYPE_NET_OPTION_NAME_CSS:
        case sfp.NODE_TYPE_NET_OPTION_NAME_DENYALLOW:
        case sfp.NODE_TYPE_NET_OPTION_NAME_DOC:
        case sfp.NODE_TYPE_NET_OPTION_NAME_EHIDE:
        case sfp.NODE_TYPE_NET_OPTION_NAME_EMPTY:
        case sfp.NODE_TYPE_NET_OPTION_NAME_FONT:
        case sfp.NODE_TYPE_NET_OPTION_NAME_FRAME:
        case sfp.NODE_TYPE_NET_OPTION_NAME_FROM:
        case sfp.NODE_TYPE_NET_OPTION_NAME_GENERICBLOCK:
        case sfp.NODE_TYPE_NET_OPTION_NAME_GHIDE:
        case sfp.NODE_TYPE_NET_OPTION_NAME_HEADER:
        case sfp.NODE_TYPE_NET_OPTION_NAME_IMAGE:
        case sfp.NODE_TYPE_NET_OPTION_NAME_IMPORTANT:
        case sfp.NODE_TYPE_NET_OPTION_NAME_INLINEFONT:
        case sfp.NODE_TYPE_NET_OPTION_NAME_INLINESCRIPT:
        case sfp.NODE_TYPE_NET_OPTION_NAME_MATCHCASE:
        case sfp.NODE_TYPE_NET_OPTION_NAME_MEDIA:
        case sfp.NODE_TYPE_NET_OPTION_NAME_METHOD:
        case sfp.NODE_TYPE_NET_OPTION_NAME_MP4:
        case sfp.NODE_TYPE_NET_OPTION_NAME_NOOP:
        case sfp.NODE_TYPE_NET_OPTION_NAME_OBJECT:
        case sfp.NODE_TYPE_NET_OPTION_NAME_OTHER:
        case sfp.NODE_TYPE_NET_OPTION_NAME_PING:
        case sfp.NODE_TYPE_NET_OPTION_NAME_POPUNDER:
        case sfp.NODE_TYPE_NET_OPTION_NAME_POPUP:
        case sfp.NODE_TYPE_NET_OPTION_NAME_REDIRECT:
        case sfp.NODE_TYPE_NET_OPTION_NAME_REDIRECTRULE:
        case sfp.NODE_TYPE_NET_OPTION_NAME_REMOVEPARAM:
        case sfp.NODE_TYPE_NET_OPTION_NAME_SCRIPT:
        case sfp.NODE_TYPE_NET_OPTION_NAME_SHIDE:
        case sfp.NODE_TYPE_NET_OPTION_NAME_TO:
        case sfp.NODE_TYPE_NET_OPTION_NAME_URLTRANSFORM:
        case sfp.NODE_TYPE_NET_OPTION_NAME_XHR:
        case sfp.NODE_TYPE_NET_OPTION_NAME_WEBRTC:
        case sfp.NODE_TYPE_NET_OPTION_NAME_WEBSOCKET:
            mode.lastNetOptionType = nodeType;
            return 'def';
        case sfp.NODE_TYPE_NET_OPTION_ASSIGN:
        case sfp.NODE_TYPE_NET_OPTION_QUOTE:
            return 'def';
        case sfp.NODE_TYPE_NET_OPTION_VALUE:
            if ( mode.astWalker.canGoDown() ) { break; }
            switch ( mode.lastNetOptionType ) {
            case sfp.NODE_TYPE_NET_OPTION_NAME_REDIRECT:
            case sfp.NODE_TYPE_NET_OPTION_NAME_REDIRECTRULE:
                return redirectTokenStyle(mode);
            default:
                break;
            }
            return 'value';
        case sfp.NODE_TYPE_OPTION_VALUE_NOT:
            return 'keyword strong';
        case sfp.NODE_TYPE_OPTION_VALUE_DOMAIN:
            return 'value';
        case sfp.NODE_TYPE_OPTION_VALUE_SEPARATOR:
            return 'def';
        default:
            break;
        }
        return '+';
    };

    class ModeState {
        constructor() {
            this.astParser = new sfp.AstFilterParser({
                interactive: true,
                nativeCssHas: vAPI.webextFlavor.env.includes('native_css_has'),
            });
            this.astWalker = this.astParser.getWalker();
            this.currentWalkerNode = 0;
            this.lastNetOptionType = 0;
            self.addEventListener('trustedSource', ev => {
                const { trusted } = ev.detail;
                this.astParser.options.trustedSource = trusted;
            });
            self.addEventListener('trustedScriptletTokens', ev => {
                this.astParser.options.trustedScriptletTokens = ev.detail;
            });
        }
    }

    return {
        state: null,
        startState() {
            if ( this.state === null ) {
                this.state = new ModeState();
            }
            return this.state;
        },
        copyState(other) {
            return other;
        },
        token(stream, state) {
            if ( stream.sol() ) {
                state.astParser.parse(stream.string);
                if ( state.astParser.getFlags(sfp.AST_FLAG_UNSUPPORTED) !== 0 ) {
                    stream.skipToEnd();
                    return 'error';
                }
                if ( state.astParser.getType() === sfp.AST_TYPE_NONE ) {
                    stream.skipToEnd();
                    return 'comment';
                }
                state.currentWalkerNode = state.astWalker.reset();
            } else if ( nodeHasError(state) ) {
                state.currentWalkerNode = state.astWalker.right();
            } else {
                state.currentWalkerNode = state.astWalker.next();
            }
            let style = '';
            while ( state.currentWalkerNode !== 0 ) {
                style = colorFromAstNode(state, stream);
                if ( style !== '+' ) { break; }
                state.currentWalkerNode = state.astWalker.next();
            }
            if ( style === '+' ) {
                stream.skipToEnd();
                return null;
            }
            stream.pos = state.astParser.getNodeStringEnd(state.currentWalkerNode);
            if ( state.astParser.isNetworkFilter() ) {
                return style ? `line-cm-net ${style}` : 'line-cm-net';
            }
            if ( state.astParser.isExtendedFilter() ) {
                let flavor = '';
                if ( state.astParser.isCosmeticFilter() ) {
                    flavor = 'line-cm-ext-dom';
                } else if ( state.astParser.isScriptletFilter() ) {
                    flavor = 'line-cm-ext-js';
                } else if ( state.astParser.isHtmlFilter() ) {
                    flavor = 'line-cm-ext-html';
                }
                if ( flavor !== '' ) {
                    style = `${flavor} ${style}`;
                }
            }
            style = style.trim();
            return style !== '' ? style : null;
        },
        lineComment: '!',
    };
})();

CodeMirror.defineMode('ubo-static-filtering', ( ) => uBOStaticFilteringMode);

/******************************************************************************/

// Following code is for auto-completion. Reference:
//   https://codemirror.net/demo/complete.html

CodeMirror.defineOption('uboHints', null, (cm, hints) => {
    if ( hints instanceof Object === false ) { return; }
    if ( Array.isArray(hints.redirectResources) ) {
        for ( const [ name, desc ] of hints.redirectResources ) {
            const displayText = desc.aliasOf !== ''
                ? `${name} (${desc.aliasOf})`
                : '';
            if ( desc.canRedirect ) {
                redirectNames.set(name, displayText);
            }
            if ( desc.canInject && name.endsWith('.js') ) {
                scriptletNames.set(name.slice(0, -3), displayText);
            }
        }
    }
    if ( Array.isArray(hints.preparseDirectiveEnv)) {
        preparseDirectiveEnv.length = 0;
        preparseDirectiveEnv.push(...hints.preparseDirectiveEnv);
    }
    if ( Array.isArray(hints.preparseDirectiveHints)) {
        preparseDirectiveHints.push(...hints.preparseDirectiveHints);
    }
    if ( Array.isArray(hints.originHints) ) {
        originHints.length = 0;
        for ( const hint of hints.originHints ) {
            originHints.push(hint);
        }
    }
    if ( hintHelperRegistered ) { return; }
    hintHelperRegistered = true;
    initHints();
});

function initHints() {
    const astParser = new sfp.AstFilterParser({
        interactive: true,
        nativeCssHas: vAPI.webextFlavor.env.includes('native_css_has'),
    });
    const proceduralOperatorNames = new Map(
        Array.from(sfp.proceduralOperatorTokens)
            .filter(item => (item[1] & 0b01) !== 0)
    );
    const excludedHints = new Set([
        'genericblock',
        'object-subrequest',
        'rewrite',
        'webrtc',
    ]);

    const pickBestHints = function(cursor, seedLeft, seedRight, hints) {
        const seed = (seedLeft + seedRight).trim();
        const out = [];
        // First, compare against whole seed
        for ( const hint of hints ) {
            const text = hint instanceof Object
                ? hint.displayText || hint.text
                : hint;
            if ( text.startsWith(seed) === false ) { continue; }
            out.push(hint);
        }
        if ( out.length !== 0 ) {
            return {
                from: { line: cursor.line, ch: cursor.ch - seedLeft.length },
                to: { line: cursor.line, ch: cursor.ch + seedRight.length },
                list: out,
            };
        }
        // If no match, try again with a different heuristic: valid hints are
        // those matching left seed, not matching right seed but right seed is
        // found to be a valid hint. This is to take care of cases like:
        //
        //     *$script,redomain=example.org
        //                ^
        //                + cursor position
        //
        // In such case, [ redirect=, redirect-rule= ] should be returned
        // as valid hints.
        for ( const hint of hints ) {
            const text = hint instanceof Object
                ? hint.displayText || hint.text
                : hint;
            if ( seedLeft.length === 0 ) { continue; }
            if ( text.startsWith(seedLeft) === false ) { continue; }
            if ( hints.includes(seedRight) === false ) { continue; }
            out.push(hint);
        }
        if ( out.length !== 0 ) {
            return {
                from: { line: cursor.line, ch: cursor.ch - seedLeft.length },
                to: { line: cursor.line, ch: cursor.ch },
                list: out,
            };
        }
        // If no match, try again with a different heuristic: valid hints are
        // those containing seed as a substring. This is to take care of cases
        // like:
        //
        //     *$script,redirect=gif
        //                       ^
        //                       + cursor position
        //
        // In such case, [ 1x1.gif, 1x1-transparent.gif ] should be returned
        // as valid hints.
        for ( const hint of hints ) {
            const text = hint instanceof Object
                ? hint.displayText || hint.text
                : hint;
            if ( seedLeft.length === 1 ) {
                if ( text.startsWith(seedLeft) === false ) { continue; }
            } else if ( text.includes(seed) === false ) { continue; }
            out.push(hint);
        }
        if ( out.length !== 0 ) {
            return {
                from: { line: cursor.line, ch: cursor.ch - seedLeft.length },
                to: { line: cursor.line, ch: cursor.ch + seedRight.length },
                list: out,
            };
        }
        // If still no match, try again with a different heuristic: valid hints
        // are those containing left seed as a substring. This is to take care
        // of cases like:
        //
        //     *$script,redirect=gifdomain=example.org
        //                          ^
        //                          + cursor position
        //
        // In such case, [ 1x1.gif, 1x1-transparent.gif ] should be returned
        // as valid hints.
        for ( const hint of hints ) {
            const text = hint instanceof Object
                ? hint.displayText || hint.text
                : hint;
            if ( text.includes(seedLeft) === false ) { continue; }
            out.push(hint);
        }
        if ( out.length !== 0 ) {
            return {
                from: { line: cursor.line, ch: cursor.ch - seedLeft.length },
                to: { line: cursor.line, ch: cursor.ch },
                list: out,
            };
        }
    };

    const getOriginHints = function(cursor, line, suffix = '') {
        const beg = cursor.ch;
        const matchLeft = /[^,|=~]*$/.exec(line.slice(0, beg));
        const matchRight = /^[^#,|]*/.exec(line.slice(beg));
        if ( matchLeft === null || matchRight === null ) { return; }
        const hints = [];
        for ( const text of originHints ) {
            hints.push(text + suffix);
        }
        return pickBestHints(cursor, matchLeft[0], matchRight[0], hints);
    };

    const getNetPatternHints = function(cursor, line) {
        if ( /\|\|[\w.-]*$/.test(line.slice(0, cursor.ch)) ) {
            return getOriginHints(cursor, line, '^');
        }
        // Maybe a static extended filter is meant to be crafted.
        if ( /[^\w\x80-\xF4#,.-]/.test(line) === false ) {
            return getOriginHints(cursor, line);
        }
    };

    const getNetOptionHints = function(cursor, seedLeft, seedRight) {
        const isNegated = seedLeft.startsWith('~');
        if ( isNegated ) {
            seedLeft = seedLeft.slice(1);
        }
        const assignPos = seedRight.indexOf('=');
        if ( assignPos !== -1 ) { seedRight = seedRight.slice(0, assignPos); }
        const isException = astParser.isException();
        const hints = [];
        for ( let [ text, desc ] of sfp.netOptionTokenDescriptors ) {
            if ( excludedHints.has(text) ) { continue; }
            if ( isNegated && desc.canNegate !== true ) { continue; }
            if ( isException ) {
                if ( desc.blockOnly ) { continue; }
            } else {
                if ( desc.allowOnly ) { continue; }
                if ( (assignPos === -1) && desc.mustAssign ) {
                    text += '=';
                }
            }
            hints.push(text);
        }
        return pickBestHints(cursor, seedLeft, seedRight, hints);
    };

    const getNetRedirectHints = function(cursor, seedLeft, seedRight) {
        const hints = [];
        for ( const text of redirectNames.keys() ) {
            if ( text.startsWith('abp-resource:') ) { continue; }
            hints.push(text);
        }
        return pickBestHints(cursor, seedLeft, seedRight, hints);
    };

    const getNetHints = function(cursor, line) {
        const patternNode = astParser.getBranchFromType(sfp.NODE_TYPE_NET_PATTERN_RAW);
        if ( patternNode === 0 ) { return; }
        const patternEnd = astParser.getNodeStringEnd(patternNode);
        const beg = cursor.ch;
        if ( beg <= patternEnd ) {
            return getNetPatternHints(cursor, line);
        }
        const lineBefore = line.slice(0, beg);
        const lineAfter = line.slice(beg);
        let matchLeft = /[^$,]*$/.exec(lineBefore);
        let matchRight = /^[^,]*/.exec(lineAfter);
        if ( matchLeft === null || matchRight === null ) { return; }
        const assignPos = matchLeft[0].indexOf('=');
        if ( assignPos === -1 ) {
            return getNetOptionHints(cursor, matchLeft[0], matchRight[0]);
        }
        if ( /^(redirect(-rule)?|rewrite)=/.test(matchLeft[0]) ) {
            return getNetRedirectHints(
                cursor,
                matchLeft[0].slice(assignPos + 1),
                matchRight[0]
            );
        }
        if ( /^(domain|from)=/.test(matchLeft[0]) ) {
            return getOriginHints(cursor, line);
        }
    };

    const getExtSelectorHints = function(cursor, line) {
        const beg = cursor.ch;
        // Special selector case: `^responseheader`
        {
            const match = /#\^([a-z]+)$/.exec(line.slice(0, beg));
            if (
                match !== null &&
                'responseheader'.startsWith(match[1]) &&
                line.slice(beg) === ''
            ) {
                return pickBestHints(
                    cursor,
                    match[1],
                    '',
                    [ 'responseheader()' ]
                );
            }
        }
        // Procedural operators
        const matchLeft = /#\^?.*:([^:]*)$/.exec(line.slice(0, beg));
        const matchRight = /^([a-z-]*)\(?/.exec(line.slice(beg));
        if ( matchLeft === null || matchRight === null ) { return; }
        const isStaticDOM = matchLeft[0].indexOf('^') !== -1;
        const hints = [];
        for ( let [ text, bits ] of proceduralOperatorNames ) {
            if ( isStaticDOM && (bits & 0b10) !== 0 ) { continue; }
            hints.push(text);
        }
        return pickBestHints(cursor, matchLeft[1], matchRight[1], hints);
    };

    const getExtHeaderHints = function(cursor, line) {
        const beg = cursor.ch;
        const matchLeft = /#\^responseheader\((.*)$/.exec(line.slice(0, beg));
        const matchRight = /^([^)]*)/.exec(line.slice(beg));
        if ( matchLeft === null || matchRight === null ) { return; }
        const hints = [];
        for ( const hint of sfp.removableHTTPHeaders ) {
            hints.push(hint);
        }
        return pickBestHints(cursor, matchLeft[1], matchRight[1], hints);
    };

    const getExtScriptletHints = function(cursor, line) {
        const beg = cursor.ch;
        const matchLeft = /#\+js\(([^,]*)$/.exec(line.slice(0, beg));
        const matchRight = /^([^,)]*)/.exec(line.slice(beg));
        if ( matchLeft === null || matchRight === null ) { return; }
        const hints = [];
        for ( const [ text, displayText ] of scriptletNames ) {
            const hint = { text };
            if ( displayText !== '' ) {
                hint.displayText = displayText;
            }
            hints.push(hint);
        }
        return pickBestHints(cursor, matchLeft[1], matchRight[1], hints);
    };

    const getCommentHints = function(cursor, line) {
        const beg = cursor.ch;
        if ( line.startsWith('!#if ') ) {
            const matchLeft = /^!#if !?(\w*)$/.exec(line.slice(0, beg));
            const matchRight = /^\w*/.exec(line.slice(beg));
            if ( matchLeft === null || matchRight === null ) { return; }
            return pickBestHints(
                cursor,
                matchLeft[1],
                matchRight[0],
                preparseDirectiveHints
            );
        }
        if ( line.startsWith('!#') && line !== '!#endif' ) {
            const matchLeft = /^!#(\w*)$/.exec(line.slice(0, beg));
            const matchRight = /^\w*/.exec(line.slice(beg));
            if ( matchLeft === null || matchRight === null ) { return; }
            const hints = [ 'if ', 'endif\n', 'include ' ];
            return pickBestHints(cursor, matchLeft[1], matchRight[0], hints);
        }
    };

    CodeMirror.registerHelper('hint', 'ubo-static-filtering', function(cm) {
        const cursor = cm.getCursor();
        const line = cm.getLine(cursor.line);
        astParser.parse(line);
        if ( astParser.isExtendedFilter() ) {
            const anchorNode = astParser.getBranchFromType(sfp.NODE_TYPE_EXT_OPTIONS_ANCHOR);
            if ( anchorNode === 0 ) { return; }
            let hints;
            if ( cursor.ch <= astParser.getNodeStringBeg(anchorNode) ) {
                hints = getOriginHints(cursor, line);
            } else if ( astParser.isScriptletFilter() ) {
                hints = getExtScriptletHints(cursor, line);
            } else if ( astParser.isResponseheaderFilter() ) {
                hints = getExtHeaderHints(cursor, line);
            } else {
                hints = getExtSelectorHints(cursor, line);
            }
            return hints;
        }
        if ( astParser.isNetworkFilter() ) {
            return getNetHints(cursor, line);
        }
        if ( astParser.isComment() ) {
            return getCommentHints(cursor, line);
        }
        return getOriginHints(cursor, line);
    });
}

/******************************************************************************/

CodeMirror.registerHelper('fold', 'ubo-static-filtering', (( ) => {
    const foldIfEndif = function(startLineNo, startLine, cm) {
        const lastLineNo = cm.lastLine();
        let endLineNo = startLineNo;
        let depth = 1;
        while ( endLineNo < lastLineNo ) {
            endLineNo += 1;
            const line = cm.getLine(endLineNo);
            if ( line.startsWith('!#endif') ) {
                depth -= 1;
                if ( depth === 0 ) {
                    return {
                        from: CodeMirror.Pos(startLineNo, startLine.length),
                        to: CodeMirror.Pos(endLineNo, 0)
                    };
                }
            }
            if ( line.startsWith('!#if') ) {
                depth += 1;
            }
        }
    };

    const foldInclude = function(startLineNo, startLine, cm) {
        const lastLineNo = cm.lastLine();
        let endLineNo = startLineNo + 1;
        if ( endLineNo >= lastLineNo ) { return; }
        if ( cm.getLine(endLineNo).startsWith('! >>>>>>>> ') === false ) {
            return;
        }
        while ( endLineNo < lastLineNo ) {
            endLineNo += 1;
            const line = cm.getLine(endLineNo);
            if ( line.startsWith('! <<<<<<<< ') ) {
                return {
                    from: CodeMirror.Pos(startLineNo, startLine.length),
                    to: CodeMirror.Pos(endLineNo, line.length)
                };
            }
        }
    };

    return function(cm, start) {
        const startLineNo = start.line;
        const startLine = cm.getLine(startLineNo);
        if ( startLine.startsWith('!#if') ) {
            return foldIfEndif(startLineNo, startLine, cm);
        }
        if ( startLine.startsWith('!#include ') ) {
            return foldInclude(startLineNo, startLine, cm);
        }
    };
})());

/******************************************************************************/

// Linter

{
    const astParser = new sfp.AstFilterParser({
        interactive: true,
        nativeCssHas: vAPI.webextFlavor.env.includes('native_css_has'),
    });

    const changeset = [];
    let changesetTimer;

    const includeset = new Set();
    let errorCount = 0;

    const ifendifSet = new Set();
    let ifendifSetChanged = false;

    const extractMarkerDetails = (doc, lineHandle) => {
        if ( astParser.isUnsupported() ) {
            return { lint: 'error', msg: 'Unsupported filter syntax' };
        }
        if ( astParser.hasError() ) {
            let msg = 'Invalid filter';
            switch ( astParser.astError ) {
            case sfp.AST_ERROR_UNSUPPORTED:
                msg = `${msg}: Unsupported filter syntax`;
                break;
            case sfp.AST_ERROR_REGEX:
                msg = `${msg}: Bad regular expression`;
                break;
            case sfp.AST_ERROR_PATTERN:
                msg = `${msg}: Bad pattern`;
                break;
            case sfp.AST_ERROR_DOMAIN_NAME:
                msg = `${msg}: Bad domain name`;
                break;
            case sfp.AST_ERROR_OPTION_BADVALUE:
                msg = `${msg}: Bad value assigned to a valid option`;
                break;
            case sfp.AST_ERROR_OPTION_DUPLICATE:
                msg = `${msg}: Duplicate filter option`;
                break;
            case sfp.AST_ERROR_OPTION_UNKNOWN:
                msg = `${msg}: Unsupported filter option`;
                break;
            case sfp.AST_ERROR_IF_TOKEN_UNKNOWN:
                msg = `${msg}: Unknown preparsing token`;
                break;
            case sfp.AST_ERROR_UNTRUSTED_SOURCE:
                msg = `${msg}: Filter requires trusted source`;
                break;
            default:
                if ( astParser.isCosmeticFilter() && astParser.result.error ) {
                    msg = `${msg}: ${astParser.result.error}`;
                }
                break;
            }
            return { lint: 'error', msg };
        }
        if ( astParser.astType !== sfp.AST_TYPE_COMMENT ) { return; }
        if ( astParser.astTypeFlavor !== sfp.AST_TYPE_COMMENT_PREPARSER ) {
            if ( astParser.raw.startsWith('! <<<<<<<< ') === false ) { return; }
            for ( const include of includeset ) {
                if ( astParser.raw.endsWith(include) === false ) { continue; }
                includeset.delete(include);
                return { lint: 'include-end' };
            }
            return;
        }
        if ( /^\s*!#if \S+/.test(astParser.raw) ) {
            return {
                lint: 'if-start',
                data: {
                    state: sfp.utils.preparser.evaluateExpr(
                        astParser.getTypeString(sfp.NODE_TYPE_PREPARSE_DIRECTIVE_IF_VALUE),
                        preparseDirectiveEnv
                    ) ? 'y' : 'n'
                }
            };
        }
        if ( /^\s*!#endif\b/.test(astParser.raw) ) {
            return { lint: 'if-end' };
        }
        const match = /^\s*!#include\s*(\S+)/.exec(astParser.raw);
        if ( match === null ) { return; }
        const nextLineHandle = doc.getLineHandle(lineHandle.lineNo() + 1);
        if ( nextLineHandle === undefined ) { return; }
        if ( nextLineHandle.text.startsWith('! >>>>>>>> ') === false ) { return; }
        const includeToken = `/${match[1]}`;
        if ( nextLineHandle.text.endsWith(includeToken) === false ) { return; }
        includeset.add(includeToken);
        return { lint: 'include-start' };
    };

    const extractMarker = lineHandle => {
        const markers = lineHandle.gutterMarkers || null;
        return markers !== null
            ? markers['CodeMirror-lintgutter'] || null
            : null;
    };

    const markerTemplates = {
        'error': {
            node: null,
            html: [
                '<div class="CodeMirror-lintmarker" data-lint="error" data-error="y">&nbsp;',
                  '<span class="msg"></span>',
                '</div>',
            ],
        },
        'if-start': {
            node: null,
            html: [
                '<div class="CodeMirror-lintmarker" data-lint="if" data-fold="start" data-state="">&nbsp;',
                  '<svg viewBox="0 0 100 100">',
                    '<polygon points="0,0 100,0 50,100" />',
                  '</svg>',
                  '<span class="msg">Mismatched if-endif directive</span>',
                '</div>',
            ],
        },
        'if-end': {
            node: null,
            html: [
                '<div class="CodeMirror-lintmarker" data-lint="if" data-fold="end">&nbsp;',
                  '<svg viewBox="0 0 100 100">',
                    '<polygon points="50,0 100,100 0,100" />',
                  '</svg>',
                  '<span class="msg">Mismatched if-endif directive</span>',
                '</div>',
            ],
        },
        'include-start': {
            node: null,
            html: [
                '<div class="CodeMirror-lintmarker" data-lint="include" data-fold="start">&nbsp;',
                  '<svg viewBox="0 0 100 100">',
                    '<polygon points="0,0 100,0 50,100" />',
                  '</svg>',
                '</div>',
            ],
        },
        'include-end': {
            node: null,
            html: [
                '<div class="CodeMirror-lintmarker" data-lint="include" data-fold="end">&nbsp;',
                  '<svg viewBox="0 0 100 100">',
                    '<polygon points="50,0 100,100 0,100" />',
                  '</svg>',
                '</div>',
            ],
        },
    };

    const markerFromTemplate = details => {
        const template = markerTemplates[details.lint];
        if ( template.node === null ) {
            const domParser = new DOMParser();
            const doc = domParser.parseFromString(template.html.join(''), 'text/html');
            template.node = document.adoptNode(qs$(doc, '.CodeMirror-lintmarker'));
        }
        const node = template.node.cloneNode(true);
        if ( details.data instanceof Object ) {
            for ( const [ k, v ] of Object.entries(details.data) ) {
                node.dataset[k] = `${v}`;
            }
        }
        return node;
    };

    const addMarker = (doc, lineHandle, marker, details) => {
        if ( marker && marker.dataset.lint !== details.lint ) {
            doc.setGutterMarker(lineHandle, 'CodeMirror-lintgutter', null);
            if ( marker.dataset.error === 'y' ) {
                errorCount -= 1;
            }
            if ( marker.dataset.lint === 'if' ) {
                ifendifSet.delete(lineHandle);
                ifendifSetChanged = true;
            }
            marker = null;
        }
        if ( marker === null ) {
            marker = markerFromTemplate(details);
            doc.setGutterMarker(lineHandle, 'CodeMirror-lintgutter', marker);
            if ( marker.dataset.error === 'y' ) {
                errorCount += 1;
            }
            if ( marker.dataset.lint === 'if' ) {
                ifendifSet.add(lineHandle);
                ifendifSetChanged = true;
            }
        } else if ( marker.dataset.lint === 'error' ) {
            if ( marker.dataset.error !== 'y' ) {
                marker.dataset.error = 'y';
                errorCount += 1;
            }
        }
        if ( typeof details.msg !== 'string' || details.msg === '' ) { return; }
        const msgElem = qs$(marker, '.msg');
        if ( msgElem === null ) { return; }
        msgElem.textContent = details.msg;
    };

    const removeMarker = (doc, lineHandle, marker) => {
        doc.setGutterMarker(lineHandle, 'CodeMirror-lintgutter', null);
        if ( marker.dataset.error === 'y' ) {
            errorCount -= 1;
        }
        if ( marker.dataset.lint === 'if' ) {
            ifendifSet.delete(lineHandle);
            ifendifSetChanged = true;
        }
    };

    // Analyze whether all if-endif are properly paired
    const processIfendifs = ( ) => {
        if ( ifendifSet.size === 0 ) { return; }
        if ( ifendifSetChanged !== true ) { return; }
        const sortFn = (a, b) => a.lineNo() - b.lineNo();
        const sorted = Array.from(ifendifSet).sort(sortFn);
        const bad = [];
        const stack = [];
        for ( const line of sorted ) {
            const marker = extractMarker(line);
            const fold = marker.dataset.fold;
            if ( fold === 'start' ) {
                stack.push(line);
            } else if ( fold === 'end' ) {
                if ( stack.length !== 0 ) {
                    if ( marker.dataset.error === 'y' ) {
                        marker.dataset.error = '';
                        errorCount -= 1;
                    }
                    const ifstart = extractMarker(stack.pop());
                    if ( ifstart.dataset.error === 'y' ) {
                        ifstart.dataset.error = '';
                        errorCount -= 1;
                    }
                } else {
                    bad.push(line);
                }
            }
        }
        bad.push(...stack);
        for ( const line of bad ) {
            const marker = extractMarker(line);
            marker.dataset.error = 'y';
            errorCount += 1;
        }
        ifendifSetChanged = false;
    };

    const processDeletion = (doc, change) => {
        let { from, to } = change;
        doc.eachLine(from.line, to.line, lineHandle => {
            const marker = extractMarker(lineHandle);
            if ( marker === null ) { return; }
            if ( marker.dataset.error === 'y' ) {
                marker.dataset.error = '';
                errorCount -= 1;
            }
            ifendifSet.delete(lineHandle);
            ifendifSetChanged = true;
        });
    };

    const processInsertion = (doc, deadline, change) => {
        let { from, to } = change;
        doc.eachLine(from, to, lineHandle => {
            astParser.parse(lineHandle.text);
            const markerDetails = extractMarkerDetails(doc, lineHandle);
            const marker = extractMarker(lineHandle);
            if ( markerDetails !== undefined ) {
                addMarker(doc, lineHandle, marker, markerDetails);
            } else if ( marker !== null ) {
                removeMarker(doc, lineHandle, marker);
            }
            from += 1;
            if ( (from & 0x0F) !== 0 ) { return; }
            if ( deadline.timeRemaining() !== 0 ) { return; }
            return true;
        });
        if ( from !== to ) {
            return { from, to };
        }
    };

    const processChangeset = (doc, deadline) => {
        const cm = doc.getEditor();
        cm.startOperation();
        while ( changeset.length !== 0 ) {
            const change = processInsertion(doc, deadline, changeset.shift());
            if ( change === undefined ) { continue; }
            changeset.unshift(change);
            break;
        }
        cm.endOperation();
        if ( changeset.length !== 0 ) {
            return processChangesetAsync(doc);
        }
        includeset.clear();
        processIfendifs(doc);
        CodeMirror.signal(doc.getEditor(), 'linterDone', { errorCount });
    };

    const processChangesetAsync = doc => {
        if ( changesetTimer !== undefined ) { return; }
        changesetTimer = self.requestIdleCallback(deadline => {
            changesetTimer = undefined;
            processChangeset(doc, deadline);
        });
    };

    const onChanges = (cm, changes) => {
        if ( changes.length === 0 ) { return; }
        const doc = cm.getDoc();
        for ( const change of changes ) {
            const from = change.from.line;
            const to = from + change.text.length;
            changeset.push({ from, to });
        }
        processChangesetAsync(doc);
    };

    const onBeforeChanges = (cm, change) => {
        const doc = cm.getDoc();
        processDeletion(doc, change);
    };

    const foldRangeFinder = (cm, from) => {
        const lineNo = from.line;
        const lineHandle = cm.getDoc().getLineHandle(lineNo);
        const marker = extractMarker(lineHandle);
        if ( marker === null ) { return; }
        if ( marker.dataset.fold === undefined ) { return; }
        const foldName = marker.dataset.lint;
        from.ch = lineHandle.text.length;
        const to = { line: 0, ch: 0 };
        const doc = cm.getDoc();
        let depth = 0;
        doc.eachLine(from.line, doc.lineCount(), lineHandle => {
            const marker = extractMarker(lineHandle);
            if ( marker === null ) { return; }
            if ( marker.dataset.lint === foldName && marker.dataset.fold === 'start' ) {
                depth += 1;
                return;
            }
            if ( marker.dataset.lint !== foldName ) { return; }
            if ( marker.dataset.fold !== 'end' ) { return; }
            depth -= 1;
            if ( depth !== 0 ) { return; }
            to.line = lineHandle.lineNo();
            return true;
        });
        return { from, to };
    };

    const onGutterClick = (cm, lineNo, gutterId, ev) => {
        if ( ev.button !== 0 ) { return; }
        if ( gutterId !== 'CodeMirror-lintgutter' ) { return; }
        const doc = cm.getDoc();
        const lineHandle = doc.getLineHandle(lineNo);
        const marker = extractMarker(lineHandle);
        if ( marker === null ) { return; }
        if ( marker.dataset.fold === 'start' ) {
            if ( ev.ctrlKey ) {
                if ( dom.cl.has(marker, 'folded') ) {
                    CodeMirror.commands.unfoldAll(cm);
                } else {
                    CodeMirror.commands.foldAll(cm);
                }
                doc.setCursor(lineNo);
                return;
            }
            cm.foldCode(lineNo, {
                widget: '\u00A0\u22EF\u00A0',
                rangeFinder: foldRangeFinder,
            });
            return;
        }
        if ( marker.dataset.fold === 'end' ) {
            let depth = 1;
            let lineNo = lineHandle.lineNo();
            while ( lineNo-- ) {
                const prevLineHandle = doc.getLineHandle(lineNo);
                const markerFrom = extractMarker(prevLineHandle);
                if ( markerFrom === null ) { continue; }
                if ( markerFrom.dataset.fold === 'end' ) {
                    depth += 1;
                } else if ( markerFrom.dataset.fold === 'start' ) {
                    depth -= 1;
                    if ( depth === 0 ) {
                        doc.setCursor(lineNo);
                        break;
                    }
                }
            }
            return;
        }
    };

    self.addEventListener('trustedSource', ev => {
        const { trusted } = ev.detail;
        astParser.options.trustedSource = trusted;
    });

    self.addEventListener('trustedScriptletTokens', ev => {
        astParser.options.trustedScriptletTokens = ev.detail;
    });

    CodeMirror.defineInitHook(cm => {
        cm.on('changes', onChanges);
        cm.on('beforeChange', onBeforeChanges);
        cm.on('gutterClick', onGutterClick);
        cm.on('fold', function(cm, from) {
            const doc = cm.getDoc();
            const lineHandle = doc.getLineHandle(from.line);
            const marker = extractMarker(lineHandle);
            dom.cl.add(marker, 'folded');
        });
        cm.on('unfold', function(cm, from) {
            const doc = cm.getDoc();
            const lineHandle = doc.getLineHandle(from.line);
            const marker = extractMarker(lineHandle);
            dom.cl.remove(marker, 'folded');
        });
    });
}

/******************************************************************************/

// Enhanced word selection

{
    const selectWordAt = function(cm, pos) {
        const { line, ch } = pos;
        const s = cm.getLine(line);
        const { type: token } = cm.getTokenAt(pos);
        let beg, end;

        // Select URL in comments
        if ( /\bcomment\b/.test(token) && /\blink\b/.test(token) ) {
            const l = /\S+$/.exec(s.slice(0, ch));
            if ( l && /^https?:\/\//.test(s.slice(l.index)) ) {
                const r = /^\S+/.exec(s.slice(ch));
                if ( r ) {
                    beg = l.index;
                    end = ch + r[0].length;
                }
            }
        }

        // Better word selection for extended filters: prefix
        else if (
            /\bline-cm-ext-(?:dom|html|js)\b/.test(token) &&
            /\bvalue\b/.test(token)
        ) {
            const l = /[^,.]*$/i.exec(s.slice(0, ch));
            const r = /^[^#,]*/i.exec(s.slice(ch));
            if ( l && r ) {
                beg = l.index;
                end = ch + r[0].length;
            }
        }

        // Better word selection for cosmetic and HTML filters: suffix
        else if ( /\bline-cm-ext-(?:dom|html)\b/.test(token) ) {
            const l = /[#.]?[a-z0-9_-]+$/i.exec(s.slice(0, ch));
            const r = /^[a-z0-9_-]+/i.exec(s.slice(ch));
            if ( l && r ) {
                beg = l.index;
                end = ch + r[0].length;
                if ( /\bdef\b/.test(cm.getTokenTypeAt({ line, ch: beg + 1 })) ) {
                    beg += 1;
                }
            }
        }

        // Better word selection for network filters
        else if ( /\bline-cm-net\b/.test(token) ) {
            if ( /\bvalue\b/.test(token) ) {
                const l = /[^ ,.=|]*$/i.exec(s.slice(0, ch));
                const r = /^[^ #,|]*/i.exec(s.slice(ch));
                if ( l && r ) {
                    beg = l.index;
                    end = ch + r[0].length;
                }
            } else if ( /\bdef\b/.test(token) ) {
                const l = /[a-z0-9-]+$/i.exec(s.slice(0, ch));
                const r = /^[^,]*=[^,]+/i.exec(s.slice(ch));
                if ( l && r ) {
                    beg = l.index;
                    end = ch + r[0].length;
                }
            }
        }

        if ( beg === undefined ) {
            const { anchor, head } = cm.findWordAt(pos);
            return { from: anchor, to: head };
        }

        return {
            from: { line, ch: beg },
            to: { line, ch: end },
        };
    };

    CodeMirror.defineInitHook(cm => {
        cm.setOption('configureMouse', function(cm, repeat) {
            return {
                unit: repeat === 'double' ? selectWordAt : null,
            };
        });
    });
}

/******************************************************************************/

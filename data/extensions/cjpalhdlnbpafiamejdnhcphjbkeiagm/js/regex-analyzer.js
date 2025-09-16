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

import Regex from '../lib/regexanalyzer/regex.js';

/******************************************************************************/

// Depends on:
// https://github.com/foo123/RegexAnalyzer
const RegexAnalyzer = Regex && Regex.Analyzer || null;

export function isRE2(reStr) {
    if ( RegexAnalyzer === null ) { return true; }
    try {
        return _isRE2(RegexAnalyzer(reStr, false).tree());
    } catch {
    }
    return false;
}

export function tokenizableStrFromRegex(reStr) {
    return _literalStrFromRegex(reStr);
}

/******************************************************************************/

function _isRE2(node) {
    if ( node instanceof Object === false ) { return true; }
    if ( node.flags instanceof Object ) {
        if ( node.flags.LookAhead === 1 ) { return false; }
        if ( node.flags.NegativeLookAhead === 1 ) { return false; }
        if ( node.flags.LookBehind === 1 ) { return false; }
        if ( node.flags.NegativeLookBehind === 1 ) { return false; }
    }
    if ( Array.isArray(node.val) ) {
        for ( const entry of node.val ) {
            if ( _isRE2(entry) === false ) { return false; }
        }
    }
    if ( node.val instanceof Object ) {
        return _isRE2(node.val);
    }
    return true;
}

/******************************************************************************/

function _literalStrFromRegex(reStr) {
    if ( RegexAnalyzer === null ) { return ''; }
    let s = '';
    try {
        s = tokenizableStrFromNode(
            RegexAnalyzer(reStr, false).tree()
        );
    } catch {
    }
    // Process optional sequences
    const reOptional = /[\x02\x03]+/;
    for (;;) {
        const match = reOptional.exec(s);
        if ( match === null ) { break; }
        const left = s.slice(0, match.index);
        const middle = match[0];
        const right = s.slice(match.index + middle.length);
        s = left;
        s += firstCharCodeClass(right) === 1 || firstCharCodeClass(middle) === 1
            ? '\x01'
            : '\x00';
        s += lastCharCodeClass(left) === 1 || lastCharCodeClass(middle) === 1
            ? '\x01'
            : '\x00';
        s += right;
    }
    return s;
}

function firstCharCodeClass(s) {
    if ( s.length === 0 ) { return 0; }
    const c = s.charCodeAt(0);
    if ( c === 1 || c === 3 ) { return 1; }
    return reCharCodeClass.test(s.charAt(0)) ? 1 : 0;
}

function lastCharCodeClass(s) {
    const i = s.length - 1;
    if ( i === -1 ) { return 0; }
    const c = s.charCodeAt(i);
    if ( c === 1 || c === 3 ) { return 1; }
    return reCharCodeClass.test(s.charAt(i)) ? 1 : 0;
}

const reCharCodeClass = /[%0-9A-Za-z]/;

function tokenizableStrFromNode(node) {
    switch ( node.type ) {
    case 1: /* T_SEQUENCE, 'Sequence' */ {
        let s = '';
        for ( let i = 0; i < node.val.length; i++ ) {
            s += tokenizableStrFromNode(node.val[i]);
        }
        return s;
    }
    case 2: /* T_ALTERNATION, 'Alternation' */
    case 8: /* T_CHARGROUP, 'CharacterGroup' */ {
        if ( node.flags.NegativeMatch ) { return '\x01'; }
        let firstChar = 0;
        let lastChar = 0;
        for ( let i = 0; i < node.val.length; i++ ) {
            const s = tokenizableStrFromNode(node.val[i]);
            if ( firstChar === 0 && firstCharCodeClass(s) === 1 ) {
                firstChar = 1;
            }
            if ( lastChar === 0 && lastCharCodeClass(s) === 1 ) {
                lastChar = 1;
            }
            if ( firstChar === 1 && lastChar === 1 ) { break; }
        }
        return String.fromCharCode(firstChar, lastChar);
    }
    case 4: /* T_GROUP, 'Group' */ {
        if (
            node.flags.NegativeLookAhead === 1 ||
            node.flags.NegativeLookBehind === 1
        ) {
            return '';
        }
        return tokenizableStrFromNode(node.val);
    }
    case 16: /* T_QUANTIFIER, 'Quantifier' */ {
        if ( node.flags.max === 0 ) { return ''; }
        const s = tokenizableStrFromNode(node.val);
        const first = firstCharCodeClass(s);
        const last = lastCharCodeClass(s);
        if ( node.flags.min !== 0 ) {
            return String.fromCharCode(first, last);
        }
        return String.fromCharCode(first+2, last+2);
    }
    case 64: /* T_HEXCHAR, 'HexChar' */ {
        if (
            node.flags.Code === '01' ||
            node.flags.Code === '02' ||
            node.flags.Code === '03'
        ) {
            return '\x00';
        }
        return node.flags.Char;
    }
    case 128: /* T_SPECIAL, 'Special' */ {
        const flags = node.flags;
        if (
            flags.EndCharGroup === 1 || // dangling `]`
            flags.EndGroup === 1 ||     // dangling `)`
            flags.EndRepeats === 1      // dangling `}`
        ) {
            throw new Error('Unmatched bracket');
        }
        return flags.MatchEnd === 1 ||
               flags.MatchStart === 1 ||
               flags.MatchWordBoundary === 1
            ? '\x00'
            : '\x01';
    }
    case 256: /* T_CHARS, 'Characters' */ {
        for ( let i = 0; i < node.val.length; i++ ) {
            if ( firstCharCodeClass(node.val[i]) === 1 ) {
                return '\x01';
            }
        }
        return '\x00';
    }
    // Ranges are assumed to always involve token-related characters.
    case 512: /* T_CHARRANGE, 'CharacterRange' */ {
        return '\x01';
    }
    case 1024: /* T_STRING, 'String' */ {
        return node.val;
    }
    case 2048: /* T_COMMENT, 'Comment' */ {
        return '';
    }
    default:
        break;
    }
    return '\x01';
}

/******************************************************************************/

export function toHeaderPattern(reStr) {
    if ( RegexAnalyzer === null ) { return; }
    try {
        return _toHeaderPattern(RegexAnalyzer(reStr, false).tree());
    } catch {
    }
}

function _toHeaderPattern(branch, depth = 0) {
    switch ( branch.type ) {
    case 1: /* T_SEQUENCE, 'Sequence' */ {
        let s = '';
        for ( const node of branch.val ) {
            const t = _toHeaderPattern(node, depth+1);
            if ( t === undefined ) { return; }
            s += t;
        }
        if ( depth === 0 && branch.val.length !== 0 ) {
            const first = branch.val[0];
            if ( first.type !== 128 || first.val !== '^' ) { s = `*${s}`; }
            const last = branch.val.at(-1);
            if ( last.type !== 128 || last.val !== '$' ) { s = `${s}*`; }
        }
        return s;
    }
    case 4: /* T_GROUP, 'Group' */ {
        if (
            branch.flags.NegativeLookAhead === 1 ||
            branch.flags.NegativeLookBehind === 1
        ) {
            return;
        }
        return _toHeaderPattern(branch.val, depth+1);
    }
    case 64: /* T_HEXCHAR, 'HexChar' */
        return branch.flags.Char;
    case 128: /* T_SPECIAL, 'Special' */ {
        if ( branch.val === '^' ) { return ''; }
        if ( branch.val === '$' ) { return ''; }
        return;
    }
    case 1024: /* T_STRING, 'String' */
        return branch.val;
    case 2048: /* T_COMMENT, 'Comment' */
        return '';
    default:
        break;
    }
}

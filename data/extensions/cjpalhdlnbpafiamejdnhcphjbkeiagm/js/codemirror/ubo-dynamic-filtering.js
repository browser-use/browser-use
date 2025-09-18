/*******************************************************************************

    uBlock Origin - a comprehensive, efficient content blocker
    Copyright (C) 2019-present Raymond Hill

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

CodeMirror.defineMode('ubo-dynamic-filtering', ( ) => {

    const validSwitches = new Set([
        'no-strict-blocking:',
        'no-popups:',
        'no-cosmetic-filtering:',
        'no-remote-fonts:',
        'no-large-media:',
        'no-csp-reports:',
        'no-scripting:',
    ]);
    const validSwitcheStates = new Set([
        'true',
        'false',
    ]);
    const validHnRuleTypes = new Set([
        '*',
        '3p',
        'image',
        'inline-script',
        '1p-script',
        '3p-script',
        '3p-frame',
    ]);
    const invalidURLRuleTypes = new Set([
        'doc',
        'main_frame',
    ]);
    const validActions = new Set([
        'block',
        'allow',
        'noop',
    ]);
    const hnValidator = new URL(self.location.href);
    const reBadHn = /[%]|^\.|\.$/;
    const slices = [];
    let sliceIndex = 0;
    let sliceCount = 0;
    let hostnameToDomainMap = new Map();
    let psl;

    const isValidHostname = hnin => {
        if ( hnin === '*' ) { return true; }
        hnValidator.hostname = '_';
        try {
            hnValidator.hostname = hnin;
        } catch {
            return false;
        }
        const hnout = hnValidator.hostname;
        return hnout !== '_' && hnout !== '' && reBadHn.test(hnout) === false;
    };

    const addSlice = (len, style = null) => {
        let i = sliceCount;
        if ( i === slices.length ) {
            slices[i] = { len: 0, style: null };
        }
        const entry = slices[i];
        entry.len = len;
        entry.style = style;
        sliceCount += 1;
    };

    const addMatchSlice = (match, style = null) => {
        const len = match !== null ? match[0].length : 0;
        addSlice(len, style);
        return match !== null ? match.input.slice(len) : '';
    };

    const addMatchHnSlices = (match, style = null) => {
        const hn = match[0];
        if ( hn === '*' ) {
            return addMatchSlice(match, style);
        }
        let dn = hostnameToDomainMap.get(hn) || '';
        if ( dn === '' && psl !== undefined ) {
            dn = /(\d|\])$/.test(hn) ? hn : (psl.getDomain(hn) || hn);
        }
        const entityBeg = hn.length - dn.length;
        if ( entityBeg !== 0 ) {
            addSlice(entityBeg, style);
        }
        let entityEnd = dn.indexOf('.');
        if ( entityEnd === -1 ) { entityEnd = dn.length; }
        addSlice(entityEnd, style !== null ? `${style} strong` : 'strong');
        if ( entityEnd < dn.length ) {
            addSlice(dn.length - entityEnd, style);
        }
        return match.input.slice(hn.length);
    };

    const makeSlices = (stream, opts) => {
        sliceIndex = 0;
        sliceCount = 0;
        let { string } = stream;
        if ( string === '...' ) { return; }
        const { sortType } = opts;
        const reNotToken = /^\s+/;
        const reToken = /^\S+/;
        const tokens = [];
        // leading whitespaces
        let match = reNotToken.exec(string);
        if ( match !== null ) {
            string = addMatchSlice(match);
        }
        // first token
        match = reToken.exec(string);
        if ( match === null ) { return; }
        tokens.push(match[0]);
        // hostname or switch
        const isSwitchRule = validSwitches.has(match[0]);
        if ( isSwitchRule ) {
            string = addMatchSlice(match, sortType === 0 ? 'sortkey' : null);
        } else if ( isValidHostname(match[0]) ) {
            if ( sortType === 1 ) {
                string = addMatchHnSlices(match, 'sortkey');
            } else {
                string = addMatchHnSlices(match, null);
            }
        } else {
            string = addMatchSlice(match, 'error');
        }
        // whitespaces before second token
        match = reNotToken.exec(string);
        if ( match === null ) { return; }
        string = addMatchSlice(match);
        // second token
        match = reToken.exec(string);
        if ( match === null ) { return; }
        tokens.push(match[0]);
        // hostname or url
        const isURLRule = isSwitchRule === false && match[0].indexOf('://') > 0;
        if ( isURLRule ) {
            string = addMatchSlice(match, sortType === 2 ? 'sortkey' : null);
        } else if ( isValidHostname(match[0]) === false ) {
            string = addMatchSlice(match, 'error');
        } else if ( sortType === 1 && isSwitchRule || sortType === 2 ) {
            string = addMatchHnSlices(match, 'sortkey');
        } else {
            string = addMatchHnSlices(match, null);
        }
        // whitespaces before third token
        match = reNotToken.exec(string);
        if ( match === null ) { return; }
        string = addMatchSlice(match);
        // third token
        match = reToken.exec(string);
        if ( match === null ) { return; }
        tokens.push(match[0]);
        // rule type or switch state
        if ( isSwitchRule ) {
            string = validSwitcheStates.has(match[0])
                ? addMatchSlice(match, match[0] === 'true' ? 'blockrule' : 'allowrule')
                : addMatchSlice(match, 'error');
        } else if ( isURLRule ) {
            string = invalidURLRuleTypes.has(match[0])
                ? addMatchSlice(match, 'error')
                : addMatchSlice(match);
        } else if ( tokens[1] === '*' ) {
            string = validHnRuleTypes.has(match[0])
                ? addMatchSlice(match)
                : addMatchSlice(match, 'error');
        } else {
            string = match[0] === '*'
                ? addMatchSlice(match)
                : addMatchSlice(match, 'error');
        }
        // whitespaces before fourth token
        match = reNotToken.exec(string);
        if ( match === null ) { return; }
        string = addMatchSlice(match);
        // fourth token
        match = reToken.exec(string);
        if ( match === null ) { return; }
        tokens.push(match[0]);
        string = isSwitchRule || validActions.has(match[0]) === false
            ? addMatchSlice(match, 'error')
            : addMatchSlice(match, `${match[0]}rule`);
        // whitespaces before end of line
        match = reNotToken.exec(string);
        if ( match === null ) { return; }
        string = addMatchSlice(match);
        // any token beyond fourth token is invalid
        match = reToken.exec(string);
        if ( match !== null ) {
            string = addMatchSlice(null, 'error');
        }
    };

    const token = function(stream) {
        if ( stream.sol() ) {
            makeSlices(stream, this);
        }
        if ( sliceIndex >= sliceCount ) {
            stream.skipToEnd(stream);
            return null;
        }
        const { len, style } = slices[sliceIndex++];
        if ( len === 0 ) {
            stream.skipToEnd();
        } else {
            stream.pos += len;
        }
        return style;
    };

    return {
        token,
        sortType: 1,
        setHostnameToDomainMap: a => { hostnameToDomainMap = a; },
        setPSL: a => { psl = a; },
    };
});

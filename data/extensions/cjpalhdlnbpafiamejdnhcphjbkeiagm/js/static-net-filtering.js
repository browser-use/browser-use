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

import * as sfp from './static-filtering-parser.js';

import { domainFromHostname, hostnameFromNetworkURL } from './uri-utils.js';
import { dropTask, queueTask } from './tasks.js';
import { isRE2, toHeaderPattern, tokenizableStrFromRegex } from './regex-analyzer.js';

import BidiTrieContainer from './biditrie.js';
import { CompiledListReader } from './static-filtering-io.js';
import { FilteringContext } from './filtering-context.js';
import HNTrieContainer from './hntrie.js';
import { urlSkip } from './urlskip.js';

/******************************************************************************/

// Access to a key-val store is optional and useful only for optimal
// initialization at module load time. Probably could re-arrange code
// to export an init() function with optimization parameters which would
// need to be called by module clients. For now, I want modularizing with
// minimal amount of changes.

const keyvalStore = typeof vAPI !== 'undefined'
    ? vAPI.localStorage
    : { getItem() { return null; }, setItem() {}, removeItem() {} };

/******************************************************************************/

// 10fedcba9876543210
// ||||||||    | || |
// ||||||||    | || |
// ||||||||    | || |
// ||||||||    | || |
// ||||||||    | || +---- bit 0- 1: block=0, allow=1, block important=2
// ||||||||    | |+------ bit    2: unused
// ||||||||    | +------- bit 3- 4: party [0-3]
// ||||||||    +--------- bit 5- 9: type [0-31]
// |||||||+-------------- bit   10: headers-based filters
// ||||||+--------------- bit   11: redirect filters
// |||||+---------------- bit   12: removeparam filters
// ||||+----------------- bit   13: csp filters
// |||+------------------ bit   14: permissions filters
// ||+------------------- bit   15: uritransform filters
// |+-------------------- bit   16: replace filters
// +--------------------- bit   17: urlskip filters
// TODO: bit 11-17 could be converted into 3-bit value, as these options are not
//       meant to be combined.

const BLOCK_REALM          = 0b0000_0000_0000_0000_0000;
const ALLOW_REALM          = 0b0000_0000_0000_0000_0001;
const IMPORTANT_REALM      = 0b0000_0000_0000_0000_0010;
const BLOCKALLOW_REALM     = BLOCK_REALM | ALLOW_REALM | IMPORTANT_REALM;
const BLOCKIMPORTANT_REALM = BLOCK_REALM | IMPORTANT_REALM;
const ANYPARTY_REALM       = 0b0000_0000_0000_0000_0000;
const FIRSTPARTY_REALM     = 0b0000_0000_0000_0000_1000;
const THIRDPARTY_REALM     = 0b0000_0000_0000_0001_0000;
const ALLPARTIES_REALM     = FIRSTPARTY_REALM | THIRDPARTY_REALM;
const TYPE_REALM           = 0b0000_0000_0011_1110_0000;
const HEADERS_REALM        = 0b0000_0000_0100_0000_0000;
const REDIRECT_REALM       = 0b0000_0000_1000_0000_0000;
const REMOVEPARAM_REALM    = 0b0000_0001_0000_0000_0000;
const CSP_REALM            = 0b0000_0010_0000_0000_0000;
const PERMISSIONS_REALM    = 0b0000_0100_0000_0000_0000;
const URLTRANSFORM_REALM   = 0b0000_1000_0000_0000_0000;
const REPLACE_REALM        = 0b0001_0000_0000_0000_0000;
const URLSKIP_REALM        = 0b0010_0000_0000_0000_0000;
const MODIFY_REALMS        = REDIRECT_REALM | CSP_REALM |
                             REMOVEPARAM_REALM | PERMISSIONS_REALM |
                             URLTRANSFORM_REALM | REPLACE_REALM |
                             URLSKIP_REALM;

const TYPE_REALM_OFFSET = 5;

const typeNameToTypeValue = {
           'no_type':  0 << TYPE_REALM_OFFSET,
        'stylesheet':  1 << TYPE_REALM_OFFSET,
             'image':  2 << TYPE_REALM_OFFSET,
            'object':  3 << TYPE_REALM_OFFSET,
 'object_subrequest':  3 << TYPE_REALM_OFFSET,
            'script':  4 << TYPE_REALM_OFFSET,
             'fetch':  5 << TYPE_REALM_OFFSET,
    'xmlhttprequest':  5 << TYPE_REALM_OFFSET,
         'sub_frame':  6 << TYPE_REALM_OFFSET,
              'font':  7 << TYPE_REALM_OFFSET,
             'media':  8 << TYPE_REALM_OFFSET,
         'websocket':  9 << TYPE_REALM_OFFSET,
            'beacon': 10 << TYPE_REALM_OFFSET,
              'ping': 10 << TYPE_REALM_OFFSET,
             'other': 11 << TYPE_REALM_OFFSET,
             'popup': 12 << TYPE_REALM_OFFSET, // start of behavioral filtering
          'popunder': 13 << TYPE_REALM_OFFSET,
        'main_frame': 14 << TYPE_REALM_OFFSET, // start of 1p behavioral filtering
       'generichide': 15 << TYPE_REALM_OFFSET,
      'specifichide': 16 << TYPE_REALM_OFFSET,
       'inline-font': 17 << TYPE_REALM_OFFSET,
     'inline-script': 18 << TYPE_REALM_OFFSET,
             'cname': 19 << TYPE_REALM_OFFSET,
            'webrtc': 20 << TYPE_REALM_OFFSET,
       'unsupported': 21 << TYPE_REALM_OFFSET,
};

const otherTypeBitValue = typeNameToTypeValue.other;

const bitFromType = type =>
    1 << ((typeNameToTypeValue[type] >>> TYPE_REALM_OFFSET) - 1);

// All network request types to bitmap
//   bring origin to 0 (from TYPE_REALM_OFFSET -- see typeNameToTypeValue)
//   left-shift 1 by the above-calculated value
//   subtract 1 to set all type bits
const allNetworkTypesBits =
    (1 << (otherTypeBitValue >>> TYPE_REALM_OFFSET)) - 1;

const allTypesBits =
    allNetworkTypesBits |
    1 << (typeNameToTypeValue['popup'] >>> TYPE_REALM_OFFSET) - 1 |
    1 << (typeNameToTypeValue['main_frame'] >>> TYPE_REALM_OFFSET) - 1 |
    1 << (typeNameToTypeValue['inline-font'] >>> TYPE_REALM_OFFSET) - 1 |
    1 << (typeNameToTypeValue['inline-script'] >>> TYPE_REALM_OFFSET) - 1;
const unsupportedTypeBit =
    1 << (typeNameToTypeValue['unsupported'] >>> TYPE_REALM_OFFSET) - 1;

const typeValueToTypeName = [
    '',
    'stylesheet',
    'image',
    'object',
    'script',
    'xhr',
    'frame',
    'font',
    'media',
    'websocket',
    'ping',
    'other',
    'popup',
    'popunder',
    'document',
    'generichide',
    'specifichide',
    'inline-font',
    'inline-script',
    'cname',
    '',
    '',
    'webrtc',
    'unsupported',
];

const typeValueToDNRTypeName = [
    '',
    'stylesheet',
    'image',
    'object',
    'script',
    'xmlhttprequest',
    'sub_frame',
    'font',
    'media',
    'websocket',
    'ping',
    'other',
];

// Do not change order. Compiled filter lists rely on this order being
// consistent across sessions.
const MODIFIER_TYPE_REDIRECT = 1;
const MODIFIER_TYPE_REDIRECTRULE = 2;
const MODIFIER_TYPE_REMOVEPARAM = 3;
const MODIFIER_TYPE_CSP = 4;
const MODIFIER_TYPE_PERMISSIONS = 5;
const MODIFIER_TYPE_URLTRANSFORM = 6;
const MODIFIER_TYPE_REPLACE = 7;
const MODIFIER_TYPE_URLSKIP = 8;

const modifierBitsFromType = new Map([
    [ MODIFIER_TYPE_REDIRECT, REDIRECT_REALM ],
    [ MODIFIER_TYPE_REDIRECTRULE, REDIRECT_REALM ],
    [ MODIFIER_TYPE_REMOVEPARAM, REMOVEPARAM_REALM ],
    [ MODIFIER_TYPE_CSP, CSP_REALM ],
    [ MODIFIER_TYPE_PERMISSIONS, PERMISSIONS_REALM ],
    [ MODIFIER_TYPE_URLTRANSFORM, URLTRANSFORM_REALM ],
    [ MODIFIER_TYPE_REPLACE, REPLACE_REALM ],
    [ MODIFIER_TYPE_URLSKIP, URLSKIP_REALM ],
]);

const modifierTypeFromName = new Map([
    [ 'redirect', MODIFIER_TYPE_REDIRECT ],
    [ 'redirect-rule', MODIFIER_TYPE_REDIRECTRULE ],
    [ 'removeparam', MODIFIER_TYPE_REMOVEPARAM ],
    [ 'csp', MODIFIER_TYPE_CSP ],
    [ 'permissions', MODIFIER_TYPE_PERMISSIONS ],
    [ 'uritransform', MODIFIER_TYPE_URLTRANSFORM ],
    [ 'replace', MODIFIER_TYPE_REPLACE ],
    [ 'urlskip', MODIFIER_TYPE_URLSKIP ],
]);

const modifierNameFromType = new Map([
    [ MODIFIER_TYPE_REDIRECT, 'redirect' ],
    [ MODIFIER_TYPE_REDIRECTRULE, 'redirect-rule' ],
    [ MODIFIER_TYPE_REMOVEPARAM, 'removeparam' ],
    [ MODIFIER_TYPE_CSP, 'csp' ],
    [ MODIFIER_TYPE_PERMISSIONS, 'permissions' ],
    [ MODIFIER_TYPE_URLTRANSFORM, 'uritransform' ],
    [ MODIFIER_TYPE_REPLACE, 'replace' ],
    [ MODIFIER_TYPE_URLSKIP, 'urlskip' ],
]);

//const typeValueFromCatBits = catBits => (catBits >>> TYPE_REALM_OFFSET) & 0b11111;

const MAX_TOKEN_LENGTH = 7;

// Four upper bits of token hash are reserved for built-in predefined
// token hashes, which should never end up being used when tokenizing
// any arbitrary string.
const        NO_TOKEN_HASH = 0x5000_0000;
const       DOT_TOKEN_HASH = 0x1000_0000;
const       ANY_TOKEN_HASH = 0x2000_0000;
const ANY_HTTPS_TOKEN_HASH = 0x3000_0000;
const  ANY_HTTP_TOKEN_HASH = 0x4000_0000;
const     EMPTY_TOKEN_HASH = 0xF000_0000;
const   INVALID_TOKEN_HASH = 0xFFFF_FFFF;

/******************************************************************************/

// See the following as short-lived registers, used during evaluation. They are
// valid until the next evaluation.

let $requestMethodBit = 0;
let $requestTypeValue = 0;
let $requestURL = '';
let $requestURLRaw = '';
let $requestHostname = '';
let $requestAddress = '';
let $docHostname = '';
let $docDomain = '';
let $tokenBeg = 0;
let $patternMatchLeft = 0;
let $patternMatchRight = 0;
let $isBlockImportant = false;

const $docEntity = {
    entity: '',
    last: '',
    compute() {
        if ( this.last !== $docHostname ) {
            this.last = $docHostname;
            const pos = $docDomain.indexOf('.');
            this.entity = pos !== -1
                ? `${$docHostname.slice(0, pos - $docDomain.length)}.*`
                : '';
        }
        return this.entity;
    },
};

const $requestEntity = {
    entity: '',
    last: '',
    compute() {
        if ( this.last !== $requestHostname ) {
            this.last = $requestHostname;
            const requestDomain = domainFromHostname($requestHostname);
            const pos = requestDomain.indexOf('.');
            this.entity = pos !== -1
                ? `${$requestHostname.slice(0, pos - requestDomain.length)}.*`
                : '';
        }
        return this.entity;
    },
};

const $httpHeaders = {
    init(headers) {
        this.headers = headers;
        this.parsed.clear();
    },
    reset() {
        this.headers = [];
        this.parsed.clear();
    },
    lookup(name) {
        if ( this.parsed.size === 0 ) {
            for ( const { name, value } of this.headers ) {
                this.parsed.set(name.toLowerCase(), value);
            }
        }
        return this.parsed.get(name);
    },
    headers: [],
    parsed: new Map(),
};

/******************************************************************************/

// Local helpers

const restrSeparator = '(?:[^%.0-9a-z_-]|$)';

// https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Regular_Expressions
const reEscape = /[.*+?^${}()|[\]\\]/g;

// Convert a plain string (devoid of special characters) into a regex.
const restrFromPlainPattern = s => s.replace(reEscape, '\\$&');

const restrFromGenericPattern = function(s, anchor = 0) {
    let reStr = s.replace(restrFromGenericPattern.rePlainChars, '\\$&')
                 .replace(restrFromGenericPattern.reSeparators, restrSeparator)
                 .replace(restrFromGenericPattern.reDanglingAsterisks, '')
                 .replace(restrFromGenericPattern.reAsterisks, '\\S*?');
    if ( anchor & 0b100 ) {
        reStr = (
            reStr.startsWith('\\.') ?
                restrFromGenericPattern.restrHostnameAnchor2 :
                restrFromGenericPattern.restrHostnameAnchor1
        ) + reStr;
    } else if ( anchor & 0b010 ) {
        reStr = '^' + reStr;
    }
    if ( anchor & 0b001 ) {
        reStr += '$';
    }
    return reStr;
};
restrFromGenericPattern.rePlainChars = /[.+?${}()|[\]\\]/g;
restrFromGenericPattern.reSeparators = /\^/g;
restrFromGenericPattern.reDanglingAsterisks = /^\*+|\*+$/g;
restrFromGenericPattern.reAsterisks = /\*+/g;
restrFromGenericPattern.restrHostnameAnchor1 = '^[a-z-]+://(?:[^/?#]+\\.)?';
restrFromGenericPattern.restrHostnameAnchor2 = '^[a-z-]+://(?:[^/?#]+)?';

/******************************************************************************/

class LogData {
    constructor(categoryBits, tokenHash, iunit) {
        this.result = 0;
        this.source = 'static';
        this.tokenHash = tokenHash;
        if ( iunit === 0 ) {
            this.raw = this.regex = '';
            return;
        }
        this.result = (categoryBits & ALLOW_REALM) === 0 ? 1 : 2;
        const pattern = [];
        const regex = [];
        const options = [];
        const denyallow = [];
        const fromDomains = [];
        const toDomains = [];
        const logData = {
            pattern,
            regex,
            denyallow,
            fromDomains,
            toDomains,
            options,
            isRegex: false,
        };
        filterLogData(iunit, logData);
        if ( (categoryBits & THIRDPARTY_REALM) !== 0 ) {
            logData.options.unshift('3p');
        } else if ( (categoryBits & FIRSTPARTY_REALM) !== 0 ) {
            logData.options.unshift('1p');
        }
        const type = categoryBits & TYPE_REALM;
        if ( type !== 0 ) {
            logData.options.unshift(typeValueToTypeName[type >>> TYPE_REALM_OFFSET]);
        }
        let raw = logData.pattern.join('');
        if (
            logData.isRegex === false &&
            raw.charCodeAt(0) === 0x2F /* '/' */ &&
            raw.charCodeAt(raw.length - 1) === 0x2F /* '/' */
        ) {
            raw += '*';
        }
        if ( (categoryBits & ALLOW_REALM) !== 0 ) {
            raw = '@@' + raw;
        }
        if ( denyallow.length !== 0 ) {
            options.push(`denyallow=${denyallow.join('|')}`);
        }
        if ( fromDomains.length !== 0 ) {
            options.push(`from=${fromDomains.join('|')}`);
        }
        if ( toDomains.length !== 0 ) {
            options.push(`to=${toDomains.join('|')}`);
        }
        if ( options.length !== 0 ) {
            raw += '$' + options.join(',');
        }
        this.raw = raw;
        this.regex = logData.regex.join('');
        if ( logData.reason ) {
            this.reason = logData.reason;
        }
    }
    isUntokenized() {
        return this.tokenHash === NO_TOKEN_HASH;
    }
    isPureHostname() {
        return this.tokenHash === DOT_TOKEN_HASH;
    }

    static requote(s) {
        if ( /^\$|^(["'`]).*\1$|,/.test(s) === false ) { return s; }
        if ( s.includes("'") === false ) { return `'${s}'`; }
        if ( s.includes('"') === false ) { return `"${s}"`; }
        if ( s.includes('`') === false ) { return `\`${s}\``; }
        return `'${s.replace(/'/g, "\\'")}'`;
    }
}

/******************************************************************************/

const charClassMap = new Uint32Array(128);
const CHAR_CLASS_SEPARATOR = 0b00000001;

{
    const reSeparators = /[^\w%.-]/;
    for ( let i = 0; i < 128; i++ ) {
        if ( reSeparators.test(String.fromCharCode(i)) ) {
            charClassMap[i] |= CHAR_CLASS_SEPARATOR;
        }
    }
}

const isSeparatorChar = c => (charClassMap[c] & CHAR_CLASS_SEPARATOR) !== 0;

/******************************************************************************/

const FILTER_DATA_PAGE_SIZE = 65536;

const roundToFilterDataPageSize =
    len => (len + FILTER_DATA_PAGE_SIZE-1) & ~(FILTER_DATA_PAGE_SIZE-1);

let filterData = new Int32Array(FILTER_DATA_PAGE_SIZE * 5);
let filterDataWritePtr = 2;
const filterDataGrow = len => {
    if ( len <= filterData.length ) { return; }
    const newLen = roundToFilterDataPageSize(len);
    const newBuf = new Int32Array(newLen);
    newBuf.set(filterData);
    filterData = newBuf;
};
const filterDataShrink = ( ) => {
    const newLen = Math.max(
        roundToFilterDataPageSize(filterDataWritePtr),
        FILTER_DATA_PAGE_SIZE
    );
    if ( newLen >= filterData.length ) { return; }
    const newBuf = new Int32Array(newLen);
    newBuf.set(filterData.subarray(0, filterDataWritePtr));
    filterData = newBuf;
};
const filterDataAlloc = (...args) => {
    const len = args.length;
    const idata = filterDataAllocLen(len);
    for ( let i = 0; i < len; i++ ) {
        filterData[idata+i] = args[i];
    }
    return idata;
};
const filterDataAllocLen = len => {
    const idata = filterDataWritePtr;
    filterDataWritePtr += len;
    if ( filterDataWritePtr > filterData.length ) {
        filterDataGrow(filterDataWritePtr);
    }
    return idata;
};
const filterSequenceAdd = (a, b) => {
    const iseq = filterDataAllocLen(2);
    filterData[iseq+0] = a;
    filterData[iseq+1] = b;
    return iseq;
};
const filterDataReset = ( ) => {
    filterData.fill(0);
    filterDataWritePtr = 2;
};
const filterDataToSelfie = ( ) =>
    filterData.subarray(0, filterDataWritePtr);

const filterDataFromSelfie = selfie => {
    if ( selfie instanceof Int32Array === false ) { return false; }
    filterData = selfie;
    filterDataWritePtr = selfie.length;
    return true;
};

const filterRefs = [ null ];
let filterRefsWritePtr = 1;
const filterRefAdd = ref => {
    const i = filterRefsWritePtr;
    filterRefs[i] = ref;
    filterRefsWritePtr += 1;
    return i;
};
const filterRefsReset = ( ) => {
    filterRefs.fill(null);
    filterRefsWritePtr = 1;
};
const filterRefsToSelfie = ( ) =>
    filterRefs.slice(0, filterRefsWritePtr);

const filterRefsFromSelfie = selfie => {
    if ( Array.isArray(selfie) === false ) { return false; }
    for ( let i = 0, n = selfie.length; i < n; i++ ) {
        filterRefs[i] = selfie[i];
    }
    filterRefsWritePtr = selfie.length;
    return true;
};

/******************************************************************************/

const origHNTrieContainer = new HNTrieContainer();
const destHNTrieContainer = new HNTrieContainer();

/******************************************************************************/

const bidiTrieMatchExtra = (l, r, ix) => {
    for (;;) {
        $patternMatchLeft = l;
        $patternMatchRight = r;
        const iu = filterData[ix+0];
        if ( filterMatch(iu) ) { return iu; }
        ix = filterData[ix+1];
        if ( ix === 0 ) { break; }
    }
    return 0;
};

const bidiTrie = new BidiTrieContainer(bidiTrieMatchExtra);

/*******************************************************************************

    Each filter class will register itself in the map.

    IMPORTANT: any change which modifies the mapping will have to be
    reflected with µBlock.systemSettings.compiledMagic.

*/

const filterClasses = [];
const filterArgsToUnit = new Map();
let   filterClassIdGenerator = 0;

const registerFilterClass = fc => {
    const fid = filterClassIdGenerator++;
    fc.fid = fid;
    fc.fidstr = `${fid}`;
    filterClasses[fid] = fc;
};

const filterFromCompiled = args => {
    const fc = filterClasses[args[0]];
    const keygen = fc.keyFromArgs;
    if ( keygen === undefined ) {
        return fc.fromCompiled(args);
    }
    const key = `${fc.fidstr} ${(keygen(args) || '')}`;
    let idata = filterArgsToUnit.get(key);
    if ( idata !== undefined ) { return idata; }
    idata = fc.fromCompiled(args);
    filterArgsToUnit.set(key, idata);
    return idata;
};

const filterGetClass = idata => {
    return filterClasses[filterData[idata+0]];
};

const filterMatch = idata => filterClasses[filterData[idata+0]].match(idata);

const filterHasOriginHit = idata => {
    const fc = filterClasses[filterData[idata+0]];
    return fc.hasOriginHit !== undefined && fc.hasOriginHit(idata);
};

const filterGetDomainOpt = (idata, out) => {
    const fc = filterClasses[filterData[idata+0]];
    if ( fc.getDomainOpt === undefined ) { return; }
    const fromOpt = fc.getDomainOpt(idata);
    if ( out === undefined ) { return fromOpt; }
    out.push(fromOpt);
};

const filterGetRegexPattern = (idata, out) => {
    const fc = filterClasses[filterData[idata+0]];
    if ( fc.hasRegexPattern === undefined ) { return; }
    const reStr = fc.getRegexPattern(idata);
    if ( out === undefined ) { return reStr; }
    out.push(reStr);
};

const filterIsBidiTrieable = idata => {
    const fc = filterClasses[filterData[idata+0]];
    if ( fc.isBidiTrieable === undefined ) { return false; }
    return fc.isBidiTrieable(idata) === true;
};

const filterToBidiTrie = idata => {
    const fc = filterClasses[filterData[idata+0]];
    if ( fc.toBidiTrie === undefined ) { return; }
    return fc.toBidiTrie(idata);
};

const filterMatchAndFetchModifiers = (idata, env) => {
    const fc = filterClasses[filterData[idata+0]];
    if ( fc.matchAndFetchModifiers === undefined ) { return; }
    return fc.matchAndFetchModifiers(idata, env);
};

const filterGetModifierType = idata => {
    const fc = filterClasses[filterData[idata+0]];
    if ( fc.getModifierType === undefined ) { return; }
    return fc.getModifierType(idata);
};

const filterLogData = (idata, details) => {
    const fc = filterClasses[filterData[idata+0]];
    if ( fc.logData === undefined ) { return; }
    fc.logData(idata, details);
};

const filterDumpInfo = (idata) => {
    const fc = filterGetClass(idata);
    if ( fc.dumpInfo === undefined ) { return; }
    return fc.dumpInfo(idata);
};

const dnrRuleFromCompiled = (args, rule) => {
    const fc = filterClasses[args[0]];
    if ( fc.dnrFromCompiled === undefined ) { return false; }
    fc.dnrFromCompiled(args, rule);
    return true;
};

const dnrAddRuleError = (rule, msg) => {
    rule._error = rule._error || [];
    rule._error.push(msg);
};

const dnrAddRuleWarning = (rule, msg) => {
    rule._warning = rule._warning || [];
    rule._warning.push(msg);
};

/*******************************************************************************

    Filter classes

    Pattern:
        FilterPatternAny
        FilterPatternPlain
            FilterPatternPlain1
            FilterPatternPlainX
        FilterPatternGeneric
        FilterRegex
        FilterPlainTrie
        FilterHostnameDict

    Pattern modifiers:
        FilterAnchorHnLeft
            FilterAnchorHn
        FilterAnchorRight
        FilterAnchorLeft
        FilterTrailingSeparator

    Context, immediate:
        FilterOriginHit
            FilterOriginMiss
                FilterOriginEntityMiss
            FilterOriginEntityHit
        FilterOriginHitSet
            FilterOriginMissSet
            FilterJustOrigin
                FilterHTTPJustOrigin
                FilterHTTPSJustOrigin

    Other options:
        FilterDenyAllow
        FilterImportant
        FilterNotType
        FilterStrictParty
        FilterModifier
        FilterOnHeaders
        FilterIPAddress

    Collection:
        FilterCollection
            FilterCompositeAll
            FilterBucket
                FilterBucketIf
                    FilterBucketIfOriginHits
                    FilterBucketIfRegexHits
            FilterDomainHitAny

    A single filter can be made of many parts, in which case FilterCompositeAll
    is used to hold all the parts, and where all the parts must be a match in
    order for the filter to be a match.

**/

/******************************************************************************/

class FilterPatternAny {
    static match() {
        return true;
    }

    static compile() {
        return [ FilterPatternAny.fid ];
    }

    static fromCompiled(args) {
        return filterDataAlloc(args[0]);
    }

    static keyFromArgs() {
    }

    static logData(idata, details) {
        details.pattern.push('*');
        details.regex.push('^');
    }
}

registerFilterClass(FilterPatternAny);

/******************************************************************************/

class FilterImportant {
    static match() {
        return ($isBlockImportant = true);
    }

    static compile() {
        return [ FilterImportant.fid ];
    }

    static fromCompiled(args) {
        return filterDataAlloc(args[0]);
    }

    static dnrFromCompiled(args, rule) {
        rule.__important = true;
    }

    static keyFromArgs() {
    }

    static logData(idata, details) {
        details.options.unshift('important');
    }
}

registerFilterClass(FilterImportant);

/******************************************************************************/

class FilterPatternPlain {
    static isBidiTrieable(idata) {
        return filterData[idata+2] <= 255;
    }

    static toBidiTrie(idata) {
        return {
            i: filterData[idata+1],
            n: filterData[idata+2],
            itok: filterData[idata+3],
        };
    }

    static match(idata) {
        const left = $tokenBeg;
        const n = filterData[idata+2];
        if (
            bidiTrie.startsWith(
                left,
                bidiTrie.getHaystackLen(),
                filterData[idata+1],
                n
            ) === 0
        ) {
            return false;
        }
        $patternMatchLeft = left;
        $patternMatchRight = left + n;
        return true;
    }

    static compile(details) {
        const { tokenBeg } = details;
        if ( tokenBeg === 0 ) {
            return [ FilterPatternPlain.fid, details.pattern, 0 ];
        }
        if ( tokenBeg === 1 ) {
            return [ FilterPatternPlain1.fid, details.pattern, 1 ];
        }
        return [ FilterPatternPlainX.fid, details.pattern, tokenBeg ];
    }

    static fromCompiled(args) {
        const idata = filterDataAllocLen(4);
        filterData[idata+0] = args[0];                          // fid
        filterData[idata+1] = bidiTrie.storeString(args[1]);    // i
        filterData[idata+2] = args[1].length;                   // n   
        filterData[idata+3] = args[2];                          // tokenBeg
        return idata;
    }

    static dnrFromCompiled(args, rule) {
        if ( rule.condition === undefined ) {
            rule.condition = {};
        } else if ( rule.condition.urlFilter !== undefined ) {
            dnrAddRuleError(rule, `urlFilter already defined: ${rule.condition.urlFilter}`);
        }
        rule.condition.urlFilter = args[1];
    }

    static logData(idata, details) {
        const s = bidiTrie.extractString(
            filterData[idata+1],
            filterData[idata+2]
        );
        details.pattern.push(s);
        details.regex.push(restrFromPlainPattern(s));
        // https://github.com/gorhill/uBlock/issues/3037
        //   Make sure the logger reflects accurately internal match, taking
        //   into account MAX_TOKEN_LENGTH.
        if ( /^[0-9a-z%]{1,6}$/i.exec(s.slice(filterData[idata+3])) !== null ) {
            details.regex.push('(?![0-9A-Za-z%])');
        }
    }

    static dumpInfo(idata) {
        const pattern = bidiTrie.extractString(
            filterData[idata+1],
            filterData[idata+2]
        );
        return `${pattern} ${filterData[idata+3]}`;
    }
}

FilterPatternPlain.isPatternPlain = true;

registerFilterClass(FilterPatternPlain);


class FilterPatternPlain1 extends FilterPatternPlain {
    static match(idata) {
        const left = $tokenBeg - 1;
        const n = filterData[idata+2];
        if (
            bidiTrie.startsWith(
                left,
                bidiTrie.getHaystackLen(),
                filterData[idata+1],
                n
            ) === 0
        ) {
            return false;
        }
        $patternMatchLeft = left;
        $patternMatchRight = left + n;
        return true;
    }
}

registerFilterClass(FilterPatternPlain1);


class FilterPatternPlainX extends FilterPatternPlain {
    static match(idata) {
        const left = $tokenBeg - filterData[idata+3];
        const n = filterData[idata+2];
        if (
            bidiTrie.startsWith(
                left,
                bidiTrie.getHaystackLen(),
                filterData[idata+1],
                n
            ) === 0
        ) {
            return false;
        }
        $patternMatchLeft = left;
        $patternMatchRight = left + n;
        return true;
    }
}

registerFilterClass(FilterPatternPlainX);

/******************************************************************************/

class FilterPatternGeneric {
    static hasRegexPattern() {
        return true;
    }

    static getRegexPattern(idata) {
        return restrFromGenericPattern(
            bidiTrie.extractString(
                filterData[idata+1],
                filterData[idata+2]
            ),
            filterData[idata+3]
        );
    }

    static match(idata) {
        const refs = filterRefs[filterData[idata+4]];
        if ( refs.$re === null ) {
            refs.$re = new RegExp(this.getRegexPattern(idata));
        }
        return refs.$re.test($requestURL);
    }

    static compile(details) {
        const out = [
            FilterPatternGeneric.fid,
            details.pattern,
            details.anchor,
        ];
        details.anchor = 0;
        return out;
    }

    static fromCompiled(args) {
        const idata = filterDataAllocLen(5);
        filterData[idata+0] = args[0];                          // fid
        filterData[idata+1] = bidiTrie.storeString(args[1]);    // i
        filterData[idata+2] = args[1].length;                   // n
        filterData[idata+3] = args[2];                          // anchor
        filterData[idata+4] = filterRefAdd({ $re: null });
        return idata;
    }

    static dnrFromCompiled(args, rule) {
        if ( rule.condition === undefined ) {
            rule.condition = {};
        } else if ( rule.condition.urlFilter !== undefined ) {
            dnrAddRuleError(rule, `urlFilter already defined: ${rule.condition.urlFilter}`);
        }
        let pattern = args[1];
        if ( args[2] & 0b100 ) {
            if ( pattern.startsWith('.') ) {
                pattern = `*${pattern}`;
            }
            pattern = `||${pattern}`;
        } else if ( args[2] & 0b010 ) {
            pattern = `|${pattern}`;
        }
        if ( args[2] & 0b001 ) {
            pattern += '|';
        }
        rule.condition.urlFilter = pattern;
    }

    static keyFromArgs(args) {
        return `${args[1]}\t${args[2]}`;
    }

    static logData(idata, details) {
        details.pattern.length = 0;
        const anchor = filterData[idata+3];
        if ( (anchor & 0b100) !== 0 ) {
            details.pattern.push('||');
        } else if ( (anchor & 0b010) !== 0 ) {
            details.pattern.push('|');
        }
        const s = bidiTrie.extractString(
            filterData[idata+1],
            filterData[idata+2]
        );
        details.pattern.push(s);
        if ( (anchor & 0b001) !== 0 ) {
            details.pattern.push('|');
        }
        details.regex.length = 0;
        details.regex.push(restrFromGenericPattern(s, anchor & ~0b100));
    }

    static dumpInfo(idata) {
        return bidiTrie.extractString(
            filterData[idata+1],
            filterData[idata+2]
        );
    }
}

FilterPatternGeneric.isSlow = true;

registerFilterClass(FilterPatternGeneric);

/******************************************************************************/

class FilterAnchorHnLeft {
    static match(idata) {
        const len = $requestHostname.length;
        const haystackCodes = bidiTrie.haystack;
        let lastBeg = filterData[idata+2];
        let lastEnd = filterData[idata+3];
        if (
            len !== filterData[idata+1] ||
            lastBeg === -1 ||
            haystackCodes[lastBeg-3] !== 0x3A /* ':' */ ||
            haystackCodes[lastBeg-2] !== 0x2F /* '/' */ ||
            haystackCodes[lastBeg-1] !== 0x2F /* '/' */
        ) {
            lastBeg = len !== 0 ? haystackCodes.indexOf(0x3A) : -1;
            if ( lastBeg !== -1 ) {
                if (
                    lastBeg >= bidiTrie.getHaystackLen() ||
                    haystackCodes[lastBeg+1] !== 0x2F ||
                    haystackCodes[lastBeg+2] !== 0x2F
                ) {
                    lastBeg = -1;
                }
            }
            if ( lastBeg !== -1 ) {
                lastBeg += 3;
                lastEnd = lastBeg + len;
            } else {
                lastEnd = -1;
            }
            filterData[idata+1] = len;
            filterData[idata+2] = lastBeg;
            filterData[idata+3] = lastEnd;
        }
        const left = $patternMatchLeft;
        return left < lastEnd && (
            left === lastBeg ||
            left > lastBeg && haystackCodes[left-1] === 0x2E /* '.' */
        );
    }

    static compile() {
        return [ FilterAnchorHnLeft.fid ];
    }

    static fromCompiled(args) {
        const idata = filterDataAllocLen(4);
        filterData[idata+0] = args[0];  // fid
        filterData[idata+1] = 0;        // lastLen
        filterData[idata+2] = -1;       // lastBeg
        filterData[idata+3] = -1;       // lastEnd
        return idata;
    }

    static dnrFromCompiled(args, rule) {
        rule.condition.urlFilter = `||${rule.condition.urlFilter}`;
    }

    static keyFromArgs() {
    }

    static logData(idata, details) {
        details.pattern.unshift('||');
    }
}

registerFilterClass(FilterAnchorHnLeft);

/******************************************************************************/

class FilterAnchorHn extends FilterAnchorHnLeft {
    static match(idata) {
        return super.match(idata) && filterData[idata+3] === $patternMatchRight;
    }

    static compile() {
        return [ FilterAnchorHn.fid ];
    }

    static dnrFromCompiled(args, rule) {
        rule.condition.requestDomains = [ rule.condition.urlFilter ];
        rule.condition.urlFilter = undefined;
    }

    static keyFromArgs() {
    }

    static logData(idata, details) {
        super.logData(idata, details);
        details.pattern.push('^');
        details.regex.push('\\.?', restrSeparator);
    }
}

registerFilterClass(FilterAnchorHn);

/******************************************************************************/

class FilterAnchorLeft {
    static match() {
        return $patternMatchLeft === 0;
    }

    static compile() {
        return [ FilterAnchorLeft.fid ];
    }

    static fromCompiled(args) {
        return filterDataAlloc(args[0]);
    }

    static dnrFromCompiled(args, rule) {
        rule.condition.urlFilter = `|${rule.condition.urlFilter}`;
    }

    static keyFromArgs() {
    }

    static logData(idata, details) {
        details.pattern.unshift('|');
        details.regex.unshift('^');
    }
}

registerFilterClass(FilterAnchorLeft);

/******************************************************************************/

class FilterAnchorRight {
    static match() {
        return $patternMatchRight === $requestURL.length;
    }

    static compile() {
        return [ FilterAnchorRight.fid ];
    }

    static fromCompiled(args) {
        return filterDataAlloc(args[0]);
    }

    static dnrFromCompiled(args, rule) {
        rule.condition.urlFilter = `${rule.condition.urlFilter}|`;
    }

    static keyFromArgs() {
    }

    static logData(idata, details) {
        details.pattern.push('|');
        details.regex.push('$');
    }
}

registerFilterClass(FilterAnchorRight);

/******************************************************************************/

class FilterTrailingSeparator {
    static match() {
        if ( $patternMatchRight === $requestURL.length ) { return true; }
        if ( isSeparatorChar(bidiTrie.haystack[$patternMatchRight]) ) {
            $patternMatchRight += 1;
            return true;
        }
        return false;
    }

    static compile() {
        return [ FilterTrailingSeparator.fid ];
    }

    static fromCompiled(args) {
        return filterDataAlloc(args[0]);
    }

    static dnrFromCompiled(args, rule) {
        rule.condition.urlFilter = `${rule.condition.urlFilter}^`;
    }

    static keyFromArgs() {
    }

    static logData(idata, details) {
        details.pattern.push('^');
        details.regex.push(restrSeparator);
    }
}

registerFilterClass(FilterTrailingSeparator);

/******************************************************************************/

class FilterRegex {
    static hasRegexPattern() {
        return true;
    }

    static getRegexPattern(idata) {
        return bidiTrie.extractString(
            filterData[idata+1],
            filterData[idata+2]
        );
    }

    static match(idata) {
        const refs = filterRefs[filterData[idata+4]];
        if ( refs.$re === null ) {
            refs.$re = new RegExp(
                this.getRegexPattern(idata),
                filterData[idata+3] === 0 ? 'i' : ''
            );
        }
        if ( refs.$re.test($requestURLRaw) === false ) { return false; }
        return true;
    }

    static compile(details) {
        return [
            FilterRegex.fid,
            details.pattern,
            details.optionValues.has('match-case') ? 1 : 0,
        ];
    }

    static fromCompiled(args) {
        const idata = filterDataAllocLen(5);
        filterData[idata+0] = args[0];                          // fid
        filterData[idata+1] = bidiTrie.storeString(args[1]);    // i
        filterData[idata+2] = args[1].length;                   // n
        filterData[idata+3] = args[2];                          // match-case
        filterData[idata+4] = filterRefAdd({ $re: null });
        return idata;
    }

    static dnrFromCompiled(args, rule) {
        if ( rule.condition === undefined ) {
            rule.condition = {};
        }
        if ( isRE2(args[1]) === false ) {
            dnrAddRuleError(rule, `regexFilter is not RE2-compatible: ${args[1]}`);
        }
        rule.condition.regexFilter = args[1];
        if ( args[2] === 1 ) {
            rule.condition.isUrlFilterCaseSensitive = true;
        }
    }

    static keyFromArgs(args) {
        return `${args[1]}\t${args[2]}`;
    }

    static logData(idata, details) {
        const s = bidiTrie.extractString(
            filterData[idata+1],
            filterData[idata+2]
        );
        details.pattern.push('/', s, '/');
        details.regex.push(s);
        details.isRegex = true;
        if ( filterData[idata+3] !== 0 ) {
            details.options.push('match-case');
        }
    }

    static dumpInfo(idata) {
        return [
            '/',
            bidiTrie.extractString(
                filterData[idata+1],
                filterData[idata+2]
            ),
            '/',
            filterData[idata+3] !== 0 ? ' (match-case)' : '',
        ].join('');
    }
}

FilterRegex.isSlow = true;

registerFilterClass(FilterRegex);

/******************************************************************************/

class FilterMethod {
    static match(idata) {
        if ( $requestMethodBit === 0 ) { return false; }
        const methodBits = filterData[idata+1];
        const notMethodBits = filterData[idata+2];
        return (methodBits !== 0 && ($requestMethodBit & methodBits) !== 0) ||
               (notMethodBits !== 0 && ($requestMethodBit & notMethodBits) === 0);
    }

    static compile(details) {
        return [ FilterMethod.fid, details.methodBits, details.notMethodBits ];
    }

    static fromCompiled(args) {
        const idata = filterDataAllocLen(3);
        filterData[idata+0] = args[0];  // fid
        filterData[idata+1] = args[1];  // methodBits
        filterData[idata+2] = args[2];  // notMethodBits
        return idata;
    }

    static dnrFromCompiled(args, rule) {
        rule.condition = rule.condition || {};
        const rc = rule.condition;
        let methodBits = args[1];
        let notMethodBits = args[2];
        if ( methodBits !== 0 && rc.requestMethods === undefined ) {
            rc.requestMethods = [];
        }
        if ( notMethodBits !== 0 && rc.excludedRequestMethods === undefined ) {
            rc.excludedRequestMethods = [];
        }
        for ( let i = 1; methodBits !== 0 || notMethodBits !== 0; i++ ) {
            const bit = 1 << i;
            const methodName = FilteringContext.getMethodName(bit);
            if ( (methodBits & bit) !== 0 ) {
                methodBits &= ~bit;
                rc.requestMethods.push(methodName);
            } else if ( (notMethodBits & bit) !== 0 ) {
                notMethodBits &= ~bit;
                rc.excludedRequestMethods.push(methodName);
            }
        }
    }

    static keyFromArgs(args) {
        return `${args[1]} ${args[2]}`;
    }

    static logData(idata, details) {
        const methods = [];
        let methodBits = filterData[idata+1];
        let notMethodBits = filterData[idata+2];
        for ( let i = 0; methodBits !== 0 || notMethodBits !== 0; i++ ) {
            const bit = 1 << i;
            const methodName = FilteringContext.getMethodName(bit);
            if ( (methodBits & bit) !== 0 ) {
                methodBits &= ~bit;
                methods.push(methodName);
            } else if ( (notMethodBits & bit) !== 0 ) {
                notMethodBits &= ~bit;
                methods.push(`~${methodName}`);
            }
        }
        details.options.push(`method=${methods.join('|')}`);
    }

    static dumpInfo(idata) {
        return `0b${filterData[idata+1].toString(2)} 0b${filterData[idata+2].toString(2)}`;
    }
}

registerFilterClass(FilterMethod);

/******************************************************************************/

// stylesheet: 1 => bit 0
// image: 2 => bit 1
// object: 3 => bit 2
// script: 4 => bit 3
// ...

class FilterNotType {
    static match(idata) {
        return $requestTypeValue !== 0 &&
            (filterData[idata+1] & (1 << ($requestTypeValue - 1))) === 0;
    }

    static compile(details) {
        return [ FilterNotType.fid, details.notTypeBits ];
    }

    static fromCompiled(args) {
        const idata = filterDataAllocLen(2);
        filterData[idata+0] = args[0];  // fid
        filterData[idata+1] = args[1];  // notTypeBits
        return idata;
    }

    static dnrFromCompiled(args, rule) {
        rule.condition = rule.condition || {};
        const rc = rule.condition;
        if ( rc.excludedResourceTypes === undefined ) {
            rc.excludedResourceTypes = [ 'main_frame' ];
        }
        let bits = args[1];
        for ( let i = 1; bits !== 0 && i < typeValueToDNRTypeName.length; i++ ) {
            const bit = 1 << (i - 1);
            if ( (bits & bit) === 0 ) { continue; }
            bits &= ~bit;
            const type = typeValueToDNRTypeName[i];
            if ( type === undefined ) { continue; }
            if ( rc.excludedResourceTypes.includes(type) ) { continue; }
            rc.excludedResourceTypes.push(type);
        }
    }

    static keyFromArgs(args) {
        return `${args[1]}`;
    }

    static logData(idata, details) {
        let bits = filterData[idata+1];
        for ( let i = 1; bits !== 0 && i < typeValueToTypeName.length; i++ ) {
            const bit = 1 << (i - 1);
            if ( (bits & bit) === 0 ) { continue; }
            bits &= ~bit;
            details.options.push(`~${typeValueToTypeName[i]}`);
        }
    }

    static dumpInfo(idata) {
        return `0b${filterData[idata+1].toString(2)}`;
    }
}

registerFilterClass(FilterNotType);

/******************************************************************************/

// A helper class to parse `domain=` option.

class DomainOptIterator {
    constructor(domainOpt) {
        this.reset(domainOpt);
    }
    reset(domainOpt) {
        this.domainOpt = domainOpt;
        this.i = 0;
        this.value = undefined;
        this.done = false;
        return this;
    }
    next() {
        if ( this.i === -1 ) {
            this.domainOpt = '';
            this.value = undefined;
            this.done = true;
            return this;
        }
        const pos = this.domainOpt.indexOf('|', this.i);
        if ( pos !== -1 ) {
            this.value = this.domainOpt.slice(this.i, pos);
            this.i = pos + 1;
        } else {
            this.value = this.domainOpt.slice(this.i);
            this.i = -1;
        }
        return this;
    }
    [Symbol.iterator]() {
        return this;
    }
}

// A helper instance to reuse throughout
const domainOptIterator = new DomainOptIterator('');

/******************************************************************************/

// The optimal class is picked according to the content of the `from=`
// filter option.
const compileDomainOpt = (ctors, iterable, prepend, units) => {
    const hostnameHits = [];
    const hostnameMisses = [];
    const entityHits = [];
    const entityMisses = [];
    const regexHits = [];
    const regexMisses = [];
    for ( const s of iterable ) {
        const len = s.length;
        const beg = len > 1 && s.charCodeAt(0) === 0x7E /* '~' */ ? 1 : 0;
        if ( len <= beg ) {  continue; }
        if ( s.charCodeAt(beg) === 0x2F /* / */ ) {
            if ( beg === 0 ) { regexHits.push(s); continue; }
            regexMisses.push(s.slice(1)); continue;
        }
        if ( s.endsWith('.*') === false ) {
            if ( beg === 0 ) { hostnameHits.push(s); continue; }
            hostnameMisses.push(s.slice(1)); continue;
        }
        if ( beg === 0 ) { entityHits.push(s); continue; }
        entityMisses.push(s.slice(1)); continue;
    }
    const toTrie = [];
    let trieWhich = 0b00;
    if ( hostnameHits.length > 1 ) {
        toTrie.push(...hostnameHits);
        hostnameHits.length = 0;
        trieWhich |= 0b01;
    }
    if ( entityHits.length > 1 ) {
        toTrie.push(...entityHits);
        entityHits.length = 0;
        trieWhich |= 0b10;
    }
    const compiledHit = [];
    if ( toTrie.length !== 0 ) {
        compiledHit.push(
            ctors[2].compile(toTrie.sort(), trieWhich)
        );
    }
    for ( const hn of hostnameHits ) {
        compiledHit.push(ctors[0].compile(hn));
    }
    for ( const hn of entityHits ) {
        compiledHit.push(ctors[1].compile(hn));
    }
    for ( const hn of regexHits ) {
        compiledHit.push(ctors[3].compile(hn));
    }
    if ( compiledHit.length > 1 ) {
        compiledHit[0] = FilterDomainHitAny.compile(compiledHit.slice());
        compiledHit.length = 1;
    }
    toTrie.length = trieWhich = 0;
    if ( hostnameMisses.length > 1 ) {
        toTrie.push(...hostnameMisses);
        hostnameMisses.length = 0;
        trieWhich |= 0b01;
    }
    if ( entityMisses.length > 1 ) {
        toTrie.push(...entityMisses);
        entityMisses.length = 0;
        trieWhich |= 0b10;
    }
    const compiledMiss = [];
    if ( toTrie.length !== 0 ) {
        compiledMiss.push(
            ctors[6].compile(toTrie.sort(), trieWhich)
        );
    }
    for ( const hn of hostnameMisses ) {
        compiledMiss.push(ctors[4].compile(hn));
    }
    for ( const hn of entityMisses ) {
        compiledMiss.push(ctors[5].compile(hn));
    }
    for ( const hn of regexMisses ) {
        compiledMiss.push(ctors[7].compile(hn));
    }
    if ( prepend ) {
        if ( compiledHit.length !== 0 ) {
            units.unshift(compiledHit[0]);
        }
        if ( compiledMiss.length !== 0 ) {
            units.unshift(...compiledMiss);
        }
    } else {
        if ( compiledMiss.length !== 0 ) {
            units.push(...compiledMiss);
        }
        if ( compiledHit.length !== 0 ) {
            units.push(compiledHit[0]);
        }
    }
};

/******************************************************************************/

class FilterDomainHit {
    static getDomainOpt(idata) {
        return this.hntrieContainer.extractHostname(
            filterData[idata+1],
            filterData[idata+2]
        );
    }

    static match(idata) {
        return this.hntrieContainer.matchesHostname(
            this.getMatchTarget(),
            filterData[idata+1],
            filterData[idata+2]
        );
    }

    static compile(hostname) {
        return [ this.fid, hostname ];
    }

    static fromCompiled(args) {
        const idata = filterDataAllocLen(3);
        filterData[idata+0] = args[0];                                     // fid
        filterData[idata+1] = this.hntrieContainer.storeHostname(args[1]); // i
        filterData[idata+2] = args[1].length;                              // n
        return idata;
    }

    static dnrFromCompiled(args, rule) {
        rule.condition = rule.condition || {};
        const prop = this.dnrConditionName;
        if ( rule.condition[prop] === undefined ) {
            rule.condition[prop] = [];
        }
        rule.condition[prop].push(args[1]);
    }

    static dumpInfo(idata) {
        return this.getDomainOpt(idata);
    }
}

/******************************************************************************/

class FilterDomainHitSet {
    static getDomainOpt(idata) {
        return this.hntrieContainer.extractDomainOpt(
            filterData[idata+1],
            filterData[idata+2]
        );
    }

    static getTrieCount(idata) {
        const itrie = filterData[idata+4];
        if ( itrie === 0 ) { return 0; }
        return Array.from(
            this.hntrieContainer.trieIterator(filterData[idata+4])
        ).length;
    }

    static getLastResult(idata) {
        return filterData[idata+5];
    }

    static getMatchedHostname(idata) {
        const lastResult = filterData[idata+5];
        if ( lastResult === -1 ) { return ''; }
        return this.getMatchTarget(lastResult >>> 8).slice(lastResult & 0xFF);
    }

    static match(idata) {
        const refs = filterRefs[filterData[idata+6]];
        const docHostname = this.getMatchTarget(0b01);
        if ( docHostname === refs.$last ) {
            return filterData[idata+5] !== -1;
        }
        refs.$last = docHostname;
        const which = filterData[idata+3];
        const itrie = filterData[idata+4] || this.toTrie(idata);
        if ( itrie === 0 ) { return false; }
        if ( (which & 0b01) !== 0 ) {
            const pos = this.hntrieContainer
                .setNeedle(docHostname)
                .matches(itrie);
            if ( pos !== -1 ) {
                filterData[idata+5] = 0b01 << 8 | pos;
                return true;
            }
        }
        if ( (which & 0b10) !== 0 ) {
            const pos = this.hntrieContainer
                .setNeedle(this.getMatchTarget(0b10))
                .matches(itrie);
            if ( pos !== -1 ) {
                filterData[idata+5] = 0b10 << 8 | pos;
                return true;
            }
        }
        filterData[idata+5] = -1;
        return false;
    }

    static add(idata, hn) {
        this.hntrieContainer.setNeedle(hn).add(filterData[idata+4]);
        filterData[idata+3] |= hn.charCodeAt(hn.length - 1) !== 0x2A /* '*' */
            ? 0b01
            : 0b10;
        filterData[idata+5] = -1;
        filterRefs[filterData[idata+6]].$last = '';
    }

    static create(fid = -1) {
        const idata = filterDataAllocLen(7);
        filterData[idata+0] = fid !== -1 ? fid : this.fid;
        filterData[idata+1] = 0;
        filterData[idata+2] = 0;
        filterData[idata+3] = 0;
        filterData[idata+4] = this.hntrieContainer.createTrie();
        filterData[idata+5] = -1;           // $lastResult
        filterData[idata+6] = filterRefAdd({ $last: '' });
        return idata;
    }

    static compile(hostnames, which) {
        const stringified = Array.isArray(hostnames)
            ? hostnames.join('|')
            : hostnames;
        return [ this.fid, stringified, which ];
    }

    static fromCompiled(args) {
        const idata = filterDataAllocLen(7);
        filterData[idata+0] = args[0];      // fid
        filterData[idata+1] = this.hntrieContainer.storeDomainOpt(args[1]);
        filterData[idata+2] = args[1].length;
        filterData[idata+3] = args[2];      // which
        filterData[idata+4] = 0;            // itrie
        filterData[idata+5] = -1;           // $lastResult
        filterData[idata+6] = filterRefAdd({ $last: '' });
        return idata;
    }

    static dnrFromCompiled(args, rule) {
        rule.condition = rule.condition || {};
        const prop = this.dnrConditionName;
        if ( rule.condition[prop] === undefined ) {
            rule.condition[prop] = [];
        }
        rule.condition[prop].push(...args[1].split('|'));
    }

    static toTrie(idata) {
        if ( filterData[idata+2] === 0 ) { return 0; }
        const itrie = filterData[idata+4] =
            this.hntrieContainer.createTrieFromStoredDomainOpt(
                filterData[idata+1],
                filterData[idata+2]
            );
        return itrie;
    }

    static keyFromArgs(args) {
        return args[1];
    }

    static dumpInfo(idata) {
        return `0b${filterData[idata+3].toString(2)} ${this.getDomainOpt(idata)}`;
    }
}

/******************************************************************************/

class FilterDomainRegexHit {
    static getDomainOpt(idata) {
        const ref = filterRefs[filterData[idata+1]];
        return ref.restr;
    }

    static match(idata) {
        const ref = filterRefs[filterData[idata+1]];
        if ( ref.$re === null ) {
            ref.$re = new RegExp(ref.restr.slice(1,-1));
        }
        return ref.$re.test(this.getMatchTarget());
    }

    static compile(restr) {
        return [ this.fid, restr ];
    }

    static fromCompiled(args) {
        const idata = filterDataAllocLen(2);
        filterData[idata+0] = args[0];  // fid
        filterData[idata+1] = filterRefAdd({ restr: args[1], $re: null });
        return idata;
    }

    static dnrFromCompiled(args, rule) {
        rule.condition = rule.condition || {};
        const prop = this.dnrConditionName;
        if ( rule.condition[prop] === undefined ) {
            rule.condition[prop] = [];
        }
        rule.condition[prop].push(args[1]);
    }

    static dumpInfo(idata) {
        return this.getDomainOpt(idata);
    }
}

/******************************************************************************/

// Implement the following filter option:
// - domain=
// - from=

class FilterFromDomainHit extends FilterDomainHit {
    static hasOriginHit() {
        return true;
    }

    static getMatchTarget() {
        return $docHostname;
    }

    static get dnrConditionName() {
        return 'initiatorDomains';
    }

    static logData(idata, details) {
        details.fromDomains.push(this.getDomainOpt(idata));
    }
}
Object.defineProperty(FilterFromDomainHit, 'hntrieContainer', {
    value: origHNTrieContainer
});

class FilterFromDomainMiss extends FilterFromDomainHit {
    static hasOriginHit() {
        return false;
    }

    static get dnrConditionName() {
        return 'excludedInitiatorDomains';
    }

    static match(idata) {
        return super.match(idata) === false;
    }

    static logData(idata, details) {
        details.fromDomains.push(`~${this.getDomainOpt(idata)}`);
    }
}

class FilterFromEntityHit extends FilterFromDomainHit {
    static getMatchTarget() {
        return $docEntity.compute();
    }
}

class FilterFromEntityMiss extends FilterFromDomainMiss {
    static getMatchTarget() {
        return $docEntity.compute();
    }
}

class FilterFromDomainHitSet extends FilterDomainHitSet {
    static hasOriginHit() {
        return true;
    }

    static getMatchTarget(which) {
        return (which & 0b01) !== 0
            ? $docHostname
            : $docEntity.compute();
    }

    static get dnrConditionName() {
        return 'initiatorDomains';
    }

    static logData(idata, details) {
        details.fromDomains.push(this.getDomainOpt(idata));
    }
}
Object.defineProperty(FilterFromDomainHitSet, 'hntrieContainer', {
    value: origHNTrieContainer
});

class FilterFromDomainMissSet extends FilterFromDomainHitSet {
    static hasOriginHit() {
        return false;
    }

    static match(idata) {
        return super.match(idata) === false;
    }

    static get dnrConditionName() {
        return 'excludedInitiatorDomains';
    }

    static logData(idata, details) {
        details.fromDomains.push('~' + this.getDomainOpt(idata).replace(/\|/g, '|~'));
    }
}

class FilterFromRegexHit extends FilterDomainRegexHit {
    static getMatchTarget() {
        return $docHostname;
    }

    static get dnrConditionName() {
        return 'initiatorDomains';
    }

    static logData(idata, details) {
        details.fromDomains.push(`${this.getDomainOpt(idata)}`);
    }
}

class FilterFromRegexMiss extends FilterFromRegexHit {
    static match(idata) {
        return super.match(idata) === false;
    }

    static get dnrConditionName() {
        return 'excludedInitiatorDomains';
    }

    static logData(idata, details) {
        details.fromDomains.push(`~${this.getDomainOpt(idata)}`);
    }
}

registerFilterClass(FilterFromDomainHit);
registerFilterClass(FilterFromDomainMiss);
registerFilterClass(FilterFromEntityHit);
registerFilterClass(FilterFromEntityMiss);
registerFilterClass(FilterFromDomainHitSet);
registerFilterClass(FilterFromDomainMissSet);
registerFilterClass(FilterFromRegexHit);
registerFilterClass(FilterFromRegexMiss);

const fromOptClasses = [
    FilterFromDomainHit,
    FilterFromEntityHit,
    FilterFromDomainHitSet,
    FilterFromRegexHit,
    FilterFromDomainMiss,
    FilterFromEntityMiss,
    FilterFromDomainMissSet,
    FilterFromRegexMiss,
];

const compileFromDomainOpt = (...args) => {
    return compileDomainOpt(fromOptClasses, ...args);
};

/******************************************************************************/

// Implement the following filter option:
// - to=

class FilterToDomainHit extends FilterDomainHit {
    static getMatchTarget() {
        return $requestHostname;
    }

    static get dnrConditionName() {
        return 'requestDomains';
    }

    static logData(idata, details) {
        details.toDomains.push(this.getDomainOpt(idata));
    }
}
Object.defineProperty(FilterToDomainHit, 'hntrieContainer', {
    value: destHNTrieContainer
});

class FilterToDomainMiss extends FilterToDomainHit {
    static get dnrConditionName() {
        return 'excludedRequestDomains';
    }

    static match(idata) {
        return super.match(idata) === false;
    }

    static logData(idata, details) {
        details.toDomains.push(`~${this.getDomainOpt(idata)}`);
    }
}

class FilterToEntityHit extends FilterToDomainHit {
    static getMatchTarget() {
        return $requestEntity.compute();
    }
}

class FilterToEntityMiss extends FilterToDomainMiss {
    static getMatchTarget() {
        return $requestEntity.compute();
    }
}

class FilterToDomainHitSet extends FilterDomainHitSet {
    static getMatchTarget(which) {
        return (which & 0b01) !== 0
            ? $requestHostname
            : $requestEntity.compute();
    }

    static get dnrConditionName() {
        return 'requestDomains';
    }

    static logData(idata, details) {
        details.toDomains.push(this.getDomainOpt(idata));
    }
}
Object.defineProperty(FilterToDomainHitSet, 'hntrieContainer', {
    value: destHNTrieContainer
});

class FilterToDomainMissSet extends FilterToDomainHitSet {
    static match(idata) {
        return super.match(idata) === false;
    }

    static get dnrConditionName() {
        return 'excludedRequestDomains';
    }

    static logData(idata, details) {
        details.toDomains.push('~' + this.getDomainOpt(idata).replace(/\|/g, '|~'));
    }
}

class FilterToRegexHit extends FilterDomainRegexHit {
    static getMatchTarget() {
        return $requestHostname;
    }

    static get dnrConditionName() {
        return 'requestDomains';
    }

    static logData(idata, details) {
        details.toDomains.push(`${this.getDomainOpt(idata)}`);
    }
}

class FilterToRegexMiss extends FilterToRegexHit {
    static match(idata) {
        return super.match(idata) === false;
    }

    static get dnrConditionName() {
        return 'excludedRequestDomains';
    }

    static logData(idata, details) {
        details.toDomains.push(`~${this.getDomainOpt(idata)}`);
    }
}

registerFilterClass(FilterToDomainHit);
registerFilterClass(FilterToDomainMiss);
registerFilterClass(FilterToEntityHit);
registerFilterClass(FilterToEntityMiss);
registerFilterClass(FilterToDomainHitSet);
registerFilterClass(FilterToDomainMissSet);
registerFilterClass(FilterToRegexHit);
registerFilterClass(FilterToRegexMiss);

const toOptClasses = [
    FilterToDomainHit,
    FilterToEntityHit,
    FilterToDomainHitSet,
    FilterToRegexHit,
    FilterToDomainMiss,
    FilterToEntityMiss,
    FilterToDomainMissSet,
    FilterToRegexMiss,
];

const compileToDomainOpt = (...args) => {
    return compileDomainOpt(toOptClasses, ...args);
};

/******************************************************************************/

class FilterDenyAllow extends FilterToDomainMissSet {
    static compile(details) {
        return super.compile(details.optionValues.get('denyallow'), 0b01);
    }

    static logData(idata, details) {
        details.denyallow.push(this.getDomainOpt(idata));
    }
}

registerFilterClass(FilterDenyAllow);

/******************************************************************************/

class FilterModifier {
    static getModifierType(idata) {
        return filterData[idata+2];
    }

    static match() {
        return true;
    }

    static matchAndFetchModifiers(idata, env) {
        if ( this.getModifierType(idata) !== env.type ) { return; }
        env.results.push(new FilterModifierResult(idata, env));
    }

    static compile(details) {
        return [
            FilterModifier.fid,
            details.action,
            details.modifyType,
            details.modifyValue || '',
        ];
    }

    static fromCompiled(args) {
        const idata = filterDataAllocLen(4);
        filterData[idata+0] = args[0];          // fid
        filterData[idata+1] = args[1];          // actionBits
        filterData[idata+2] = args[2];          // type
        filterData[idata+3] = filterRefAdd({
            value: args[3],
            $cache: null,
        });
        return idata;
    }

    static dnrFromCompiled(args, rule) {
        rule.__modifierAction = args[1];
        rule.__modifierType = modifierNameFromType.get(args[2]);
        rule.__modifierValue = args[3];
    }

    static keyFromArgs(args) {
        return `${args[1]}\t${args[2]}\t${args[3]}`;
    }

    static logData(idata, details) {
        let opt = modifierNameFromType.get(filterData[idata+2]);
        const refs = filterRefs[filterData[idata+3]];
        if ( refs.value !== '' ) {
            opt += `=${LogData.requote(refs.value)}`;
        }
        details.options.push(opt);
    }

    static dumpInfo(idata) {
        const s = modifierNameFromType.get(filterData[idata+2]);
        const refs = filterRefs[filterData[idata+3]];
        if ( refs.value === '' ) { return s; }
        return `${s}=${refs.value}`;
    }
}

registerFilterClass(FilterModifier);

// Helper class for storing instances of FilterModifier which were found to
// be a match.

class FilterModifierResult {
    constructor(imodifierunit, env) {
        this.imodifierunit = imodifierunit;
        this.refs = filterRefs[filterData[imodifierunit+3]];
        this.ireportedunit = env.iunit;
        this.th = env.th;
        this.bits = (env.bits & ~BLOCKALLOW_REALM) | filterData[imodifierunit+1];
    }

    get result() {
        return (this.bits & ALLOW_REALM) === 0 ? 1 : 2;
    }

    get value() {
        return this.refs.value;
    }

    get cache() {
        return this.refs.$cache;
    }

    set cache(a) {
        this.refs.$cache = a;
    }

    logData() {
        const r = new LogData(this.bits, this.th, this.ireportedunit);
        r.result = this.result;
        r.modifier = true;
        return r;
    }
}

/******************************************************************************/

class FilterCollection {
    static getCount(idata) {
        let n = 0;
        this.forEach(idata, ( ) => { n += 1; });
        return n;
    }

    static forEach(idata, fn) {
        let i = filterData[idata+1];
        if ( i === 0 ) { return; }
        do {
            const iunit = filterData[i+0];
            const r = fn(iunit);
            if ( r !== undefined ) { return r; }
            i = filterData[i+1];
        } while ( i !== 0 );
    }

    static unshift(idata, iunit) {
        filterData[idata+1] = filterSequenceAdd(iunit, filterData[idata+1]);
    }

    static shift(idata) {
        filterData[idata+1] = filterData[filterData[idata+1]+1];
    }

    static create(fid = -1) {
        return filterDataAlloc(
            fid !== -1 ? fid : FilterCollection.fid,
            0
        );
    }

    static compile(fc, fdata) {
        return [ fc.fid, fdata ];
    }

    static fromCompiled(args) {
        const units = args[1];
        const n = units.length;
        let iunit, inext = 0;
        let i = n;
        while ( i-- ) {
            iunit = filterFromCompiled(units[i]);
            inext = filterSequenceAdd(iunit, inext);
        }
        const idata = filterDataAllocLen(2);
        filterData[idata+0] = args[0];  // fid
        filterData[idata+1] = inext;    // i
        return idata;
    }

    static dnrFromCompiled(args, rule) {
        for ( const unit of args[1] ) {
            dnrRuleFromCompiled(unit, rule);
        }
    }

    static logData(idata, details) {
        this.forEach(idata, iunit => {
            filterLogData(iunit, details);
        });
    }

    static dumpInfo(idata) {
        return this.getCount(idata);
    }
}

registerFilterClass(FilterCollection);

/******************************************************************************/

class FilterDomainHitAny extends FilterCollection {
    static getDomainOpt(idata) {
        const domainOpts = [];
        this.forEach(idata, iunit => {
            if ( filterHasOriginHit(iunit) !== true ) { return; }
            filterGetDomainOpt(iunit, domainOpts);
        });
        return domainOpts.join('|');
    }

    static hasOriginHit(idata) {
        this.forEach(idata, iunit => {
            if ( filterHasOriginHit(iunit) ) { return true; }
        });
        return false;
    }

    static match(idata) {
        let i = filterData[idata+1];
        while ( i !== 0 ) {
            if ( filterMatch(filterData[i+0]) ) { return true; }
            i = filterData[i+1];
        }
        return false;
    }

    static compile(fdata) {
        return super.compile(FilterDomainHitAny, fdata);
    }

    static fromCompiled(args) {
        return super.fromCompiled(args);
    }
}

registerFilterClass(FilterDomainHitAny);

/******************************************************************************/

class FilterCompositeAll extends FilterCollection {
    // FilterPatternPlain is assumed to be first filter in sequence. This can
    // be revisited if needed.
    static isBidiTrieable(idata) {
        return filterIsBidiTrieable(filterData[filterData[idata+1]+0]);
    }

    static toBidiTrie(idata) {
        const iseq = filterData[idata+1];
        const details = filterToBidiTrie(filterData[iseq+0]);
        this.shift(idata);
        return details;
    }

    static getDomainOpt(idata) {
        return this.forEach(idata, iunit => {
            if ( filterHasOriginHit(iunit) !== true ) { return; }
            return filterGetDomainOpt(iunit);
        });
    }

    static hasOriginHit(idata) {
        return this.forEach(idata, iunit => {
            if ( filterHasOriginHit(iunit) === true ) { return true; }
        }) || false;
    }

    static hasRegexPattern(idata) {
        return this.forEach(idata, iunit => {
            const fc = filterGetClass(iunit);
            if ( fc.hasRegexPattern === undefined ) { return; }
            if ( fc.hasRegexPattern(iunit) === true ) { return true; }
        }) || false;
    }

    static getRegexPattern(idata) {
        return this.forEach(idata, iunit => {
            const fc = filterGetClass(iunit);
            if ( fc.getRegexPattern === undefined ) { return; }
            return fc.getRegexPattern(iunit);
        });
    }

    static match(idata) {
        let i = filterData[idata+1];
        while ( i !== 0 ) {
            if ( filterMatch(filterData[i+0]) !== true ) {
                return false;
            }
            i = filterData[i+1];
        }
        return true;
    }

    // IMPORTANT: the modifier filter unit is assumed to be ALWAYS the
    // first unit in the sequence. This requirement ensures that we do
    // not have to traverse the sequence to find the modifier filter
    // unit.
    static getModifierType(idata) {
        const iseq = filterData[idata+1];
        const iunit = filterData[iseq+0];
        return filterGetModifierType(iunit);
    }

    static matchAndFetchModifiers(idata, env) {
        const iseq = filterData[idata+1];
        const iunit = filterData[iseq+0];
        if (
            filterGetModifierType(iunit) === env.type &&
            this.match(idata)
        ) {
            filterMatchAndFetchModifiers(iunit, env);
        }
    }

    static compile(fdata) {
        return super.compile(FilterCompositeAll, fdata);
    }

    static fromCompiled(args) {
        return super.fromCompiled(args);
    }
}

registerFilterClass(FilterCompositeAll);

/******************************************************************************/

// Dictionary of hostnames

class FilterHostnameDict {
    static getCount(idata) {
        const itrie = filterData[idata+1];
        if ( itrie !== 0 ) {
            return Array.from(destHNTrieContainer.trieIterator(itrie)).length;
        }
        return filterRefs[filterData[idata+3]].length;
    }

    static match(idata) {
        const itrie = filterData[idata+1] || this.optimize(idata);
        return (
            filterData[idata+2] = destHNTrieContainer
                .setNeedle($requestHostname)
                .matches(itrie)
        ) !== -1;
    }

    static add(idata, hn) {
        const itrie = filterData[idata+1];
        if ( itrie === 0 ) {
            filterRefs[filterData[idata+3]].push(hn);
        } else {
            destHNTrieContainer.setNeedle(hn).add(itrie);
        }
    }

    static optimize(idata) {
        const itrie = filterData[idata+1];
        if ( itrie !== 0 ) { return itrie; }
        const hostnames = filterRefs[filterData[idata+3]];
        filterData[idata+1] = destHNTrieContainer.createTrieFromIterable(hostnames);
        filterRefs[filterData[idata+3]] = null;
        return filterData[idata+1];
    }

    static create() {
        const idata = filterDataAllocLen(4);
        filterData[idata+0] = FilterHostnameDict.fid;   // fid
        filterData[idata+1] = 0;                        // itrie
        filterData[idata+2] = -1;                       // lastResult
        filterData[idata+3] = filterRefAdd([]);         // []: hostnames
        return idata;
    }

    static logData(idata, details) {
        const hostname = $requestHostname.slice(filterData[idata+2]);
        details.pattern.push('||', hostname, '^');
        details.regex.push(
            restrFromPlainPattern(hostname),
            '\\.?',
            restrSeparator
        );
    }

    static dumpInfo(idata) {
        return this.getCount(idata);
    }
}

registerFilterClass(FilterHostnameDict);

/******************************************************************************/

// Dictionary of hostnames for filters which only purpose is to match
// the document origin.

class FilterJustOrigin extends FilterFromDomainHitSet {
    static create(fid = -1) {
        return super.create(fid !== -1 ? fid : FilterJustOrigin.fid);
    }

    static logPattern(idata, details) {
        details.pattern.push('*');
        details.regex.push('^');
    }

    static logData(idata, details) {
        this.logPattern(idata, details);
        details.fromDomains.push(this.getMatchedHostname(idata));
    }

    static dumpInfo(idata) {
        return this.getTrieCount(idata);
    }
}

registerFilterClass(FilterJustOrigin);

/******************************************************************************/

class FilterHTTPSJustOrigin extends FilterJustOrigin {
    static match(idata) {
        return $requestURL.startsWith('https://') && super.match(idata);
    }

    static create() {
        return super.create(FilterHTTPSJustOrigin.fid);
    }

    static logPattern(idata, details) {
        details.pattern.push('|https://');
        details.regex.push('^https://');
    }
}

registerFilterClass(FilterHTTPSJustOrigin);

/******************************************************************************/

class FilterHTTPJustOrigin extends FilterJustOrigin {
    static match(idata) {
        return $requestURL.startsWith('http://') && super.match(idata);
    }

    static create() {
        return super.create(FilterHTTPJustOrigin.fid);
    }

    static logPattern(idata, details) {
        details.pattern.push('|http://');
        details.regex.push('^http://');
    }
}

registerFilterClass(FilterHTTPJustOrigin);

/******************************************************************************/

class FilterPlainTrie {
    static match(idata) {
        if ( bidiTrie.matches(filterData[idata+1], $tokenBeg) !== 0 ) {
            filterData[idata+2] = bidiTrie.$iu;
            return true;
        }
        return false;
    }

    static create() {
        const idata = filterDataAllocLen(3);
        filterData[idata+0] = FilterPlainTrie.fid;      // fid
        filterData[idata+1] = bidiTrie.createTrie();    // itrie
        filterData[idata+2] = 0;                        // matchedUnit
        return idata;
    }

    static addUnitToTrie(idata, iunit) {
        const trieDetails = filterToBidiTrie(iunit);
        const itrie = filterData[idata+1];
        const id = bidiTrie.add(
            itrie,
            trieDetails.i,
            trieDetails.n,
            trieDetails.itok
        );
        // No point storing a pattern with conditions if the bidi-trie already
        // contain a pattern with no conditions.
        const ix = bidiTrie.getExtra(id);
        if ( ix === 1 ) { return; }
        // If the newly stored pattern has no condition, short-circuit existing
        // ones since they will always be short-circuited by the condition-less
        // pattern.
        const fc = filterGetClass(iunit);
        if ( fc.isPatternPlain ) {
            bidiTrie.setExtra(id, 1);
            return;
        }
        // FilterCompositeAll is assumed here, i.e. with conditions.
        if ( fc === FilterCompositeAll && fc.getCount(iunit) === 1 ) {
            iunit = filterData[filterData[iunit+1]+0];
        }
        bidiTrie.setExtra(id, filterSequenceAdd(iunit, ix));
    }

    static logData(idata, details) {
        const s = $requestURL.slice(bidiTrie.$l, bidiTrie.$r);
        details.pattern.push(s);
        details.regex.push(restrFromPlainPattern(s));
        if ( filterData[idata+2] !== -1 ) {
            filterLogData(filterData[idata+2], details);
        }
    }

    static dumpInfo(idata) {
        return `${Array.from(bidiTrie.trieIterator(filterData[idata+1])).length}`;
    }
}

registerFilterClass(FilterPlainTrie);

/******************************************************************************/

class FilterBucket extends FilterCollection {
    static getCount(idata) {
        return filterData[idata+2];
    }

    static forEach(idata, fn) {
        return super.forEach(filterData[idata+1], fn);
    }

    static match(idata) {
        const icollection = filterData[idata+1];
        let iseq = filterData[icollection+1];
        while ( iseq !== 0 ) {
            const iunit = filterData[iseq+0];
            if ( filterMatch(iunit) ) {
                filterData[idata+3] = iunit;
                return true;
            }
            iseq = filterData[iseq+1];
        }
        return false;
    }

    static matchAndFetchModifiers(idata, env) {
        const icollection = filterData[idata+1];
        let iseq = filterData[icollection+1];
        while ( iseq !== 0 ) {
            const iunit = filterData[iseq+0];
            env.iunit = iunit;
            filterMatchAndFetchModifiers(iunit, env);
            iseq = filterData[iseq+1];
        }
    }

    static unshift(idata, iunit) {
        super.unshift(filterData[idata+1], iunit);
        filterData[idata+2] += 1;
    }

    static shift(idata) {
        super.shift(filterData[idata+1]);
        filterData[idata+2] -= 1;
    }

    static create() {
        const idata = filterDataAllocLen(4);
        filterData[idata+0] = FilterBucket.fid;             // fid
        filterData[idata+1] = FilterCollection.create();    // icollection
        filterData[idata+2] = 0;                            // n
        filterData[idata+3] = 0;                            // $matchedUnit
        return idata;
    }

    static logData(idata, details) {
        filterLogData(filterData[idata+3], details);
    }

    static optimize(idata, optimizeBits = 0b11) {
        if ( (optimizeBits & 0b01) !== 0 ) {
            if ( filterData[idata+2] >= 3 ) {
                const iplaintrie = this.optimizePatternTests(idata);
                if ( iplaintrie !== 0 ) {
                    const icollection = filterData[idata+1];
                    const i = filterData[icollection+1];
                    if ( i === 0 ) { return iplaintrie; }
                    this.unshift(idata, iplaintrie);
                }
            }
        }
        if ( (optimizeBits & 0b10) !== 0 ) {
            if ( filterData[idata+2] >= 5 ) {
                const ioptimized = this.optimizeMatch(
                    idata,
                    FilterBucketIfOriginHits,
                    5
                );
                if ( ioptimized !== 0 ) {
                    const icollection = filterData[idata+1];
                    const i = filterData[icollection+1];
                    if ( i === 0 ) { return ioptimized; }
                    this.unshift(idata, ioptimized);
                }
            }
            if ( filterData[idata+2] >= 5 ) {
                const ioptimized = this.optimizeMatch(
                    idata,
                    FilterBucketIfRegexHits,
                    5
                );
                if ( ioptimized !== 0 ) {
                    const icollection = filterData[idata+1];
                    const i = filterData[icollection+1];
                    if ( i === 0 ) { return ioptimized; }
                    this.unshift(idata, ioptimized);
                }
            }
        }
        return 0;
    }

    static optimizePatternTests(idata) {
        const isrccollection = filterData[idata+1];
        let n = 0;
        let iseq = filterData[isrccollection+1];
        do {
            if ( filterIsBidiTrieable(filterData[iseq+0]) ) { n += 1; }
            iseq = filterData[iseq+1];
        } while ( iseq !== 0 && n < 3 );
        if ( n < 3 ) { return 0; }
        const iplaintrie = FilterPlainTrie.create();
        iseq = filterData[isrccollection+1];
        let iprev = 0;
        for (;;) {
            const iunit = filterData[iseq+0];
            const inext = filterData[iseq+1];
            if ( filterIsBidiTrieable(iunit) ) {
                FilterPlainTrie.addUnitToTrie(iplaintrie, iunit);
                if ( iprev !== 0 ) {
                    filterData[iprev+1] = inext;
                } else {
                    filterData[isrccollection+1] = inext;
                }
                filterData[idata+2] -= 1;
            } else {
                iprev = iseq;
            }
            if ( inext === 0 ) { break; }
            iseq = inext;
        }
        return iplaintrie;
    }

    static optimizeMatch(idata, fc, min) {
        const isrccollection = filterData[idata+1];
        const candidates = [];
        this.forEach(idata, iunit => {
            if ( fc.canCoalesce(iunit) === false ) { return; }
            candidates.push(iunit);
        });
        if ( candidates.length < min ) { return 0; }
        const idesbucket = FilterBucket.create();
        const idescollection = filterData[idesbucket+1];
        let coalesced;
        let isrcseq = filterData[isrccollection+1];
        let iprev = 0;
        for (;;) {
            const iunit = filterData[isrcseq+0];
            const inext = filterData[isrcseq+1];
            if ( candidates.includes(iunit) ) {
                coalesced = fc.coalesce(iunit, coalesced);
                // move the sequence slot to new bucket
                filterData[isrcseq+1] = filterData[idescollection+1];
                filterData[idescollection+1] = isrcseq;
                filterData[idesbucket+2] += 1;
                if ( iprev !== 0 ) {
                    filterData[iprev+1] = inext;
                } else {
                    filterData[isrccollection+1] = inext;
                }
                filterData[idata+2] -= 1;
            } else {
                iprev = isrcseq;
            }
            if ( inext === 0 ) { break; }
            isrcseq = inext;
        }
        return fc.create(coalesced, idesbucket);
    }

    static dumpInfo(idata) {
        return this.getCount(idata);
    }
}

registerFilterClass(FilterBucket);

/******************************************************************************/

// Filter bucket objects which have a pre-test method before being treated
// as a plain filter bucket -- the pre-test method should be fast as it is
// used to avoid having to iterate through the content of the filter bucket.

class FilterBucketIf extends FilterBucket {
    static getCount(idata) {
        return super.getCount(filterData[idata+1]);
    }

    static forEach(idata, fn) {
        return super.forEach(filterData[idata+1], fn);
    }

    static match(idata) {
        return this.preTest(idata) && super.match(filterData[idata+1]);
    }

    static matchAndFetchModifiers(idata, env) {
        if ( this.preTest(idata) ) {
            super.matchAndFetchModifiers(filterData[idata+1], env);
        }
    }

    static create(fid, ibucket, itest) {
        const idata = filterDataAllocLen(3);
        filterData[idata+0] = fid;
        filterData[idata+1] = ibucket;
        filterData[idata+2] = itest;
        return idata;
    }

    static logData(idata, details) {
        filterLogData(filterData[idata+1], details);
    }
}

registerFilterClass(FilterBucketIf);

/******************************************************************************/

class FilterBucketIfOriginHits extends FilterBucketIf {
    static preTest(idata) {
        return filterMatch(filterData[idata+2]);
    }

    static canCoalesce(iunit) {
        return filterHasOriginHit(iunit);
    }

    static coalesce(iunit, coalesced) {
        if ( coalesced === undefined ) {
            coalesced = new Set();
        }
        const domainOpt = filterGetDomainOpt(iunit);
        if ( domainOpt.includes('|') ) {
            for ( const hn of domainOptIterator.reset(domainOpt) ) {
                coalesced.add(hn);
            }
        } else {
            coalesced.add(domainOpt);
        }
        return coalesced;
    }

    static create(coalesced, ibucket) {
        const units = [];
        compileFromDomainOpt(coalesced, false, units);
        const ihittest = filterFromCompiled(units[0]);
        const ipretest = super.create(
            FilterBucketIfOriginHits.fid,
            ibucket,
            ihittest
        );
        return ipretest;
    }
}

registerFilterClass(FilterBucketIfOriginHits);

/******************************************************************************/

class FilterBucketIfRegexHits extends FilterBucketIf {
    static preTest(idata) {
        return filterRefs[filterData[idata+2]].test($requestURLRaw);
    }

    static canCoalesce(iunit) {
        const fc = filterGetClass(iunit);
        if ( fc.hasRegexPattern === undefined ) { return false; }
        if ( fc.hasRegexPattern(iunit) !== true ) { return false; }
        return true;
    }

    static coalesce(iunit, coalesced) {
        if ( coalesced === undefined ) {
            coalesced = new Set();
        }
        coalesced.add(filterGetRegexPattern(iunit));
        return coalesced;
    }

    static create(coalesced, ibucket) {
        const reString = Array.from(coalesced).join('|');
        return super.create(
            FilterBucketIfRegexHits.fid,
            ibucket,
            filterRefAdd(new RegExp(reString, 'i'))
        );
    }

    static dumpInfo(idata) {
        return filterRefs[filterData[idata+2]].source;
    }
}

registerFilterClass(FilterBucketIfRegexHits);

/******************************************************************************/

class FilterStrictParty {
    // TODO: disregard `www.`?
    static match(idata) {
        return ($requestHostname === $docHostname) === (filterData[idata+1] === 0);
    }

    static compile(details) {
        return [
            FilterStrictParty.fid,
            details.strictParty > 0 ? 0 : 1
        ];
    }

    static fromCompiled(args) {
        return filterDataAlloc(
            args[0],    // fid
            args[1]
        );
    }

    static dnrFromCompiled(args, rule) {
        const partyness = args[1] === 0 ? 1 : 3;
        dnrAddRuleError(rule, `strict${partyness}p not supported`);
    }

    static keyFromArgs(args) {
        return `${args[1]}`;
    }

    static logData(idata, details) {
        details.options.push(
            filterData[idata+1] === 0 ? 'strict1p' : 'strict3p'
        );
    }
}

registerFilterClass(FilterStrictParty);

/******************************************************************************/

class FilterOnHeaders {
    static match(idata) {
        const refs = filterRefs[filterData[idata+1]];
        if ( refs.$parsed === null ) {
            refs.$parsed = sfp.parseHeaderValue(refs.headerOpt);
        }
        const { bad, name, not, value } = refs.$parsed;
        if ( bad ) { return false; }
        const headerValue = $httpHeaders.lookup(name);
        if ( headerValue === undefined ) { return false; }
        if ( value === '' ) { return true; }
        let { re } = refs.$parsed;
        if ( re === undefined ) {
            re = new RegExp(refs.$parsed.reStr, refs.$parsed.reFlags);
            refs.$parsed.re = re;
        }
        return re.test(headerValue) !== not;
    }

    static compile(details) {
        const parsed = sfp.parseHeaderValue(details.optionValues.get('header'));
        let normalized = parsed.name;
        if ( parsed.value !== '' ) {
            normalized += `:${parsed.value}`;
        }
        return [ FilterOnHeaders.fid, normalized ];
    }

    static fromCompiled(args) {
        return filterDataAlloc(
            args[0], // fid
            filterRefAdd({
                headerOpt: args[1],
                $parsed: null,
            })
        );
    }

    static dnrFromCompiled(args, rule) {
        rule.condition ||= {};
        const parsed = sfp.parseHeaderValue(args[1]);
        if ( parsed.bad !== true ) {
            const value = parsed.isRegex
                ? toHeaderPattern(parsed.reStr)
                : parsed.value;
            if ( value !== undefined ) {
                const prop = parsed.not
                    ? 'excludedResponseHeaders'
                    : 'responseHeaders';
                rule.condition[prop] ||= [];
                const details = {
                    header: parsed.name,
                };
                if ( value !== '' ) {
                    details.values = [ value ];
                }
                rule.condition[prop].push(details);
                return;
            }
        }
        dnrAddRuleError(rule, `header="${args[1]}" not supported`);
    }

    static logData(idata, details) {
        const irefs = filterData[idata+1];
        const headerOpt = filterRefs[irefs].headerOpt;
        let opt = 'header';
        if ( headerOpt !== '' ) {
            opt += `=${LogData.requote(headerOpt)}`;
        }
        details.options.push(opt);
    }
}

registerFilterClass(FilterOnHeaders);

/******************************************************************************/

class FilterIPAddress {
    static TYPE_UNKNOWN = 0;
    static TYPE_EQUAL = 1;
    static TYPE_STARTSWITH = 2;
    static TYPE_LAN = 3;
    static TYPE_LOOPBACK = 4;
    static TYPE_RE = 5;
    static reIPv6IPv4lan = /^::ffff:(7f\w{2}|a\w{2}|a9fe|c0a8):\w+$/;
    static reIPv6local = /^f[cd]\w{2}:/;

    static match(idata) {
        const ipaddr = $requestAddress;
        if ( ipaddr === '' ) { return false; }
        const details = filterRefs[filterData[idata+1]];
        switch ( details.$type || this.TYPE_UNKNOWN ) {
        case this.TYPE_LAN:
            return this.isLAN(ipaddr);
        case this.TYPE_LOOPBACK:
            return this.isLoopback(ipaddr);
        case this.TYPE_EQUAL:
        case this.TYPE_STARTSWITH:
        case this.TYPE_RE:
            return details.$pattern.test(ipaddr);
        default:
            break;
        }
        const { pattern } = details;
        if ( pattern === 'lan' ) {
            details.$type = this.TYPE_LAN;
        } else if ( pattern === 'loopback' ) {
            details.$type = this.TYPE_LOOPBACK;
        } else if ( pattern.startsWith('/') && pattern.endsWith('/') ) {
            details.$type = this.TYPE_RE;
            details.$pattern = new RegExp(pattern.slice(1, -1), 'm');
        } else if ( pattern.endsWith('*') ) {
            details.$type = this.TYPE_STARTSWITH;
            details.$pattern = new RegExp(`^${restrFromPlainPattern(pattern.slice(0, -1))}`, 'm');
        } else {
            details.$type = this.TYPE_EQUAL;
            details.$pattern = new RegExp(`^${restrFromPlainPattern(pattern)}$`, 'm');
        }
        return this.match(idata);
    }

    // https://github.com/uBlockOrigin/uAssets/blob/master/filters/lan-block.txt
    // https://en.wikipedia.org/wiki/Reserved_IP_addresses
    // `ipaddr` is assumed well-formed
    static isLAN(ipaddr) {
        const c0 = ipaddr.charCodeAt(0);
        // ipv4
        if ( c0 === 0x30 /* 0 */ ) {
            return ipaddr.startsWith('0.');
        }
        if ( c0 === 0x31 /* 1 */ ) {
            if ( ipaddr.startsWith('10.') ) { return true; }
            if ( ipaddr.startsWith('127.') ) { return true; }
            if ( ipaddr.startsWith('169.254.') ) { return true; }
            if ( ipaddr.startsWith('172.') ) {
                const v = parseInt(ipaddr.slice(4), 10);
                return v >= 16 && v <= 31;
            }
            return ipaddr.startsWith('192.168.');
        }
        // ipv6
        if ( c0 === 0x3A /* : */ ) {
            if ( ipaddr.startsWith('::') === false ) { return false; }
            if ( ipaddr === '::' || ipaddr === '::1' ) { return true; }
            if ( ipaddr.startsWith('::ffff:') === false ) { return false; }
            return this.reIPv6IPv4lan.test(ipaddr);
        }
        if ( c0 === 0x66 /* f */ ) {
            return this.reIPv6local.test(ipaddr);
        }
        return false;
    }

    static isLoopback(ipaddr) {
        return ipaddr === '127.0.0.1' || ipaddr === '::1';
    }

    static compile(details) {
        return [ FilterIPAddress.fid, details.optionValues.get('ipaddress') ];
    }

    static fromCompiled(args) {
        const pattern = args[1];
        const details = { pattern };
        return filterDataAlloc(args[0], filterRefAdd(details));
    }

    static dnrFromCompiled(args, rule) {
        dnrAddRuleError(rule, `"ipaddress=${args[1]}" not supported`);
    }

    static logData(idata, details) {
        const irefs = filterData[idata+1];
        details.options.push(`ipaddress=${LogData.requote(filterRefs[irefs].pattern)}`);
    }
}

registerFilterClass(FilterIPAddress);

/******************************************************************************/

class FilterMessage {
    static match() {
        return true;
    }

    static compile(details) {
        return [
            FilterMessage.fid,
            encodeURIComponent(details.optionValues.get('reason')),
        ];
    }

    static fromCompiled(args) {
        const msg = args[1];
        return filterDataAlloc(args[0], bidiTrie.storeString(msg), msg.length);
    }

    static keyFromArgs(args) {
        return `${args[1]}`;
    }

    static logData(idata, details) {
        const reason = decodeURIComponent(
            bidiTrie.extractString(filterData[idata+1], filterData[idata+2])
        );
        details.reason = reason;
        details.options.push(`reason=${reason}`);
    }
}

registerFilterClass(FilterMessage);

/******************************************************************************/
/******************************************************************************/

// https://github.com/gorhill/uBlock/issues/2630
// Slice input URL into a list of safe-integer token values, instead of a list
// of substrings. The assumption is that with dealing only with numeric
// values, less underlying memory allocations, and also as a consequence
// less work for the garbage collector down the road.
// Another assumption is that using a numeric-based key value for Map() is
// more efficient than string-based key value (but that is something I would
// have to benchmark).
// Benchmark for string-based tokens vs. safe-integer token values:
//   https://gorhill.github.io/obj-vs-set-vs-map/tokenize-to-str-vs-to-int.html

// http://www.cse.yorku.ca/~oz/hash.html#djb2
//   Use above algorithm to generate token hash.

const urlTokenizer = new (class {
    constructor() {
        this._chars = '0123456789%abcdefghijklmnopqrstuvwxyz';
        this._validTokenChars = new Uint8Array(128);
        for ( let i = 0, n = this._chars.length; i < n; i++ ) {
            this._validTokenChars[this._chars.charCodeAt(i)] = i + 1;
        }

        this._urlIn = '';
        this._urlOut = '';
        this._tokenized = false;
        this._hasQuery = 0;
        // https://www.reddit.com/r/uBlockOrigin/comments/dzw57l/
        //   Remember: 1 token needs two slots
        this._tokens = new Uint32Array(bidiTrie.haystack.length + 16);

        this.knownTokens = new Uint8Array(65536);
        this.resetKnownTokens();
    }

    setURL(url) {
        if ( url !== this._urlIn ) {
            this._urlIn = url;
            this._urlOut = url.toLowerCase();
            this._hasQuery = 0;
            this._tokenized = false;
        }
        return this._urlOut;
    }

    resetKnownTokens() {
        this.knownTokens.fill(0);
        this.addKnownToken(DOT_TOKEN_HASH);
        this.addKnownToken(ANY_TOKEN_HASH);
        this.addKnownToken(ANY_HTTPS_TOKEN_HASH);
        this.addKnownToken(ANY_HTTP_TOKEN_HASH);
        this.addKnownToken(NO_TOKEN_HASH);
    }

    addKnownToken(th) {
        this.knownTokens[th & 0xFFFF] = 1;
    }

    // Tokenize on demand.
    getTokens() {
        if ( this._tokenized ) { return this._tokens; }
        let i = this._tokenize();
        this._tokens[i+0] = ANY_TOKEN_HASH;
        this._tokens[i+1] = 0;
        i += 2;
        if ( this._urlOut.startsWith('https://') ) {
            this._tokens[i+0] = ANY_HTTPS_TOKEN_HASH;
            this._tokens[i+1] = 0;
            i += 2;
        } else if ( this._urlOut.startsWith('http://') ) {
            this._tokens[i+0] = ANY_HTTP_TOKEN_HASH;
            this._tokens[i+1] = 0;
            i += 2;
        }
        this._tokens[i+0] = NO_TOKEN_HASH;
        this._tokens[i+1] = 0;
        this._tokens[i+2] = INVALID_TOKEN_HASH;
        this._tokenized = true;
        return this._tokens;
    }

    hasQuery() {
        if ( this._hasQuery === 0 ) {
            const i = this._urlOut.indexOf('?');
            this._hasQuery = i !== -1 ? i + 1 : -1;
        }
        return this._hasQuery > 0;
    }

    // http://www.cse.yorku.ca/~oz/hash.html#djb2

    tokenHashFromString(s) {
        const l = s.length;
        if ( l === 0 ) { return EMPTY_TOKEN_HASH; }
        const vtc = this._validTokenChars;
        let th = vtc[s.charCodeAt(0)];
        for ( let i = 1; i !== 7 /* MAX_TOKEN_LENGTH */ && i !== l; i++ ) {
            th = (th << 5) + th ^ vtc[s.charCodeAt(i)];
        }
        return th & 0xFFFFFFF;
    }

    stringFromTokenHash(th) {
        if ( th === 0 ) { return ''; }
        return th.toString(16);
    }

    toSelfie() {
        return this.knownTokens;
    }

    fromSelfie(selfie) {
        this.knownTokens = selfie;
    }

    // https://github.com/chrisaljoudi/uBlock/issues/1118
    // We limit to a maximum number of tokens.

    _tokenize() {
        const tokens = this._tokens;
        const url = this._urlOut;
        const l = bidiTrie.setHaystackLen(url.length);
        if ( l === 0 ) { return 0; }
        let j = 0;
        let hasq = -1;
        mainLoop: {
            const knownTokens = this.knownTokens;
            const vtc = this._validTokenChars;
            const charCodes = bidiTrie.haystack;
            let i = 0, n = 0, ti = 0, th = 0;
            for (;;) {
                for (;;) {
                    if ( i === l ) { break mainLoop; }
                    const cc = url.charCodeAt(i);
                    charCodes[i] = cc;
                    i += 1;
                    th = vtc[cc];
                    if ( th !== 0 ) { break; }
                    if ( cc === 0x3F /* '?' */ ) { hasq = i; }
                }
                ti = i - 1; n = 1;
                for (;;) {
                    if ( i === l ) { break; }
                    const cc = url.charCodeAt(i);
                    charCodes[i] = cc;
                    i += 1;
                    const v = vtc[cc];
                    if ( v === 0 ) {
                        if ( cc === 0x3F /* '?' */ ) { hasq = i; }
                        break;
                    }
                    if ( n === 7 /* MAX_TOKEN_LENGTH */ ) { continue; }
                    th = (th << 5) + th ^ v;
                    n += 1;
                }
                if ( knownTokens[th & 0xFFFF] !== 0 ) {
                    tokens[j+0] = th & 0xFFFFFFF;
                    tokens[j+1] = ti;
                    j += 2;
                }
            }
        }
        this._hasQuery = hasq;
        return j;
    }
})();

/******************************************************************************/
/******************************************************************************/

class FilterCompiler {
    constructor(other = undefined) {
        if ( other !== undefined ) {
            return Object.assign(this, other);
        }
        this.reTokens = /[%0-9A-Za-z]+/g;
        this.optionValues = new Map();
        this.tokenIdToNormalizedType = new Map([
            [ sfp.NODE_TYPE_NET_OPTION_NAME_CNAME, bitFromType('cname') ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_CSS, bitFromType('stylesheet') ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_DOC, bitFromType('main_frame') ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_FONT, bitFromType('font') ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_FRAME, bitFromType('sub_frame') ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_GENERICBLOCK, bitFromType('unsupported') ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_GHIDE, bitFromType('generichide') ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_IMAGE, bitFromType('image') ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_INLINEFONT, bitFromType('inline-font') ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_INLINESCRIPT, bitFromType('inline-script') ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_MEDIA, bitFromType('media') ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_OBJECT, bitFromType('object') ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_OTHER, bitFromType('other') ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_PING, bitFromType('ping') ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_POPUNDER, bitFromType('popunder') ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_POPUP, bitFromType('popup') ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_SCRIPT, bitFromType('script') ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_SHIDE, bitFromType('specifichide') ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_XHR, bitFromType('xmlhttprequest') ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_WEBRTC, bitFromType('unsupported') ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_WEBSOCKET, bitFromType('websocket') ],
        ]);
        this.modifierIdToNormalizedId = new Map([
            [ sfp.NODE_TYPE_NET_OPTION_NAME_CSP, MODIFIER_TYPE_CSP ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_PERMISSIONS, MODIFIER_TYPE_PERMISSIONS ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_REDIRECT, MODIFIER_TYPE_REDIRECT ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_REDIRECTRULE, MODIFIER_TYPE_REDIRECTRULE ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_REMOVEPARAM, MODIFIER_TYPE_REMOVEPARAM ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_URLTRANSFORM, MODIFIER_TYPE_URLTRANSFORM ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_REPLACE, MODIFIER_TYPE_REPLACE ],
            [ sfp.NODE_TYPE_NET_OPTION_NAME_URLSKIP, MODIFIER_TYPE_URLSKIP ],
        ]);
        // These top 100 "bad tokens" are collated using the "miss" histogram
        // from tokenHistograms(). The "score" is their occurrence among the
        // 200K+ URLs used in the benchmark and executed against default
        // filter lists.
        this.badTokens = new Map([
            [ 'https',123617 ],
            [ 'com',76987 ],
            [ 'js',43620 ],
            [ 'www',33129 ],
            [ 'jpg',32221 ],
            [ 'images',31812 ],
            [ 'css',19715 ],
            [ 'png',19140 ],
            [ 'static',15724 ],
            [ 'net',15239 ],
            [ 'de',13155 ],
            [ 'img',11109 ],
            [ 'assets',10746 ],
            [ 'min',7807 ],
            [ 'cdn',7568 ],
            [ 'content',6900 ],
            [ 'wp',6444 ],
            [ 'fonts',6095 ],
            [ 'svg',5976 ],
            [ 'http',5813 ],
            [ 'ssl',5735 ],
            [ 'amazon',5440 ],
            [ 'ru',5427 ],
            [ 'fr',5199 ],
            [ 'facebook',5178 ],
            [ 'en',5146 ],
            [ 'image',5028 ],
            [ 'html',4837 ],
            [ 'media',4833 ],
            [ 'co',4783 ],
            [ 'php',3972 ],
            [ '2019',3943 ],
            [ 'org',3924 ],
            [ 'jquery',3531 ],
            [ '02',3438 ],
            [ 'api',3382 ],
            [ 'gif',3350 ],
            [ 'eu',3322 ],
            [ 'prod',3289 ],
            [ 'woff2',3200 ],
            [ 'logo',3194 ],
            [ 'themes',3107 ],
            [ 'icon',3048 ],
            [ 'google',3026 ],
            [ 'v1',3019 ],
            [ 'uploads',2963 ],
            [ 'googleapis',2860 ],
            [ 'v3',2816 ],
            [ 'tv',2762 ],
            [ 'icons',2748 ],
            [ 'core',2601 ],
            [ 'gstatic',2581 ],
            [ 'ac',2509 ],
            [ 'utag',2466 ],
            [ 'id',2459 ],
            [ 'ver',2448 ],
            [ 'rsrc',2387 ],
            [ 'files',2361 ],
            [ 'uk',2357 ],
            [ 'us',2271 ],
            [ 'pl',2262 ],
            [ 'common',2205 ],
            [ 'public',2076 ],
            [ '01',2016 ],
            [ 'na',1957 ],
            [ 'v2',1954 ],
            [ '12',1914 ],
            [ 'thumb',1895 ],
            [ 'web',1853 ],
            [ 'ui',1841 ],
            [ 'default',1825 ],
            [ 'main',1737 ],
            [ 'false',1715 ],
            [ '2018',1697 ],
            [ 'embed',1639 ],
            [ 'player',1634 ],
            [ 'dist',1599 ],
            [ 'woff',1593 ],
            [ 'global',1593 ],
            [ 'json',1572 ],
            [ '11',1566 ],
            [ '600',1559 ],
            [ 'app',1556 ],
            [ 'styles',1533 ],
            [ 'plugins',1526 ],
            [ '274',1512 ],
            [ 'random',1505 ],
            [ 'sites',1505 ],
            [ 'imasdk',1501 ],
            [ 'bridge3',1501 ],
            [ 'news',1496 ],
            [ 'width',1494 ],
            [ 'thumbs',1485 ],
            [ 'ttf',1470 ],
            [ 'ajax',1463 ],
            [ 'user',1454 ],
            [ 'scripts',1446 ],
            [ 'twitter',1440 ],
            [ 'crop',1431 ],
            [ 'new',1412],
        ]);
        this.reset();
    }

    reset() {
        this.action = BLOCK_REALM;
        // anchor: bit vector
        //   0000 (0x0): no anchoring
        //   0001 (0x1): anchored to the end of the URL.
        //   0010 (0x2): anchored to the start of the URL.
        //   0011 (0x3): anchored to the start and end of the URL.
        //   0100 (0x4): anchored to the hostname of the URL.
        //   0101 (0x5): anchored to the hostname and end of the URL.
        this.anchor = 0;
        this.badFilter = false;
        this.error = undefined;
        this.modifyType = undefined;
        this.modifyValue = undefined;
        this.pattern = '';
        this.party = ANYPARTY_REALM;
        this.optionUnitBits = 0;
        this.optionValues.clear();
        this.isPureHostname = false;
        this.isGeneric = false;
        this.isRegex = false;
        this.strictParty = 0;
        this.token = '*';
        this.tokenHash = NO_TOKEN_HASH;
        this.tokenBeg = 0;
        this.typeBits = 0;
        this.notTypeBits = 0;
        this.methodBits = 0;
        this.notMethodBits = 0;
        return this;
    }

    start(/* writer */) {
    }

    finish(/* writer */) {
    }

    clone() {
        return new FilterCompiler(this);
    }

    normalizeRegexSource(s) {
        try {
            const re = new RegExp(s);
            return re.source;
        } catch {
        }
        return '';
    }

    processMethodOption(value) {
        for ( const method of value.split('|') ) {
            if ( method.charCodeAt(0) === 0x7E /* '~' */ ) {
                const bit = FilteringContext.getMethod(method.slice(1)) || 0;
                if ( bit === 0 ) { continue; }
                this.notMethodBits |= bit;
            } else {
                const bit = FilteringContext.getMethod(method) || 0;
                if ( bit === 0 ) { continue; }
                this.methodBits |= bit;
            }
        }
        this.methodBits &= ~this.notMethodBits;
    }

    // https://github.com/chrisaljoudi/uBlock/issues/589
    // Be ready to handle multiple negated types

    processTypeOption(id, not) {
        if ( id !== -1 ) {
            const typeBit = this.tokenIdToNormalizedType.get(id);
            if ( not ) {
                this.notTypeBits |= typeBit;
            } else {
                this.typeBits |= typeBit;
            }
            return;
        }
        // `all` option
        if ( not ) {
            this.notTypeBits |= allTypesBits;
        } else {
            this.typeBits |= allTypesBits;
        }
    }

    processPartyOption(firstParty, not) {
        if ( not ) {
            firstParty = !firstParty;
        }
        this.party |= firstParty ? FIRSTPARTY_REALM : THIRDPARTY_REALM;
    }

    processHostnameList(iter, out = []) {
        let i = 0;
        for ( const { hn, not, bad } of iter ) {
            if ( bad ) { return ''; }
            out[i] = not ? `~${hn}` : hn;
            i += 1;
        }
        out.length = i;
        return i === 1 ? out[0] : out.join('|');
    }

    processModifierOption(modifier, value) {
        if ( this.modifyType !== undefined ) { return false; }
        const normalized = this.modifierIdToNormalizedId.get(modifier);
        if ( normalized === undefined ) { return false; }
        this.modifyType = normalized;
        this.modifyValue = value || '';
        return true;
    }

    processCspOption(value) {
        this.modifyType = MODIFIER_TYPE_CSP;
        this.modifyValue = value || '';
        this.optionUnitBits |= MODIFY_BIT;
        return true;
    }

    processOptionWithValue(parser, id) {
        switch ( id ) {
        case sfp.NODE_TYPE_NET_OPTION_NAME_CSP:
            if ( this.processCspOption(parser.getNetOptionValue(id)) === false ) { return false; }
            break;
        case sfp.NODE_TYPE_NET_OPTION_NAME_DENYALLOW: {
            const value = this.processHostnameList(
                parser.getNetFilterDenyallowOptionIterator()
            );
            if ( value === '' ) { return false; }
            this.optionValues.set('denyallow', value);
            this.optionUnitBits |= DENYALLOW_BIT;
            break;
        }
        case sfp.NODE_TYPE_NET_OPTION_NAME_FROM: {
            const iter = parser.getNetFilterFromOptionIterator();
            const list = [];
            const value = this.processHostnameList(iter, list);
            if ( value === '' ) { return false; }
            this.optionValues.set('from', value);
            this.optionValues.set('fromList', list);
            this.optionUnitBits |= FROM_BIT;
            break;
        }
        case sfp.NODE_TYPE_NET_OPTION_NAME_HEADER: {
            this.optionValues.set('header', parser.getNetOptionValue(id) || '');
            this.optionUnitBits |= HEADER_BIT;
            break;
        }
        case sfp.NODE_TYPE_NET_OPTION_NAME_IPADDRESS:
            this.optionValues.set('ipaddress', parser.getNetOptionValue(id) || '');
            this.optionUnitBits |= IPADDRESS_BIT;
            break;
        case sfp.NODE_TYPE_NET_OPTION_NAME_METHOD:
            this.processMethodOption(parser.getNetOptionValue(id));
            this.optionUnitBits |= METHOD_BIT;
            break;
        case sfp.NODE_TYPE_NET_OPTION_NAME_PERMISSIONS:
        case sfp.NODE_TYPE_NET_OPTION_NAME_REDIRECTRULE:
        case sfp.NODE_TYPE_NET_OPTION_NAME_REMOVEPARAM:
        case sfp.NODE_TYPE_NET_OPTION_NAME_REPLACE:
        case sfp.NODE_TYPE_NET_OPTION_NAME_URLSKIP:
        case sfp.NODE_TYPE_NET_OPTION_NAME_URLTRANSFORM:
            if ( this.processModifierOption(id, parser.getNetOptionValue(id)) === false ) {
                return false;
            }
            this.optionUnitBits |= MODIFY_BIT;
            break;
        case sfp.NODE_TYPE_NET_OPTION_NAME_REASON:
            this.optionValues.set('reason', parser.getNetOptionValue(id));
            this.optionUnitBits |= MESSAGE_BIT;
            break;
        case sfp.NODE_TYPE_NET_OPTION_NAME_REDIRECT: {
            const actualId = this.action === ALLOW_REALM
                ? sfp.NODE_TYPE_NET_OPTION_NAME_REDIRECTRULE
                : id;
            if ( this.processModifierOption(actualId, parser.getNetOptionValue(id)) === false ) {
                return false;
            }
            this.optionUnitBits |= MODIFY_BIT;
            break;
        }
        case sfp.NODE_TYPE_NET_OPTION_NAME_TO: {
            const iter = parser.getNetFilterToOptionIterator();
            const list = [];
            const value = this.processHostnameList(iter, list);
            if ( value === '' ) { return false; }
            this.optionValues.set('to', value);
            this.optionValues.set('toList', list);
            this.optionUnitBits |= TO_BIT;
            break;
        }
        default:
            break;
        }
        return true;
    }

    process(parser) {
        // important!
        this.reset();

        if ( parser.hasError() ) {
            return this.FILTER_INVALID;
        }

        if ( parser.isException() ) {
            this.action = ALLOW_REALM;
        }

        if ( parser.isLeftHnAnchored() ) {
            this.anchor |= 0b100;
        } else if ( parser.isLeftAnchored() ) {
            this.anchor |= 0b010;
        }
        if ( parser.isRightAnchored() ) {
            this.anchor |= 0b001;
        }

        this.pattern = parser.getNetPattern();
        if ( parser.isHostnamePattern() ) {
            this.isPureHostname = true;
        } else if ( parser.isGenericPattern() ) {
            this.isGeneric = true;
        } else if ( parser.isRegexPattern() ) {
            this.isRegex = true;
        }

        for ( const type of parser.getNodeTypes() ) {
            switch ( type ) {
            case sfp.NODE_TYPE_NET_OPTION_NAME_1P:
                this.processPartyOption(true, parser.isNegatedOption(type));
                break;
            case sfp.NODE_TYPE_NET_OPTION_NAME_STRICT1P:
                this.strictParty = this.strictParty === -1 ? 0 : 1;
                this.optionUnitBits |= STRICT_PARTY_BIT;
                break;
            case sfp.NODE_TYPE_NET_OPTION_NAME_3P:
                this.processPartyOption(false, parser.isNegatedOption(type));
                break;
            case sfp.NODE_TYPE_NET_OPTION_NAME_STRICT3P:
                this.strictParty = this.strictParty === 1 ? 0 : -1;
                this.optionUnitBits |= STRICT_PARTY_BIT;
                break;
            case sfp.NODE_TYPE_NET_OPTION_NAME_ALL:
                this.processTypeOption(-1);
                break;
            case sfp.NODE_TYPE_NET_OPTION_NAME_BADFILTER:
                this.badFilter = true;
                break;
            case sfp.NODE_TYPE_NET_OPTION_NAME_CNAME:
            case sfp.NODE_TYPE_NET_OPTION_NAME_CSS:
            case sfp.NODE_TYPE_NET_OPTION_NAME_DOC:
            case sfp.NODE_TYPE_NET_OPTION_NAME_FONT:
            case sfp.NODE_TYPE_NET_OPTION_NAME_FRAME:
            case sfp.NODE_TYPE_NET_OPTION_NAME_GENERICBLOCK:
            case sfp.NODE_TYPE_NET_OPTION_NAME_GHIDE:
            case sfp.NODE_TYPE_NET_OPTION_NAME_IMAGE:
            case sfp.NODE_TYPE_NET_OPTION_NAME_INLINEFONT:
            case sfp.NODE_TYPE_NET_OPTION_NAME_INLINESCRIPT:
            case sfp.NODE_TYPE_NET_OPTION_NAME_MEDIA:
            case sfp.NODE_TYPE_NET_OPTION_NAME_OBJECT:
            case sfp.NODE_TYPE_NET_OPTION_NAME_OTHER:
            case sfp.NODE_TYPE_NET_OPTION_NAME_PING:
            case sfp.NODE_TYPE_NET_OPTION_NAME_POPUNDER:
            case sfp.NODE_TYPE_NET_OPTION_NAME_POPUP:
            case sfp.NODE_TYPE_NET_OPTION_NAME_SCRIPT:
            case sfp.NODE_TYPE_NET_OPTION_NAME_SHIDE:
            case sfp.NODE_TYPE_NET_OPTION_NAME_XHR:
            case sfp.NODE_TYPE_NET_OPTION_NAME_WEBRTC:
            case sfp.NODE_TYPE_NET_OPTION_NAME_WEBSOCKET:
                this.processTypeOption(type, parser.isNegatedOption(type));
                break;
            case sfp.NODE_TYPE_NET_OPTION_NAME_CSP:
            case sfp.NODE_TYPE_NET_OPTION_NAME_DENYALLOW:
            case sfp.NODE_TYPE_NET_OPTION_NAME_FROM:
            case sfp.NODE_TYPE_NET_OPTION_NAME_HEADER:
            case sfp.NODE_TYPE_NET_OPTION_NAME_IPADDRESS:
            case sfp.NODE_TYPE_NET_OPTION_NAME_METHOD:
            case sfp.NODE_TYPE_NET_OPTION_NAME_PERMISSIONS:
            case sfp.NODE_TYPE_NET_OPTION_NAME_REASON:
            case sfp.NODE_TYPE_NET_OPTION_NAME_REDIRECT:
            case sfp.NODE_TYPE_NET_OPTION_NAME_REDIRECTRULE:
            case sfp.NODE_TYPE_NET_OPTION_NAME_REMOVEPARAM:
            case sfp.NODE_TYPE_NET_OPTION_NAME_REPLACE:
            case sfp.NODE_TYPE_NET_OPTION_NAME_TO:
            case sfp.NODE_TYPE_NET_OPTION_NAME_URLSKIP:
            case sfp.NODE_TYPE_NET_OPTION_NAME_URLTRANSFORM:
                if ( this.processOptionWithValue(parser, type) === false ) {
                    return this.FILTER_INVALID;
                }
                break;
            case sfp.NODE_TYPE_NET_OPTION_NAME_EHIDE: {
                const not = parser.isNegatedOption(type);
                this.processTypeOption(sfp.NODE_TYPE_NET_OPTION_NAME_SHIDE, not);
                this.processTypeOption(sfp.NODE_TYPE_NET_OPTION_NAME_GHIDE, not);
                break;
            }
            case sfp.NODE_TYPE_NET_OPTION_NAME_EMPTY: {
                const id = this.action === ALLOW_REALM
                    ? sfp.NODE_TYPE_NET_OPTION_NAME_REDIRECTRULE
                    : sfp.NODE_TYPE_NET_OPTION_NAME_REDIRECT;
                if ( this.processModifierOption(id, 'empty') === false ) {
                    return this.FILTER_INVALID;
                }
                this.optionUnitBits |= MODIFY_BIT;
                break;
            }
            case sfp.NODE_TYPE_NET_OPTION_NAME_IMPORTANT:
                this.optionUnitBits |= IMPORTANT_BIT;
                this.action = BLOCKIMPORTANT_REALM;
                break;
            case sfp.NODE_TYPE_NET_OPTION_NAME_MATCHCASE:
                this.optionValues.set('match-case', true);
                break;
            case sfp.NODE_TYPE_NET_OPTION_NAME_MP4: {
                const id = this.action === ALLOW_REALM
                    ? sfp.NODE_TYPE_NET_OPTION_NAME_REDIRECTRULE
                    : sfp.NODE_TYPE_NET_OPTION_NAME_REDIRECT;
                if ( this.processModifierOption(id, 'noopmp4-1s') === false ) {
                    return this.FILTER_INVALID;
                }
                this.processTypeOption(sfp.NODE_TYPE_NET_OPTION_NAME_MEDIA, false);
                this.optionUnitBits |= MODIFY_BIT;
                break;
            }
            default:
                break;
            }
        }

        if ( this.party === ALLPARTIES_REALM ) {
            this.party = ANYPARTY_REALM;
        }

        // Negated network types? Toggle on all network type bits.
        // Negated non-network types can only toggle themselves.
        //
        // https://github.com/gorhill/uBlock/issues/2385
        //   Toggle on all network types if:
        //   - at least one network type is negated; or
        //   - no network type is present -- i.e. all network types are
        //     implicitly toggled on
        if ( this.notTypeBits !== 0 ) {
            if ( (this.typeBits && allNetworkTypesBits) === allNetworkTypesBits ) {
                this.typeBits &= ~this.notTypeBits | allNetworkTypesBits;
            } else {
                this.typeBits &= ~this.notTypeBits;
            }
            this.optionUnitBits |= NOT_TYPE_BIT;
        }

        // CSP/permissions options implicitly apply only to
        // document/subdocument.
        if (
            this.modifyType === MODIFIER_TYPE_CSP ||
            this.modifyType === MODIFIER_TYPE_PERMISSIONS
        ) {
            if ( this.typeBits === 0 ) {
                this.processTypeOption(sfp.NODE_TYPE_NET_OPTION_NAME_DOC, false);
                this.processTypeOption(sfp.NODE_TYPE_NET_OPTION_NAME_FRAME, false);
            }
        }

        // https://github.com/gorhill/uBlock/issues/2283
        //   Abort if type is only for unsupported types, otherwise
        //   toggle off `unsupported` bit.
        if ( this.typeBits & unsupportedTypeBit ) {
            this.typeBits &= ~unsupportedTypeBit;
            if ( this.typeBits === 0 ) { return this.FILTER_UNSUPPORTED; }
        }

        // Plain hostname? (from HOSTS file)
        if ( this.isPureHostname && parser.hasOptions() === false ) {
            this.anchor |= 0b100;
            return this.FILTER_OK;
        }

        // regex?
        if ( this.isRegex ) {
            return this.FILTER_OK;
        }

        if ( this.pattern.length > 1024 ) {
            return this.FILTER_UNSUPPORTED;
        }

        return this.FILTER_OK;
    }

    // Given a string, find a good token. Tokens which are too generic,
    // i.e. very common with a high probability of ending up as a miss,
    // are not good. Avoid if possible. This has a significant positive
    // impact on performance.
    //
    // For pattern-less removeparam filters, try to derive a pattern from
    // the removeparam value.

    makeToken() {
        if ( this.pattern === '*' ) {
            if ( this.modifyType !== MODIFIER_TYPE_REMOVEPARAM ) { return; }
            return this.extractTokenFromQuerypruneValue();
        }
        if ( this.isRegex ) {
            return this.extractTokenFromRegex(this.pattern);
        }
        this.extractTokenFromPattern(this.pattern);
    }

    // Note: a one-char token is better than a documented bad token.
    extractTokenFromPattern(pattern) {
        this.reTokens.lastIndex = 0;
        let bestMatch = null;
        let bestBadness = 0x7FFFFFFF;
        for (;;) {
            const match = this.reTokens.exec(pattern);
            if ( match === null ) { break; }
            const token = match[0];
            const badness = token.length > 1 ? this.badTokens.get(token) || 0 : 1;
            if ( badness >= bestBadness ) { continue; }
            if ( match.index > 0 ) {
                const c = pattern.charCodeAt(match.index - 1);
                if ( c === 0x2A /* '*' */ ) { continue; }
            }
            if ( token.length < MAX_TOKEN_LENGTH ) {
                const lastIndex = this.reTokens.lastIndex;
                if ( lastIndex < pattern.length ) {
                    const c = pattern.charCodeAt(lastIndex);
                    if ( c === 0x2A /* '*' */ ) { continue; }
                }
            }
            bestMatch = match;
            if ( badness === 0 ) { break; }
            bestBadness = badness;
        }
        if ( bestMatch !== null ) {
            this.token = bestMatch[0];
            this.tokenHash = urlTokenizer.tokenHashFromString(this.token);
            this.tokenBeg = bestMatch.index;
        }
    }

    // https://github.com/gorhill/uBlock/issues/2781
    //   For efficiency purpose, try to extract a token from a regex-based
    //   filter.
    // https://github.com/uBlockOrigin/uBlock-issues/issues/1145#issuecomment-657036902
    //   Mind `\b` directives: `/\bads\b/` should result in token being `ads`,
    //   not `bads`.
    extractTokenFromRegex(pattern) {
        pattern = tokenizableStrFromRegex(pattern);
        this.reTokens.lastIndex = 0;
        let bestToken;
        let bestBadness = 0x7FFFFFFF;
        for (;;) {
            const matches = this.reTokens.exec(pattern);
            if ( matches === null ) { break; }
            const { 0: token, index } = matches;
            if ( index === 0 || pattern.charAt(index - 1) === '\x01' ) {
                continue;
            }
            const { lastIndex } = this.reTokens;
            if (
                token.length < MAX_TOKEN_LENGTH && (
                    lastIndex === pattern.length ||
                    pattern.charAt(lastIndex) === '\x01'
                )
            ) {
                continue;
            }
            const badness = token.length > 1
                ? this.badTokens.get(token) || 0
                : 1;
            if ( badness < bestBadness ) {
                bestToken = token;
                if ( badness === 0 ) { break; }
                bestBadness = badness;
            }
        }
        if ( bestToken !== undefined ) {
            this.token = bestToken.toLowerCase();
            this.tokenHash = urlTokenizer.tokenHashFromString(this.token);
        }
    }

    // https://github.com/uBlockOrigin/uAssets/discussions/14683#discussioncomment-3559284
    //   If the removeparam value is a regex, unescape escaped commas
    extractTokenFromQuerypruneValue() {
        const pattern = this.modifyValue;
        if ( pattern === '*' || pattern.charCodeAt(0) === 0x7E /* '~' */ ) {
            return;
        }
        const match = /^\/(.+)\/i?$/.exec(pattern);
        if ( match !== null ) {
            return this.extractTokenFromRegex(
                match[1].replace(/(\{\d*)\\,/, '$1,')
            );
        }
        if ( pattern.startsWith('|') ) {
            return this.extractTokenFromRegex('\\b' + pattern.slice(1));
        }
        this.extractTokenFromPattern(pattern.toLowerCase());
    }

    hasNoOptionUnits() {
        return this.optionUnitBits === 0;
    }

    isJustOrigin() {
        if ( this.optionUnitBits !== FROM_BIT ) { return false; }
        if ( this.isRegex ) { return false; }
        if ( /[/~]/.test(this.optionValues.get('from')) ) { return false; }
        if ( this.pattern === '*' ) { return true; }
        if ( this.anchor !== 0b010 ) { return false; }
        if ( /^(?:http[s*]?:(?:\/\/)?)$/.test(this.pattern) ) { return true; }
        return false;
    }

    domainIsEntity(s) {
        const l = s.length;
        return l > 2 &&
               s.charCodeAt(l-1) === 0x2A /* '*' */ &&
               s.charCodeAt(l-2) === 0x2E /* '.' */;
    }

    compile(parser, writer) {
        const r = this.process(parser);

        // Ignore non-static network filters
        if ( r === this.FILTER_INVALID ) { return false; }

        // Ignore filters with unsupported options
        if ( r === this.FILTER_UNSUPPORTED ) {
            const who = writer.properties.get('name') || '?';
            this.error = `Invalid network filter in ${who}: ${parser.raw}`;
            return false;
        }

        writer.select(
            this.badFilter
                ? 'NETWORK_FILTERS:BAD'
                : 'NETWORK_FILTERS:GOOD'
        );

        // Reminder:
        //   `redirect=` is a combination of a `redirect-rule` filter and a
        //   block filter.
        if ( this.modifyType === MODIFIER_TYPE_REDIRECT ) {
            this.modifyType = MODIFIER_TYPE_REDIRECTRULE;
            // Do not generate block rule when compiling to DNR ruleset
            if ( parser.options.toDNR !== true ) {
                const parsedBlock = this.clone();
                parsedBlock.modifyType = undefined;
                parsedBlock.optionUnitBits &= ~MODIFY_BIT;
                parsedBlock.compileToFilter(writer);
            }
        }

        this.compileToFilter(writer);

        return true;
    }

    compileToFilter(writer) {
        // Pure hostnames, use more efficient dictionary lookup
        if ( this.isPureHostname && this.hasNoOptionUnits() ) {
            this.tokenHash = DOT_TOKEN_HASH;
            this.compileToAtomicFilter(this.pattern, writer);
            return;
        }

        this.makeToken();

        // Special pattern/option cases:
        // - `*$domain=...`
        // - `|http://$domain=...`
        // - `|https://$domain=...`
        // The semantic of "just-origin" filters is that contrary to normal
        // filters, the original filter is split into as many filters as there
        // are entries in the `domain=` option.
        if ( this.isJustOrigin() ) {
            if ( this.pattern === '*' || this.pattern.startsWith('http*') ) {
                this.tokenHash = ANY_TOKEN_HASH;
            } else if /* 'https:' */ ( this.pattern.startsWith('https') ) {
                this.tokenHash = ANY_HTTPS_TOKEN_HASH;
            } else /* 'http:' */ {
                this.tokenHash = ANY_HTTP_TOKEN_HASH;
            }
            for ( const hn of this.optionValues.get('fromList') ) {
                this.compileToAtomicFilter(hn, writer);
            }
            return;
        }

        const units = [];

        // Pattern
        const patternClass = this.compilePattern(units);

        // Anchor: must never appear before pattern unit
        if ( (this.anchor & 0b100) !== 0 ) {
            if ( this.isPureHostname ) {
                units.push(FilterAnchorHn.compile());
            } else {
                units.push(FilterAnchorHnLeft.compile());
            }
        } else if ( (this.anchor & 0b010) !== 0 ) {
            units.push(FilterAnchorLeft.compile());
        }
        if ( (this.anchor & 0b001) !== 0 ) {
            units.push(FilterAnchorRight.compile());
        }

        // Method(s)
        if ( this.methodBits !== 0 || this.notMethodBits !== 0 ) {
            units.push(FilterMethod.compile(this));
        }

        // Not types
        if ( this.notTypeBits !== 0 ) {
            units.push(FilterNotType.compile(this));
        }

        // Strict partiness
        if ( this.strictParty !== 0 ) {
            units.push(FilterStrictParty.compile(this));
        }

        // Origin
        if ( (this.optionUnitBits & FROM_BIT) !== 0 ) {
            compileFromDomainOpt(
                this.optionValues.get('fromList'),
                units.length !== 0 && patternClass.isSlow === true,
                units
            );
        }

        // Destination
        if ( (this.optionUnitBits & TO_BIT) !== 0 ) {
            compileToDomainOpt(
                this.optionValues.get('toList'),
                units.length !== 0 && patternClass.isSlow === true,
                units
            );
        }

        // Deny-allow
        if ( (this.optionUnitBits & DENYALLOW_BIT) !== 0 ) {
            units.push(FilterDenyAllow.compile(this));
        }

        // IP address
        if ( (this.optionUnitBits & IPADDRESS_BIT) !== 0 ) {
            units.push(FilterIPAddress.compile(this));
        }

        // Header
        if ( (this.optionUnitBits & HEADER_BIT) !== 0 ) {
            units.push(FilterOnHeaders.compile(this));
            this.action |= HEADERS_REALM;
        }

        // Message
        if ( (this.optionUnitBits & MESSAGE_BIT) !== 0 ) {
            units.push(FilterMessage.compile(this));
        }

        // Important
        //
        // IMPORTANT: must always appear at the end of the sequence, so as to
        // ensure $isBlockImportant is set only for matching filters.
        if ( (this.optionUnitBits & IMPORTANT_BIT) !== 0 ) {
            units.push(FilterImportant.compile());
        }

        // Modifier
        //
        // IMPORTANT: the modifier unit MUST always appear first in a sequence
        if ( this.modifyType !== undefined ) {
            units.unshift(FilterModifier.compile(this));
            this.action = (this.action & ~BLOCKALLOW_REALM) |
                modifierBitsFromType.get(this.modifyType);
        }

        const fdata = units.length === 1
            ? units[0]
            : FilterCompositeAll.compile(units);

        this.compileToAtomicFilter(fdata, writer);

        if ( (this.optionUnitBits & IPADDRESS_BIT) !== 0 ) {
            if ( (this.action & HEADERS_REALM) !== 0 ) { return; }
            this.action |= HEADERS_REALM;
            this.compileToAtomicFilter(fdata, writer);
        }
    }

    compilePattern(units) {
        if ( this.isRegex ) {
            units.push(FilterRegex.compile(this));
            return FilterRegex;
        }
        if ( this.pattern === '*' ) {
            units.push(FilterPatternAny.compile());
            return FilterPatternAny;
        }
        if ( this.tokenHash === NO_TOKEN_HASH ) {
            units.push(FilterPatternGeneric.compile(this));
            return FilterPatternGeneric;
        }
        if ( this.pattern.includes('*') === false ) {
            const caretPos = this.pattern.indexOf('^');
            if ( caretPos === -1 ) {
                units.push(FilterPatternPlain.compile(this));
                return FilterPatternPlain;
            }
            if ( caretPos === (this.pattern.length - 1) ) {
                this.pattern = this.pattern.slice(0, -1);
                units.push(FilterPatternPlain.compile(this));
                units.push(FilterTrailingSeparator.compile());
                return FilterPatternPlain;
            }
        }
        units.push(FilterPatternGeneric.compile(this));
        return FilterPatternGeneric;
    }

    compileToAtomicFilter(fdata, writer) {
        const catBits = this.action | this.party;
        let { typeBits } = this;

        // Typeless
        if ( typeBits === 0 ) {
            writer.push([ catBits, this.tokenHash, fdata ]);
            return;
        }
        // If all network types are set, create a typeless filter. Excluded
        // network types are tested at match time, se we act as if they are
        // set.
        if ( (typeBits & allNetworkTypesBits) === allNetworkTypesBits ) {
            writer.push([ catBits, this.tokenHash, fdata ]);
            typeBits &= ~allNetworkTypesBits;
            if ( typeBits === 0 ) { return; }
        }
        // One filter per specific types
        let bitOffset = 1;
        do {
            if ( typeBits & 1 ) {
                writer.push([
                    catBits | (bitOffset << TYPE_REALM_OFFSET),
                    this.tokenHash,
                    fdata
                ]);
            }
            bitOffset += 1;
            typeBits >>>= 1;
        } while ( typeBits !== 0 );
    }
}

// These are to quickly test whether a filter is composite
const FROM_BIT         = 0b00000000001;
const TO_BIT           = 0b00000000010;
const DENYALLOW_BIT    = 0b00000000100;
const HEADER_BIT       = 0b00000001000;
const STRICT_PARTY_BIT = 0b00000010000;
const MODIFY_BIT       = 0b00000100000;
const NOT_TYPE_BIT     = 0b00001000000;
const IMPORTANT_BIT    = 0b00010000000;
const METHOD_BIT       = 0b00100000000;
const IPADDRESS_BIT    = 0b01000000000;
const MESSAGE_BIT      = 0b10000000000

FilterCompiler.prototype.FILTER_OK          = 0;
FilterCompiler.prototype.FILTER_INVALID     = 1;
FilterCompiler.prototype.FILTER_UNSUPPORTED = 2;

/******************************************************************************/
/******************************************************************************/

const StaticNetFilteringEngine = function() {
    this.compilerVersion = '10';
    this.selfieVersion = '10';

    this.MAX_TOKEN_LENGTH = MAX_TOKEN_LENGTH;
    this.optimizeTaskId = undefined;
    // As long as CategoryCount is reasonably low, we will use an array to
    // store buckets using category bits as index. If ever CategoryCount
    // becomes too large, we can just go back to using a Map.
    this.bitsToBucket = new Map();
    this.goodFilters = new Set();
    this.badFilters = new Set();
    this.unitsToOptimize = [];
    this.reset();
};

/******************************************************************************/

StaticNetFilteringEngine.prototype.prime = function() {
    origHNTrieContainer.reset(
        keyvalStore.getItem('SNFE.origHNTrieContainer.trieDetails')
    );
    destHNTrieContainer.reset(
        keyvalStore.getItem('SNFE.destHNTrieContainer.trieDetails')
    );
};

/******************************************************************************/

StaticNetFilteringEngine.prototype.reset = function() {
    this.processedFilterCount = 0;
    this.acceptedCount = 0;
    this.discardedCount = 0;
    this.goodFilters.clear();
    this.badFilters.clear();
    this.unitsToOptimize.length = 0;
    this.bitsToBucket.clear();

    urlTokenizer.resetKnownTokens();

    filterDataReset();
    filterRefsReset();
    origHNTrieContainer.reset();
    destHNTrieContainer.reset();
    bidiTrie.reset();
    filterArgsToUnit.clear();

    // Cancel potentially pending optimization run.
    if ( this.optimizeTaskId !== undefined ) {
        dropTask(this.optimizeTaskId);
        this.optimizeTaskId = undefined;
    }

    this.notReady = false;

    // Runtime registers
    this.$catBits = 0;
    this.$tokenHash = 0;
    this.$filterUnit = 0;
};

/******************************************************************************/

StaticNetFilteringEngine.prototype.freeze = function() {
    const unserialize = CompiledListReader.unserialize;

    for ( const line of this.goodFilters ) {
        if ( this.badFilters.has(line) ) {
            this.discardedCount += 1;
            continue;
        }

        const args = unserialize(line);

        const bits = args[0];
        const bucket = this.bitsToBucket.get(bits) || (new Map());
        if ( bucket.size === 0 ) {
            this.bitsToBucket.set(bits, bucket);
        }

        const tokenHash = args[1];
        const fdata = args[2];

        let iunit = bucket.get(tokenHash) || 0;

        if ( tokenHash === DOT_TOKEN_HASH ) {
            if ( iunit === 0 ) {
                iunit = FilterHostnameDict.create();
                bucket.set(DOT_TOKEN_HASH, iunit);
                this.unitsToOptimize.push({ bits, tokenHash });
            }
            FilterHostnameDict.add(iunit, fdata);
            continue;
        }

        if ( tokenHash === ANY_TOKEN_HASH ) {
            if ( iunit === 0 ) {
                iunit = FilterJustOrigin.create();
                bucket.set(ANY_TOKEN_HASH, iunit);
            }
            FilterJustOrigin.add(iunit, fdata);
            continue;
        }

        if ( tokenHash === ANY_HTTPS_TOKEN_HASH ) {
            if ( iunit === 0 ) {
                iunit = FilterHTTPSJustOrigin.create();
                bucket.set(ANY_HTTPS_TOKEN_HASH, iunit);
            }
            FilterHTTPSJustOrigin.add(iunit, fdata);
            continue;
        }

        if ( tokenHash === ANY_HTTP_TOKEN_HASH ) {
            if ( iunit === 0 ) {
                iunit = FilterHTTPJustOrigin.create();
                bucket.set(ANY_HTTP_TOKEN_HASH, iunit);
            }
            FilterHTTPJustOrigin.add(iunit, fdata);
            continue;
        }

        urlTokenizer.addKnownToken(tokenHash);

        this.addFilterUnit(bits, tokenHash, filterFromCompiled(fdata));

        // Add block-important filters to the block realm, so as to avoid
        // to unconditionally match against the block-important realm for
        // every network request. Block-important filters are quite rare so
        // the block-important realm should be checked when and only when
        // there is a matched exception filter, which important filters are
        // meant to override.
        if ( (bits & BLOCKALLOW_REALM) === BLOCKIMPORTANT_REALM ) {
            this.addFilterUnit(
                bits & ~IMPORTANT_REALM,
                tokenHash,
                filterFromCompiled(fdata)
            );
        }
    }

    this.badFilters.clear();
    this.goodFilters.clear();
    filterArgsToUnit.clear();

    this.notReady = false;

    // Optimizing is not critical for the static network filtering engine to
    // work properly, so defer this until later to allow for reduced delay to
    // readiness when no valid selfie is available.
    if ( this.optimizeTaskId !== undefined ) { return; }

    this.optimizeTaskId = queueTask(( ) => {
        this.optimizeTaskId = undefined;
        this.optimize(30);
    }, 2000);
};

/******************************************************************************/

StaticNetFilteringEngine.prototype.dnrFromCompiled = function(op, context, ...args) {
    if ( op === 'begin' ) {
        Object.assign(context, {
            good: new Set(),
            bad: new Set(context.bad),
            invalid: new Set(),
            filterCount: 0,
            acceptedFilterCount: 0,
            rejectedFilterCount: 0,
        });
        return;
    }

    if ( op === 'add' ) {
        const reader = args[0];
        reader.select('NETWORK_FILTERS:GOOD');
        while ( reader.next() ) {
            context.filterCount += 1;
            if ( context.good.has(reader.line) === false ) {
                context.good.add(reader.line);
            }
        }
        reader.select('NETWORK_FILTERS:BAD');
        while ( reader.next() ) {
            context.bad.add(reader.line);
        }
        return;
    }

    if ( op !== 'end' ) { return; }

    const { good, bad } = context;
    const unserialize = CompiledListReader.unserialize;
    const buckets = new Map();

    for ( const line of good ) {
        if ( bad.has(line) ) {
            context.rejectedFilterCount += 1;
            continue;
        }
        context.acceptedFilterCount += 1;

        const args = unserialize(line);
        const bits = args[0];
        const tokenHash = args[1];
        const fdata = args[2];

        if ( buckets.has(bits) === false ) {
            buckets.set(bits, new Map());
        }
        const bucket = buckets.get(bits);

        switch ( tokenHash ) {
        case DOT_TOKEN_HASH: {
            if ( bucket.has(DOT_TOKEN_HASH) === false ) {
                bucket.set(DOT_TOKEN_HASH, [{
                    condition: {
                        requestDomains: []
                    }
                }]);
            }
            const rule = bucket.get(DOT_TOKEN_HASH)[0];
            rule.condition.requestDomains.push(fdata);
            break;
        }
        case ANY_TOKEN_HASH: {
            if ( bucket.has(ANY_TOKEN_HASH) === false ) {
                bucket.set(ANY_TOKEN_HASH, [{
                    condition: {
                        initiatorDomains: []
                    }
                }]);
            }
            const rule = bucket.get(ANY_TOKEN_HASH)[0];
            rule.condition.initiatorDomains.push(fdata);
            break;
        }
        case ANY_HTTPS_TOKEN_HASH: {
            if ( bucket.has(ANY_HTTPS_TOKEN_HASH) === false ) {
                bucket.set(ANY_HTTPS_TOKEN_HASH, [{
                    condition: {
                        urlFilter: '|https://',
                        initiatorDomains: []
                    }
                }]);
            }
            const rule = bucket.get(ANY_HTTPS_TOKEN_HASH)[0];
            rule.condition.initiatorDomains.push(fdata);
            break;
        }
        case ANY_HTTP_TOKEN_HASH: {
            if ( bucket.has(ANY_HTTP_TOKEN_HASH) === false ) {
                bucket.set(ANY_HTTP_TOKEN_HASH, [{
                    condition: {
                        urlFilter: '|http://',
                        initiatorDomains: []
                    }
                }]);
            }
            const rule = bucket.get(ANY_HTTP_TOKEN_HASH)[0];
            rule.condition.initiatorDomains.push(fdata);
            break;
        }
        default: {
            if ( bucket.has(EMPTY_TOKEN_HASH) === false ) {
                bucket.set(EMPTY_TOKEN_HASH, []);
            }
            const rule = {};
            dnrRuleFromCompiled(fdata, rule);
            bucket.get(EMPTY_TOKEN_HASH).push(rule);
            break;
        }
        }
    }

    // Priority:
    //   Removeparam: 1-4
    //   Block: 10 (default priority)
    //   Redirect: 11-19
    //   Excepted redirect: 21-29
    //   Allow: 30
    //   Block important: 40
    //   Redirect important: 41-49

    const realms = new Map([
        [ BLOCK_REALM, { type: 'block', priority: 10 } ],
        [ ALLOW_REALM, { type: 'allow', priority: 30 } ],
        [ BLOCK_REALM | IMPORTANT_REALM, { type: 'block', priority: 10 } ],
        [ REDIRECT_REALM, { type: 'redirect', priority: 11 } ],
        [ REMOVEPARAM_REALM, { type: 'removeparam', priority: 0 } ],
        [ CSP_REALM, { type: 'csp', priority: 0 } ],
        [ PERMISSIONS_REALM, { type: 'permissions', priority: 0 } ],
        [ URLTRANSFORM_REALM, { type: 'uritransform', priority: 0 } ],
        [ HEADERS_REALM, { type: 'block', priority: 10 } ],
        [ HEADERS_REALM | ALLOW_REALM, { type: 'allow', priority: 30 } ],
        [ HEADERS_REALM | IMPORTANT_REALM, { type: 'allow', priority: 10 } ],
        [ URLSKIP_REALM, { type: 'urlskip', priority: 0 } ],
    ]);
    const partyness = new Map([
        [ ANYPARTY_REALM, '' ],
        [ FIRSTPARTY_REALM, 'firstParty' ],
        [ THIRDPARTY_REALM, 'thirdParty' ],
    ]);
    const types = new Set([
        'no_type',
        'stylesheet',
        'image',
        'object',
        'script',
        'xmlhttprequest',
        'sub_frame',
        'main_frame',
        'font',
        'media',
        'websocket',
        'ping',
        'other',
    ]);
    const ruleset = [];
    const seen = new Set();
    for ( const [ realmBits, realmDetails ] of realms ) {
        for ( const [ partyBits, partyName ] of partyness ) {
            for ( const typeName in typeNameToTypeValue ) {
                if ( types.has(typeName) === false ) { continue; }
                const typeBits = typeNameToTypeValue[typeName];
                const bits = realmBits | partyBits | typeBits;
                const bucket = buckets.get(bits);
                if ( bucket === undefined ) { continue; }
                for ( const rules of bucket.values() ) {
                    for ( const rule of rules ) {
                        rule.action = rule.action || {};
                        rule.action.type = realmDetails.type;
                        if ( realmDetails.priority !== 0 ) {
                            rule.priority = (rule.priority || 0) + realmDetails.priority;
                        }
                        if ( partyName !== '' ) {
                            rule.condition = rule.condition || {};
                            rule.condition.domainType = partyName;
                        }
                        if ( typeName !== 'no_type' ) {
                            rule.condition = rule.condition || {};
                            rule.condition.resourceTypes = [ typeName ];
                        }
                        const hash = JSON.stringify(rule);
                        if ( seen.has(hash) ) { continue; }
                        seen.add(hash);
                        ruleset.push(rule);
                    }
                }
            }
        }
    }
    seen.clear();

    // Adjust `important` priority
    // Mind:
    // - https://github.com/uBlockOrigin/uAssets/issues/29451#issuecomment-3150181993
    for ( const rule of ruleset ) {
        if ( rule.__important !== true ) { continue; }
        if ( rule.priority === undefined ) {
            if ( rule.__modifierType !== 'removeparam' ) { continue; }
            rule.priority ||= 0;
        }
        rule.priority += 30;
    }

    // Collect generichide filters
    const generichideExclusions = [];
    const generichideInclusions = [];
    {
        const bucket = buckets.get(ALLOW_REALM | typeNameToTypeValue['generichide']);
        if ( bucket ) {
            for ( const rules of bucket.values() ) {
                for ( const rule of rules ) {
                    if ( rule.condition === undefined ) { continue; }
                    if ( rule.condition.initiatorDomains ) {
                        generichideExclusions.push(...rule.condition.initiatorDomains);
                    } else if ( rule.condition.requestDomains ) {
                        generichideExclusions.push(...rule.condition.requestDomains);
                    }
                    if ( rule.condition.excludedInitiatorDomains ) {
                        generichideInclusions.push(...rule.condition.excludedInitiatorDomains);
                    } else if ( rule.condition.excludedRequestDomains ) {
                        generichideInclusions.push(...rule.condition.excludedRequestDomains);
                    }
                }
            }
        }
    }
    {
        const bucket = buckets.get(BLOCKIMPORTANT_REALM | typeNameToTypeValue['generichide']);
        if ( bucket ) {
            for ( const rules of bucket.values() ) {
                for ( const rule of rules ) {
                    if ( rule.condition === undefined ) { continue; }
                    if ( rule.condition.initiatorDomains ) {
                        generichideInclusions.push(...rule.condition.initiatorDomains);
                    } else if ( rule.condition.requestDomains ) {
                        generichideInclusions.push(...rule.condition.requestDomains);
                    }
                }
            }
        }
    }

    // Detect and attempt salvage of rules with entity-based hostnames and/or
    // regex-based domains.
    const isUnsupportedDomain = hn => hn.endsWith('.*') || hn.startsWith('/');
    for ( const rule of ruleset ) {
        if ( rule.condition === undefined ) { continue; }
        for ( const prop of [ 'Initiator', 'Request' ] ) {
            const hitProp = `${prop.toLowerCase()}Domains`;
            if ( Array.isArray(rule.condition[hitProp]) ) {
                if ( rule.condition[hitProp].some(hn => isUnsupportedDomain(hn)) ) {
                    const domains = rule.condition[hitProp].filter(
                        hn => isUnsupportedDomain(hn) === false 
                    );
                    if ( domains.length === 0 ) {
                        dnrAddRuleError(rule, `Can't salvage rule with unsupported domain= option: ${rule.condition[hitProp].join('|')}`);
                    } else {
                        dnrAddRuleWarning(rule, `Salvaged rule by ignoring ${rule.condition[hitProp].length - domains.length} unsupported domain= option: ${rule.condition[hitProp].join('|')}`);
                        rule.condition[hitProp] = domains;
                    }
                }
            }
            const missProp = `excluded${prop}Domains`;
            if ( Array.isArray(rule.condition[missProp]) ) {
                if ( rule.condition[missProp].some(hn => isUnsupportedDomain(hn)) ) {
                    const domains = rule.condition[missProp].filter(
                        hn => isUnsupportedDomain(hn) === false
                    );
                    rule.condition[missProp] =
                        domains.length !== 0
                            ? domains
                            : undefined;
                }
            }
        }
    }

    // Patch modifier filters
    for ( const rule of ruleset ) {
        if ( rule.__modifierType === undefined ) { continue; }
        let patchDomainOption = false;
        switch ( rule.__modifierType ) {
        case 'csp':
            rule.action.type = 'modifyHeaders';
            rule.action.responseHeaders = [{
                header: 'content-security-policy',
                operation: 'append',
                value: rule.__modifierValue,
            }];
            if ( rule.__modifierAction === ALLOW_REALM ) {
                dnrAddRuleError(rule, `Unsupported csp exception: ${rule.__modifierValue}`);
            }
            break;
        case 'permissions':
            rule.action.type = 'modifyHeaders';
            rule.action.responseHeaders = [{
                header: 'permissions-policy',
                operation: 'append',
                value: rule.__modifierValue.split('|').join(', '),
            }];
            if ( rule.__modifierAction === ALLOW_REALM ) {
                dnrAddRuleError(rule, `Unsupported permissions exception: ${rule.__modifierValue}`);
            }
            patchDomainOption = true;
            break;
        case 'redirect-rule': {
            let token = rule.__modifierValue;
            if ( token !== '' ) {
                const match = /:(\d+)$/.exec(token);
                if ( match !== null ) {
                    rule.priority += Math.min(parseInt(match[1], 10), 8);
                    token = token.slice(0, match.index);
                }
            }
            const resource = context.extensionPaths.get(token);
            if ( rule.__modifierValue !== '' && resource === undefined ) {
                dnrAddRuleError(rule, `Unpatchable redirect filter: ${rule.__modifierValue}`);
            }
            if ( rule.__modifierAction !== ALLOW_REALM ) {
                const extensionPath = resource || token;
                rule.action.type = 'redirect';
                rule.action.redirect = { extensionPath };
            } else {
                rule.action.type = 'block';
                rule.priority += 10;
            }
            break;
        }
        case 'removeparam': {
            rule.action.type = 'redirect';
            if ( rule.__modifierValue === '|' ) {
                rule.__modifierValue = '';
            }
            if ( rule.__modifierValue !== '' ) {
                rule.action.redirect = {
                    transform: {
                        queryTransform: {
                            removeParams: [ rule.__modifierValue ]
                        }
                    }
                };
                if ( /^~?\/.+\/$/.test(rule.__modifierValue) ) {
                    dnrAddRuleError(rule, `Unsupported regex-based removeParam: ${rule.__modifierValue}`);
                }
            } else {
                rule.action.redirect = {
                    transform: {
                        query: ''
                    }
                };
            }
            if ( rule.condition === undefined ) {
                rule.condition = {
                };
            }
            if ( rule.condition.resourceTypes === undefined ) {
                if ( rule.condition.excludedResourceTypes === undefined ) {
                    rule.condition.resourceTypes = [
                        'main_frame',
                        'sub_frame',
                        'xmlhttprequest',
                    ];
                }
            }
            // https://github.com/uBlockOrigin/uBOL-home/issues/140
            //   Mitigate until DNR API flaw is addressed by browser vendors
            let priority = rule.priority || 1;
            if ( rule.condition.urlFilter !== undefined ) { priority += 1; }
            if ( rule.condition.regexFilter !== undefined ) { priority += 1; }
            if ( rule.condition.initiatorDomains !== undefined ) { priority += 1; }
            if ( rule.condition.requestDomains !== undefined ) { priority += 1; }
            if ( priority !== 1 ) {
                rule.priority = priority;
            }
            if ( rule.__modifierAction === ALLOW_REALM ) {
                dnrAddRuleError(rule, `Unsupported removeparam exception: ${rule.__modifierValue}`);
            }
            break;
        }
        case 'uritransform': {
            const parsed = sfp.parseReplaceByRegexValue(rule.__modifierValue);
            if ( parsed.re !== undefined ) {
                dnrAddRuleError(rule, `Incompatible with DNR: uritransform=${rule.__modifierValue}`);
                break;
            }
            if ( rule.condition.regexFilter === undefined ) {
                dnrAddRuleError(rule, `Incompatible with DNR (need regexFilter): uritransform=${rule.__modifierValue}`);
                break;
            }
            rule.action.type = 'redirect';
            rule.action.redirect = {
                regexSubstitution: parsed.replacement.replace(/\$(\d+)/g, '\\$1')
            };
            break;
        }
        case 'urlskip': {
            let urlFilter = rule.condition?.urlFilter;
            if ( urlFilter === undefined ) { break; }
            let anchor = 0b000;
            if ( urlFilter.startsWith('||') ) {
                anchor |= 0b100;
                urlFilter = urlFilter.slice(2);
            } else if ( urlFilter.startsWith('|') ) {
                anchor |= 0b10;
                urlFilter = urlFilter.slice(1);
            }
            if ( urlFilter.endsWith('|') ) {
                anchor |= 0b001;
                urlFilter = urlFilter.slice(0, -1);
            }
            rule.condition.urlFilter = undefined;
            rule.condition.regexFilter = restrFromGenericPattern(urlFilter, anchor);
            break;
        }
        default:
            dnrAddRuleError(rule, `Unsupported modifier ${rule.__modifierType}`);
            break;
        }

        // Some modifiers only work on document resources
        // Related issue: https://github.com/uBlockOrigin/uBOL-home/issues/156
        if ( patchDomainOption ) {
            const domains = rule.condition.initiatorDomains;
            if ( Array.isArray(domains) && domains.length !== 0 ) {
                rule.condition.requestDomains ||= [];
                rule.condition.requestDomains.push(...domains);
            }
            const notDomains = rule.condition.excludedInitiatorDomains;
            if ( Array.isArray(notDomains) && notDomains.length !== 0 ) {
                rule.condition.excludedRequestDomains ||= [];
                rule.condition.excludedRequestDomains.push(...notDomains);
            }
        }
    }

    return {
        ruleset,
        filterCount: context.filterCount,
        acceptedFilterCount: context.acceptedFilterCount,
        rejectedFilterCount: context.rejectedFilterCount,
        generichideExclusions: Array.from(new Set(generichideExclusions)),
        generichideInclusions: Array.from(new Set(generichideInclusions)),
    };
};

/******************************************************************************/

StaticNetFilteringEngine.prototype.addFilterUnit = function(
    bits,
    tokenHash,
    inewunit
) {
    const bucket = this.bitsToBucket.get(bits) || (new Map());
    if ( bucket.size === 0 ) {
        this.bitsToBucket.set(bits, bucket);
    }
    const istoredunit = bucket.get(tokenHash) || 0;
    if ( istoredunit === 0 ) {
        bucket.set(tokenHash, inewunit);
        return;
    }
    if ( filterData[istoredunit+0] === FilterBucket.fid ) {
        FilterBucket.unshift(istoredunit, inewunit);
        return;
    }
    const ibucketunit = FilterBucket.create();
    FilterBucket.unshift(ibucketunit, istoredunit);
    FilterBucket.unshift(ibucketunit, inewunit);
    bucket.set(tokenHash, ibucketunit);
    this.unitsToOptimize.push({ bits, tokenHash });
};

/******************************************************************************/

StaticNetFilteringEngine.prototype.optimize = function(throttle = 0) {
    if ( this.optimizeTaskId !== undefined ) {
        dropTask(this.optimizeTaskId);
        this.optimizeTaskId = undefined;
    }

    const later = throttle => {
        this.optimizeTaskId = queueTask(( ) => {
            this.optimizeTaskId = undefined;
            this.optimize(throttle);
        }, 1000);
    };

    const t0 = Date.now();
    while ( this.unitsToOptimize.length !== 0 ) {
        const { bits, tokenHash } = this.unitsToOptimize.pop();
        const bucket = this.bitsToBucket.get(bits);
        const iunit = bucket.get(tokenHash);
        const fc = filterGetClass(iunit);
        switch ( fc ) {
        case FilterHostnameDict:
            FilterHostnameDict.optimize(iunit);
            break;
        case FilterBucket: {
            const optimizeBits =
                (tokenHash === NO_TOKEN_HASH) || (bits & MODIFY_REALMS) !== 0
                    ? 0b10
                    : 0b01;
            const inewunit = FilterBucket.optimize(iunit, optimizeBits);
            if ( inewunit !== 0 ) {
                bucket.set(tokenHash, inewunit);
            }
            break;
        }
        default:
            break;
        }
        if ( throttle > 0 && (Date.now() - t0) > 40 ) {
            return later(throttle - 1);
        }
    }

    filterArgsToUnit.clear();

    // Here we do not optimize origHNTrieContainer because many origin-related
    // tries are instantiated on demand.
    keyvalStore.setItem(
        'SNFE.destHNTrieContainer.trieDetails',
        destHNTrieContainer.optimize()
    );
    filterDataShrink();
};

/******************************************************************************/

StaticNetFilteringEngine.prototype.toSelfie = function() {
    this.optimize(0);
    bidiTrie.optimize();
    keyvalStore.setItem('SNFE.origHNTrieContainer.trieDetails',
        origHNTrieContainer.optimize()
    );
    return {
        version: this.selfieVersion,
        processedFilterCount: this.processedFilterCount,
        acceptedCount: this.acceptedCount,
        discardedCount: this.discardedCount,
        bitsToBucket: this.bitsToBucket,
        urlTokenizer: urlTokenizer.toSelfie(),
        destHNTrieContainer: destHNTrieContainer.toSelfie(),
        origHNTrieContainer: origHNTrieContainer.toSelfie(),
        bidiTrie: bidiTrie.toSelfie(),
        filterData: filterDataToSelfie(),
        filterRefs: filterRefsToSelfie(),
    };
};

StaticNetFilteringEngine.prototype.serialize = function() {
    return this.toSelfie();
};

/******************************************************************************/

StaticNetFilteringEngine.prototype.fromSelfie = function(selfie) {
    if ( typeof selfie !== 'object' || selfie === null ) { return; }

    this.reset();

    this.notReady = true;

    const results = [
        destHNTrieContainer.fromSelfie(selfie.destHNTrieContainer),
        origHNTrieContainer.fromSelfie(selfie.origHNTrieContainer),
        bidiTrie.fromSelfie(selfie.bidiTrie),
        filterDataFromSelfie(selfie.filterData),
        filterRefsFromSelfie(selfie.filterRefs),
    ];
    if ( results.slice(1).every(v => v === true) === false ) { return false; }

    if ( selfie.version !== this.selfieVersion ) { return false; }
    this.processedFilterCount = selfie.processedFilterCount;
    this.acceptedCount = selfie.acceptedCount;
    this.discardedCount = selfie.discardedCount;
    this.bitsToBucket = selfie.bitsToBucket;
    urlTokenizer.fromSelfie(selfie.urlTokenizer);

    // If this point is never reached, it means the internal state is
    // unreliable, and the caller is then responsible for resetting the
    // engine and populate properly, in which case the `notReady` barrier
    // will be properly reset.

    this.notReady = false;

    return true;
};

StaticNetFilteringEngine.prototype.unserialize = function(selfie) {
    return this.fromSelfie(selfie);
};

/******************************************************************************/

StaticNetFilteringEngine.prototype.createCompiler = function() {
    return new FilterCompiler();
};

/******************************************************************************/

StaticNetFilteringEngine.prototype.fromCompiled = function(reader) {
    reader.select('NETWORK_FILTERS:GOOD');
    while ( reader.next() ) {
        this.acceptedCount += 1;
        if ( this.goodFilters.has(reader.line) ) {
            this.discardedCount += 1;
        } else {
            this.goodFilters.add(reader.line);
        }
    }

    reader.select('NETWORK_FILTERS:BAD');
    while ( reader.next() ) {
        this.badFilters.add(reader.line);
    }
};

/******************************************************************************/

StaticNetFilteringEngine.prototype.matchAndFetchModifiers = function(
    fctxt,
    modifierName
) {
    if ( this.notReady ) { return; }

    const typeBits = typeNameToTypeValue[fctxt.type] || otherTypeBitValue;

    $requestURL = urlTokenizer.setURL(fctxt.url);
    $requestURLRaw = fctxt.url;
    $docHostname = fctxt.getDocHostname();
    $docDomain = fctxt.getDocDomain();
    $requestHostname = fctxt.getHostname();
    $requestMethodBit = fctxt.method || 0;
    $requestTypeValue = (typeBits & TYPE_REALM) >>> TYPE_REALM_OFFSET;
    $requestAddress = fctxt.getIPAddress();

    const modifierType = modifierTypeFromName.get(modifierName);
    const modifierBits = modifierBitsFromType.get(modifierType);

    const partyBits = fctxt.is3rdPartyToDoc() ? THIRDPARTY_REALM : FIRSTPARTY_REALM;

    const catBits00 = modifierBits;
    const catBits01 = modifierBits | typeBits;
    const catBits10 = modifierBits | partyBits;
    const catBits11 = modifierBits | typeBits | partyBits;

    const bucket00 = this.bitsToBucket.get(catBits00);
    const bucket01 = typeBits !== 0
        ? this.bitsToBucket.get(catBits01)
        : undefined;
    const bucket10 = partyBits !== 0
        ? this.bitsToBucket.get(catBits10)
        : undefined;
    const bucket11 = typeBits !== 0 && partyBits !== 0
        ? this.bitsToBucket.get(catBits11)
        : undefined;

    if (
        bucket00 === undefined && bucket01 === undefined &&
        bucket10 === undefined && bucket11 === undefined
    ) {
        return;
    }

    const results = [];
    const env = {
        type: modifierType || 0,
        bits: 0,
        th: 0,
        iunit: 0,
        results,
    };

    const tokenHashes = urlTokenizer.getTokens();
    let i = 0;
    let th = 0, iunit = 0;
    for (;;) {
        th = tokenHashes[i];
        if ( th === INVALID_TOKEN_HASH ) { break; }
        env.th = th;
        $tokenBeg = tokenHashes[i+1];
        if (
            (bucket00 !== undefined) &&
            (iunit = bucket00.get(th) || 0) !== 0
        ) {
            env.bits = catBits00; env.iunit = iunit;
            filterMatchAndFetchModifiers(iunit, env);
        }
        if (
            (bucket01 !== undefined) &&
            (iunit = bucket01.get(th) || 0) !== 0
        ) {
            env.bits = catBits01; env.iunit = iunit;
            filterMatchAndFetchModifiers(iunit, env);
        }
        if (
            (bucket10 !== undefined) &&
            (iunit = bucket10.get(th) || 0) !== 0
        ) {
            env.bits = catBits10; env.iunit = iunit;
            filterMatchAndFetchModifiers(iunit, env);
        }
        if (
            (bucket11 !== undefined) &&
            (iunit = bucket11.get(th) || 0) !== 0
        ) {
            env.bits = catBits11; env.iunit = iunit;
            filterMatchAndFetchModifiers(iunit, env);
        }
        i += 2;
    }

    if ( results.length === 0 ) { return; }

    // One single result is expected to be a common occurrence, and in such
    // case there is no need to process exception vs. block, block important
    // occurrences.
    if ( results.length === 1 ) {
        const result = results[0];
        if ( (result.bits & ALLOW_REALM) !== 0 ) { return; }
        return [ result ];
    }

    const toAddImportant = new Map();
    const toAdd = new Map();
    const toRemove = new Map();

    for ( const result of results ) {
        const actionBits = result.bits & BLOCKALLOW_REALM;
        const modifyValue = result.value;
        if ( actionBits === BLOCKIMPORTANT_REALM ) {
            toAddImportant.set(modifyValue, result);
        } else if ( actionBits === BLOCK_REALM ) {
            toAdd.set(modifyValue, result);
        } else {
            toRemove.set(modifyValue, result);
        }
    }
    if ( toAddImportant.size === 0 && toAdd.size === 0 ) { return; }

    // Remove entries overridden by important block filters.
    if ( toAddImportant.size !== 0 ) {
        for ( const key of toAddImportant.keys() ) {
            toAdd.delete(key);
            toRemove.delete(key);
        }
    }

    // Exception filters
    //
    // Remove excepted block filters and unused exception filters.
    //
    // Special case, except-all:
    // - Except-all applies only if there is at least one normal block filters.
    // - Except-all does not apply to important block filters.
    if ( toRemove.size !== 0 ) {
        if ( toRemove.has('') === false ) {
            for ( const key of toRemove.keys() ) {
                if ( toAdd.has(key) ) {
                    toAdd.delete(key);
                } else {
                    toRemove.delete(key);
                }
            }
        }
        else if ( toAdd.size !== 0 ) {
            toAdd.clear();
            if ( toRemove.size !== 1 ) {
                const entry = toRemove.get('');
                toRemove.clear();
                toRemove.set('', entry);
            }
        } else {
            toRemove.clear();
        }
    }

    if (
        toAdd.size === 0 &&
        toAddImportant.size === 0 &&
        toRemove.size === 0
    ) {
        return;
    }

    const out = Array.from(toAdd.values());
    if ( toAddImportant.size !== 0 ) {
        out.push(...toAddImportant.values());
    }
    if ( toRemove.size !== 0 ) {
        out.push(...toRemove.values());
    }
    return out;
};

/******************************************************************************/

StaticNetFilteringEngine.prototype.realmMatchString = function(
    realmBits,
    typeBits,
    partyBits
) {
    if ( this.notReady ) { return false; }

    const exactType = typeBits & 0x80000000;
    typeBits &= 0x7FFFFFFF;

    const catBits00 = realmBits;
    const catBits01 = realmBits | typeBits;
    const catBits10 = realmBits | partyBits;
    const catBits11 = realmBits | typeBits | partyBits;

    const bucket00 = exactType === 0
        ? this.bitsToBucket.get(catBits00)
        : undefined;
    const bucket01 = exactType !== 0 || typeBits !== 0
        ? this.bitsToBucket.get(catBits01)
        : undefined;
    const bucket10 = exactType === 0 && partyBits !== 0
        ? this.bitsToBucket.get(catBits10)
        : undefined;
    const bucket11 = (exactType !== 0 || typeBits !== 0) && partyBits !== 0
        ? this.bitsToBucket.get(catBits11)
        : undefined;

    if (
        bucket00 === undefined && bucket01 === undefined &&
        bucket10 === undefined && bucket11 === undefined
    ) {
        return false;
    }

    let catBits = 0, iunit = 0;

    // Pure hostname-based filters
    let tokenHash = DOT_TOKEN_HASH;
    if (
        (bucket00 !== undefined) &&
        (iunit = bucket00.get(DOT_TOKEN_HASH) || 0) !== 0 &&
        (filterMatch(iunit) === true)
    ) {
        catBits = catBits00;
    } else if (
        (bucket01 !== undefined) &&
        (iunit = bucket01.get(DOT_TOKEN_HASH) || 0) !== 0 &&
        (filterMatch(iunit) === true)
    ) {
        catBits = catBits01;
    } else if (
        (bucket10 !== undefined) &&
        (iunit = bucket10.get(DOT_TOKEN_HASH) || 0) !== 0 &&
        (filterMatch(iunit) === true)
    ) {
        catBits = catBits10;
    } else if (
        (bucket11 !== undefined) &&
        (iunit = bucket11.get(DOT_TOKEN_HASH) || 0) !== 0 &&
        (filterMatch(iunit) === true)
    ) {
        catBits = catBits11;
    }
    // Pattern-based filters
    else {
        const tokenHashes = urlTokenizer.getTokens();
        let i = 0;
        for (;;) {
            tokenHash = tokenHashes[i];
            if ( tokenHash === INVALID_TOKEN_HASH ) { return false; }
            $tokenBeg = tokenHashes[i+1];
            if (
                (bucket00 !== undefined) &&
                (iunit = bucket00.get(tokenHash) || 0) !== 0 &&
                (filterMatch(iunit) === true)
            ) {
                catBits = catBits00;
                break;
            }
            if (
                (bucket01 !== undefined) &&
                (iunit = bucket01.get(tokenHash) || 0) !== 0 &&
                (filterMatch(iunit) === true)
            ) {
                catBits = catBits01;
                break;
            }
            if (
                (bucket10 !== undefined) &&
                (iunit = bucket10.get(tokenHash) || 0) !== 0 &&
                (filterMatch(iunit) === true)
            ) {
                catBits = catBits10;
                break;
            }
            if (
                (bucket11 !== undefined) &&
                (iunit = bucket11.get(tokenHash) || 0) !== 0 &&
                (filterMatch(iunit) === true)
            ) {
                catBits = catBits11;
                break;
            }
            i += 2;
        }
    }

    this.$catBits = catBits;
    this.$tokenHash = tokenHash;
    this.$filterUnit = iunit;
    return true;
};

/******************************************************************************/

// Specialized handler

// https://github.com/gorhill/uBlock/issues/1477
//   Special case: blocking-generichide filter ALWAYS exists, it is implicit --
//   thus we always first check for exception filters, then for important block
//   filter if and only if there was a hit on an exception filter.
// https://github.com/gorhill/uBlock/issues/2103
//   User may want to override `generichide` exception filters.
// https://www.reddit.com/r/uBlockOrigin/comments/d6vxzj/
//   Add support for `specifichide`.

StaticNetFilteringEngine.prototype.matchRequestReverse = function(type, url) {
    const typeBits = typeNameToTypeValue[type] | 0x80000000;

    // Prime tokenizer: we get a normalized URL in return.
    $requestURL = urlTokenizer.setURL(url);
    $requestURLRaw = url;
    $requestMethodBit = 0;
    $requestTypeValue = (typeBits & TYPE_REALM) >>> TYPE_REALM_OFFSET;
    $requestAddress = '';
    $isBlockImportant = false;
    this.$filterUnit = 0;

    // These registers will be used by various filters
    $docHostname = $requestHostname = hostnameFromNetworkURL(url);
    $docDomain = domainFromHostname($docHostname);

    // Exception filters
    if ( this.realmMatchString(ALLOW_REALM, typeBits, FIRSTPARTY_REALM) ) {
        // Important block filters.
        if ( this.realmMatchString(BLOCKIMPORTANT_REALM, typeBits, FIRSTPARTY_REALM) ) {
            return 1;
        }
        return 2;
    }
    return 0;

};

/******************************************************************************/

// https://github.com/chrisaljoudi/uBlock/issues/116
//   Some type of requests are exceptional, they need custom handling,
//   not the generic handling.
// https://github.com/chrisaljoudi/uBlock/issues/519
//   Use exact type match for anything beyond `other`. Also, be prepared to
//   support unknown types.
// https://github.com/uBlockOrigin/uBlock-issues/issues/1501
//   Add support to evaluate allow realm before block realm.

/**
 * Matches a URL string using filtering context.
 * @param {FilteringContext} fctxt - The filtering context
 * @param {integer} [modifier=0] - A bit vector modifying the behavior of the
 *   matching algorithm:
 *   Bit 0: match exact type.
 *   Bit 1: lookup allow realm regardless of whether there was a match in
 *          block realm.
 *
 * @returns {integer} 0=no match, 1=block, 2=allow (exception)
 */
StaticNetFilteringEngine.prototype.matchRequest = function(fctxt, modifiers = 0) {
    let typeBits = typeNameToTypeValue[fctxt.type];
    if ( modifiers === 0 ) {
        if ( typeBits === undefined ) {
            typeBits = otherTypeBitValue;
        } else if ( typeBits === 0 || typeBits > otherTypeBitValue ) {
            modifiers |= 0b0001;
        }
    }
    if ( (modifiers & 0b0001) !== 0 ) {
        if ( typeBits === undefined ) { return 0; }
        typeBits |= 0x80000000;
    }

    const partyBits = fctxt.is3rdPartyToDoc() ? THIRDPARTY_REALM : FIRSTPARTY_REALM;

    // Prime tokenizer: we get a normalized URL in return.
    $requestURL = urlTokenizer.setURL(fctxt.url);
    $requestURLRaw = fctxt.url;
    this.$filterUnit = 0;

    // These registers will be used by various filters
    $docHostname = fctxt.getDocHostname();
    $docDomain = fctxt.getDocDomain();
    $requestHostname = fctxt.getHostname();
    $requestMethodBit = fctxt.method || 0;
    $requestTypeValue = (typeBits & TYPE_REALM) >>> TYPE_REALM_OFFSET;
    $requestAddress = fctxt.getIPAddress();
    $isBlockImportant = false;

    // Evaluate block realm before allow realm, and allow realm before
    // block-important realm, i.e. by order of likelihood of a match.
    const r = this.realmMatchString(BLOCK_REALM, typeBits, partyBits);
    if ( r || (modifiers & 0b0010) !== 0 ) {
        if ( $isBlockImportant ) { return 1; }
        if ( this.realmMatchString(ALLOW_REALM, typeBits, partyBits) ) {
            if ( this.realmMatchString(BLOCKIMPORTANT_REALM, typeBits, partyBits) ) {
                return 1;
            }
            return 2;
        }
        if ( r ) { return 1; }
    }
    return 0;
};

/******************************************************************************/

StaticNetFilteringEngine.prototype.matchHeaders = function(fctxt, headers) {
    const typeBits = typeNameToTypeValue[fctxt.type] || otherTypeBitValue;
    const partyBits = fctxt.is3rdPartyToDoc() ? THIRDPARTY_REALM : FIRSTPARTY_REALM;

    // Prime tokenizer: we get a normalized URL in return.
    $requestURL = urlTokenizer.setURL(fctxt.url);
    $requestURLRaw = fctxt.url;
    this.$filterUnit = 0;

    // These registers will be used by various filters
    $docHostname = fctxt.getDocHostname();
    $docDomain = fctxt.getDocDomain();
    $requestHostname = fctxt.getHostname();
    $requestMethodBit = fctxt.method || 0;
    $requestTypeValue = (typeBits & TYPE_REALM) >>> TYPE_REALM_OFFSET;
    $requestAddress = fctxt.getIPAddress();
    $isBlockImportant = false;
    $httpHeaders.init(headers);

    let r = 0;
    if ( this.realmMatchString(HEADERS_REALM | BLOCK_REALM, typeBits, partyBits) ) {
        r = 1;
    }
    if ( r !== 0 && $isBlockImportant !== true ) {
        if ( this.realmMatchString(HEADERS_REALM | ALLOW_REALM, typeBits, partyBits) ) {
            r = 2;
        } else if ( this.realmMatchString(ALLOW_REALM, typeBits, partyBits) ) {
            r = 2;
        }
        if ( r === 2 ) {
            if ( this.realmMatchString(HEADERS_REALM | BLOCKIMPORTANT_REALM, typeBits, partyBits) ) {
                r = 1;
            }
        }
    }

    $httpHeaders.reset();

    return r;
};

/******************************************************************************/

StaticNetFilteringEngine.prototype.redirectRequest = function(redirectEngine, fctxt) {
    const directives = this.matchAndFetchModifiers(fctxt, 'redirect-rule');
    // No directive is the most common occurrence.
    if ( directives === undefined ) { return; }
    const highest = directives.length - 1;
    // More than a single directive means more work.
    if ( highest !== 0 ) {
        directives.sort((a, b) => compareRedirectRequests(redirectEngine, a, b));
    }
    // Redirect to highest-ranked directive
    const directive = directives[highest];
    if ( (directive.bits & ALLOW_REALM) !== 0 ) { return directives; }
    const { token } = parseRedirectRequestValue(directive);
    fctxt.redirectURL = redirectEngine.tokenToURL(fctxt, token);
    if ( fctxt.redirectURL === undefined ) { return; }
    return directives;
};

function parseRedirectRequestValue(directive) {
    if ( directive.cache === null ) {
        directive.cache = sfp.parseRedirectValue(directive.value);
    }
    return directive.cache;
}

function compareRedirectRequests(redirectEngine, a, b) {
    const { token: atok, priority: aint, bits: abits } =
        parseRedirectRequestValue(a);
    if ( redirectEngine.hasToken(atok) === false ) { return -1; }
    const { token: btok, priority: bint, bits: bbits } =
        parseRedirectRequestValue(b);
    if ( redirectEngine.hasToken(btok) === false ) { return 1; }
    if ( abits !== bbits ) {
        if ( (abits & IMPORTANT_REALM) !== 0 ) { return 1; }
        if ( (bbits & IMPORTANT_REALM) !== 0 ) { return -1; }
        if ( (abits & ALLOW_REALM) !== 0 ) { return -1; }
        if ( (bbits & ALLOW_REALM) !== 0 ) { return 1; }
    }
    return aint - bint;
}

/******************************************************************************/

StaticNetFilteringEngine.prototype.transformURL = function(fctxt, out = []) {
    const directives = this.matchAndFetchModifiers(fctxt, 'uritransform');
    if ( directives === undefined ) { return; }
    const redirectURL = new URL(fctxt.url);
    for ( const directive of directives ) {
        if ( (directive.bits & ALLOW_REALM) !== 0 ) {
            out.push(directive);
            continue;
        }
        if ( directive.cache === null ) {
            directive.cache = sfp.parseReplaceByRegexValue(directive.value);
        }
        const cache = directive.cache;
        if ( cache === undefined ) { continue; }
        let { re } = cache;
        const before = redirectURL.href;
        if ( re === undefined ) {
            const logdata = directive.logData();
            if ( logdata === undefined ) { continue; }
            try { re = new RegExp(logdata.regex, cache.flags); }
            catch { continue; }
        }
        if ( re.test(before) !== true ) { continue; }
        const after = before.replace(re, cache.replacement);
        try { void new URL(after); } catch { continue; }
        if ( after === before ) { continue; }
        redirectURL.href = after;
        out.push(directive);
        break;
    }
    if ( out.length === 0 ) { return; }
    if ( redirectURL.href !== fctxt.url ) {
        fctxt.redirectURL = redirectURL.href;
    }
    return out;
};

StaticNetFilteringEngine.prototype.urlSkip = function(
    fctxt,
    blocked,
    out = []
) {
    if ( fctxt.redirectURL !== undefined ) { return; }
    const directives = this.matchAndFetchModifiers(fctxt, 'urlskip');
    if ( directives === undefined ) { return; }
    for ( const directive of directives ) {
        if ( (directive.bits & ALLOW_REALM) !== 0 ) {
            out.push(directive);
            continue;
        }
        const urlin = fctxt.url;
        const value = directive.value;
        const steps = value.includes(' ') && value.split(/ +/) || [ value ];
        const urlout = urlSkip(urlin, blocked, steps, directive);
        if ( urlout === undefined ) { continue; }
        if ( urlout === urlin ) { continue; }
        fctxt.redirectURL = urlout;
        out.push(directive);
        break;
    }
    if ( out.length === 0 ) { return; }
    return out;
};

/******************************************************************************/

// https://github.com/uBlockOrigin/uBlock-issues/issues/1626
//   Do not redirect when the number of query parameters does not change.

StaticNetFilteringEngine.prototype.filterQuery = function(fctxt, out = []) {
    if ( fctxt.redirectURL !== undefined ) { return; }
    const directives = this.matchAndFetchModifiers(fctxt, 'removeparam');
    if ( directives === undefined ) { return; }
    const url = fctxt.url;
    const qpos = url.indexOf('?');
    if ( qpos === -1 ) { return; }
    let hpos = url.indexOf('#', qpos + 1);
    if ( hpos === -1 ) { hpos = url.length; }
    const params = new Map();
    const query = url.slice(qpos + 1, hpos);
    for ( let i = 0; i < query.length; ) {
        let pos = query.indexOf('&', i);
        if ( pos === -1 ) { pos = query.length; }
        const kv = query.slice(i, pos);
        i = pos + 1;
        pos = kv.indexOf('=');
        if ( pos !== -1 ) {
            params.set(kv.slice(0, pos), kv.slice(pos + 1));
        } else {
            params.set(kv, '');
        }
    }
    const inParamCount = params.size;
    for ( const directive of directives ) {
        if ( params.size === 0 ) { break; }
        const isException = (directive.bits & ALLOW_REALM) !== 0;
        if ( isException && directive.value === '' ) {
            out.push(directive);
            break;
        }
        const { all, bad, name, not, re } = parseQueryPruneValue(directive);
        if ( bad ) { continue; }
        if ( all ) {
            if ( isException === false ) { params.clear(); }
            out.push(directive);
            break;
        }
        if ( name !== undefined ) {
            const value = params.get(name);
            if ( not === false ) {
                if ( value !== undefined ) {
                    if ( isException === false ) { params.delete(name); }
                    out.push(directive);
                }
                continue;
            }
            if ( value !== undefined ) { params.delete(name); }
            if ( params.size !== 0 ) {
                if ( isException === false ) { params.clear(); }
                out.push(directive);
            }
            if ( value !== undefined ) { params.set(name, value); }
            continue;
        }
        if ( re === undefined ) { continue; }
        let filtered = false;
        for ( const [ key, raw ] of params ) {
            let value = raw;
            try { value = decodeURIComponent(value); }
            catch { }
            if ( re.test(`${key}=${value}`) === not ) { continue; }
            if ( isException === false ) { params.delete(key); }
            filtered = true;
        }
        if ( filtered ) {
            out.push(directive);
        }
    }
    if ( out.length === 0 ) { return; }
    if ( params.size !== inParamCount ) {
        fctxt.redirectURL = url.slice(0, qpos);
        if ( params.size !== 0 ) {
            fctxt.redirectURL += '?' + Array.from(params).map(a =>
                a[1] === '' ? `${a[0]}=` : `${a[0]}=${a[1]}`
            ).join('&');
        }
        if ( hpos !== url.length ) {
            fctxt.redirectURL += url.slice(hpos);
        }
    }
    return out;
};

function parseQueryPruneValue(directive) {
    if ( directive.cache === null ) {
        directive.cache =
            sfp.parseQueryPruneValue(directive.value);
    }
    return directive.cache;
}

/******************************************************************************/

StaticNetFilteringEngine.prototype.hasQuery = function(fctxt) {
    urlTokenizer.setURL(fctxt.url);
    return urlTokenizer.hasQuery();
};

/******************************************************************************/

StaticNetFilteringEngine.prototype.toLogData = function() {
    if ( this.$filterUnit !== 0 ) {
        return new LogData(this.$catBits, this.$tokenHash, this.$filterUnit);
    }
};

/******************************************************************************/

StaticNetFilteringEngine.prototype.isBlockImportant = function() {
    return this.$filterUnit !== 0 && $isBlockImportant;
};

/******************************************************************************/

StaticNetFilteringEngine.prototype.getFilterCount = function() {
    return this.acceptedCount - this.discardedCount;
};

/******************************************************************************/

StaticNetFilteringEngine.prototype.enableWASM = function(wasmModuleFetcher, path) {
    return Promise.all([
        bidiTrie.enableWASM(wasmModuleFetcher, path),
        origHNTrieContainer.enableWASM(wasmModuleFetcher, path),
        destHNTrieContainer.enableWASM(wasmModuleFetcher, path),
    ]).then(results => {
        return results.every(a => a === true);
    });
};

/******************************************************************************/

StaticNetFilteringEngine.prototype.test = function(details) {
    const { url, type, from, redirectEngine } = details;
    if ( url === undefined ) { return; }
    const fctxt = new FilteringContext();
    fctxt.setURL(url);
    fctxt.setType(type || '');
    fctxt.setDocOriginFromURL(from || '');
    const r = this.matchRequest(fctxt);
    const out = [ `url: ${url}` ];
    if ( type ) {
        out.push(`type: ${type}`);
    }
    if ( from ) {
        out.push(`context: ${from}`);
    }
    if ( r !== 0 ) {
        const logdata = this.toLogData();
        if ( r === 1 ) {
            out.push(`blocked: ${logdata.raw}`);
        } else if ( r === 2 ) {
            out.push(`unblocked: ${logdata.raw}`);
        }
    } else {
        out.push('not blocked');
    }
    if ( r !== 1 ) {
        const entries = this.transformURL(fctxt);
        if ( entries ) {
            for ( const entry of entries ) {
                out.push(`modified: ${entry.logData().raw}`);
            }
        }
        if ( fctxt.redirectURL !== undefined && this.hasQuery(fctxt) ) {
            const entries = this.filterQuery(fctxt, 'removeparam');
            if ( entries ) {
                for ( const entry of entries ) {
                    out.push(`modified: ${entry.logData().raw}`);
                }
            }
        }
        if ( fctxt.type === 'main_frame' || fctxt.type === 'sub_frame' ) {
            const csps = this.matchAndFetchModifiers(fctxt, 'csp');
            if ( csps ) {
                for ( const csp of csps ) {
                    out.push(`modified: ${csp.logData().raw}`);
                }
            }
            const pps = this.matchAndFetchModifiers(fctxt, 'permissions');
            if ( pps ) {
                for ( const pp of pps ) {
                    out.push(`modified: ${pp.logData().raw}`);
                }
            }
        }
    } else if ( redirectEngine ) {
        const redirects = this.redirectRequest(redirectEngine, fctxt);
        if ( redirects ) {
            for ( const redirect of redirects ) {
                out.push(`modified: ${redirect.logData().raw}`);
            }
        }
    }
    const urlskips = this.matchAndFetchModifiers(fctxt, 'urlskip');
    if ( urlskips ) {
        for ( const urlskip of urlskips ) {
            out.push(`modified: ${urlskip.logData().raw}`);
        }
    }
    return out.join('\n');
}

/******************************************************************************/

StaticNetFilteringEngine.prototype.bucketHistogram = function() {
    const results = [];
    for ( const [ bits, bucket ] of this.bitsToBucket ) {
        for ( const [ th, iunit ] of bucket ) {
            const token = urlTokenizer.stringFromTokenHash(th);
            const fc = filterGetClass(iunit);
            const count = fc.getCount !== undefined ? fc.getCount(iunit) : 1;
            results.push({ bits: bits.toString(16), token, count, f: fc.name });
        }
    }
    results.sort((a, b) => {
        return b.count - a.count;
    });
    console.info(results);
};

/******************************************************************************/

// Dump the internal state of the filtering engine to the console.
// Useful to make development decisions and investigate issues.

StaticNetFilteringEngine.prototype.dump = function() {
    const thConstants = new Map([
        [ NO_TOKEN_HASH, 'NO_TOKEN_HASH' ],
        [ DOT_TOKEN_HASH, 'DOT_TOKEN_HASH' ],
        [ ANY_TOKEN_HASH, 'ANY_TOKEN_HASH' ],
        [ ANY_HTTPS_TOKEN_HASH, 'ANY_HTTPS_TOKEN_HASH' ],
        [ ANY_HTTP_TOKEN_HASH, 'ANY_HTTP_TOKEN_HASH' ],
        [ EMPTY_TOKEN_HASH, 'EMPTY_TOKEN_HASH' ],
    ]);

    const out = [];

    const toOutput = (depth, line) => {
        out.push(`${' '.repeat(depth*2)}${line}`);
    };

    const dumpUnit = (idata, depth = 0) => {
        const fc = filterGetClass(idata);
        fcCounts.set(fc.name, (fcCounts.get(fc.name) || 0) + 1);
        const info = filterDumpInfo(idata) || '';
        toOutput(depth, info !== '' ? `${fc.name}: ${info}` : fc.name);
        switch ( fc ) {
        case FilterBucket:
        case FilterCompositeAll:
        case FilterDomainHitAny: {
            fc.forEach(idata, i => {
                dumpUnit(i, depth+1);
            });
            break;
        }
        case FilterBucketIfOriginHits: {
            dumpUnit(filterData[idata+2], depth+1);
            dumpUnit(filterData[idata+1], depth+1);
            break;
        }
        case FilterBucketIfRegexHits: {
            dumpUnit(filterData[idata+1], depth+1);
            break;
        }
        case FilterPlainTrie: {
            for ( const details of bidiTrie.trieIterator(filterData[idata+1]) ) {
                toOutput(depth+1, details.pattern);
                let ix = details.iextra;
                if ( ix === 1 ) { continue; }
                for (;;) {
                    if ( ix === 0 ) { break; }
                    dumpUnit(filterData[ix+0], depth+2);
                    ix = filterData[ix+1];
                }
            }
            break;
        }
        default:
            break;
        }
    };

    const fcCounts = new Map();
    const thCounts = new Set();

    const realms = new Map([
        [ BLOCK_REALM, 'block' ],
        [ BLOCKIMPORTANT_REALM, 'block-important' ],
        [ ALLOW_REALM, 'unblock' ],
        [ REDIRECT_REALM, 'redirect' ],
        [ REMOVEPARAM_REALM, 'removeparam' ],
        [ CSP_REALM, 'csp' ],
        [ PERMISSIONS_REALM, 'permissions' ],
        [ URLTRANSFORM_REALM, 'uritransform' ],
        [ REPLACE_REALM, 'replace' ],
        [ URLSKIP_REALM, 'urlskip' ],
    ]);
    const partyness = new Map([
        [ ANYPARTY_REALM, 'any-party' ],
        [ FIRSTPARTY_REALM, '1st-party' ],
        [ THIRDPARTY_REALM, '3rd-party' ],
    ]);
    for ( const [ realmBits, realmName ] of realms ) {
        toOutput(1, `+ realm: ${realmName}`);
        for ( const [ partyBits, partyName ] of partyness ) {
            toOutput(2, `+ party: ${partyName}`);
            const processedTypeBits = new Set();
            for ( const typeName in typeNameToTypeValue ) {
                const typeBits = typeNameToTypeValue[typeName];
                if ( processedTypeBits.has(typeBits) ) { continue; }
                processedTypeBits.add(typeBits);
                const bits = realmBits | partyBits | typeBits;
                const bucket = this.bitsToBucket.get(bits);
                if ( bucket === undefined ) { continue; }
                const thCount = bucket.size;
                toOutput(3, `+ type: ${typeName} (${thCount})`);
                for ( const [ th, iunit ] of bucket) {
                    thCounts.add(th);
                    const ths = thConstants.has(th)
                        ? thConstants.get(th)
                        : `0x${th.toString(16)}`;
                    toOutput(4, `+ th: ${ths}`);
                    dumpUnit(iunit, 5);
                }
            }
        }
    }

    const knownTokens =
        urlTokenizer.knownTokens
                    .reduce((a, b) => b !== 0 ? a+1 : a, 0);

    out.unshift([
        'Static Network Filtering Engine internals:',
        `  Distinct token hashes: ${thCounts.size.toLocaleString('en')}`,
        `  Known-token sieve (Uint8Array): ${knownTokens.toLocaleString('en')} out of 65,536`,
        `  Filter data (Int32Array): ${filterDataWritePtr.toLocaleString('en')}`,
        `  Filter refs (JS array): ${filterRefsWritePtr.toLocaleString('en')}`,
        '  Origin trie container:',
        origHNTrieContainer.dumpInfo().split('\n').map(a => `    ${a}`).join('\n'),
        '  Request trie container:',
        destHNTrieContainer.dumpInfo().split('\n').map(a => `    ${a}`).join('\n'),
        '  Pattern trie container:',
        bidiTrie.dumpInfo().split('\n').map(a => `    ${a}`).join('\n'),
        '+ Filter class stats:',
        Array.from(fcCounts)
             .sort((a, b) => b[1] - a[1])
             .map(a => `    ${a[0]}: ${a[1].toLocaleString('en')}`)
             .join('\n'),
        '+ Filter tree:',
    ].join('\n'));
    return out.join('\n');
};

/******************************************************************************/

const staticNetFilteringEngine = new StaticNetFilteringEngine();

export default staticNetFilteringEngine;

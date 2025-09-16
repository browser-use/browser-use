/*******************************************************************************

    publicsuffixlist.js - an efficient javascript implementation to deal with
    Mozilla Foundation's Public Suffix List <http://publicsuffix.org/list/>

    Copyright (C) 2013-present Raymond Hill

    License: pick the one which suits you:
      GPL v3 see <https://www.gnu.org/licenses/gpl.html>
      APL v2 see <http://www.apache.org/licenses/LICENSE-2.0>

*/

/*! Home: https://github.com/gorhill/publicsuffixlist.js -- GPLv3 APLv2 */

'use strict';

/*******************************************************************************

    Reference:
    https://publicsuffix.org/list/

    Excerpt:

    > Algorithm
    > 
    > 1. Match domain against all rules and take note of the matching ones.
    > 2. If no rules match, the prevailing rule is "*".
    > 3. If more than one rule matches, the prevailing rule is the one which
         is an exception rule.
    > 4. If there is no matching exception rule, the prevailing rule is the
         one with the most labels.
    > 5. If the prevailing rule is a exception rule, modify it by removing
         the leftmost label.
    > 6. The public suffix is the set of labels from the domain which match
         the labels of the prevailing rule, using the matching algorithm above.
    > 7. The registered or registrable domain is the public suffix plus one
         additional label.

*/

/******************************************************************************/

export default (function() {
// >>>>>>>> start of anonymous namespace

/*******************************************************************************

    Tree encoding in array buffer:
    
     Node:
     +  u8: length of char data
     +  u8: flags => bit 0: is_publicsuffix, bit 1: is_exception
     + u16: length of array of children
     + u32: char data or offset to char data
     + u32: offset to array of children
     = 12 bytes

    More bits in flags could be used; for example:
    - to distinguish private suffixes

*/

                                    // i32 /  i8
const HOSTNAME_SLOT         = 0;    // jshint ignore:line
const LABEL_INDICES_SLOT    = 256;  //  -- / 256 (256/2 => 128 labels max)
const RULES_PTR_SLOT        = 100;  // 100 / 400 (400-256=144 => 144>128)
const SUFFIX_NOT_FOUND_SLOT = 399;  //  -- / 399 (safe, see above)
const CHARDATA_PTR_SLOT     = 101;  // 101 / 404
const EMPTY_STRING          = '';
const SELFIE_MAGIC          = 3;

let wasmMemory;
let pslBuffer32;
let pslBuffer8;
let pslByteLength = 0;
let hostnameArg = EMPTY_STRING;

/******************************************************************************/

const fireChangedEvent = function() {
    if ( typeof window !== 'object' ) { return; }
    if ( window instanceof Object === false ) { return; }
    if ( window.dispatchEvent instanceof Function === false ) { return; }
    if ( window.CustomEvent instanceof Function === false ) { return; }
    window.dispatchEvent(new CustomEvent('publicSuffixListChanged'));
};

/******************************************************************************/

const allocateBuffers = function(byteLength) {
    pslByteLength = byteLength + 3 & ~3;
    if (
        pslBuffer32 !== undefined &&
        pslBuffer32.byteLength >= pslByteLength
    ) {
        return;
    }
    if ( wasmMemory !== undefined ) {
        const newPageCount = pslByteLength + 0xFFFF >>> 16;
        const curPageCount = wasmMemory.buffer.byteLength >>> 16;
        const delta = newPageCount - curPageCount;
        if ( delta > 0 ) {
            wasmMemory.grow(delta);
            pslBuffer32 = new Uint32Array(wasmMemory.buffer);
            pslBuffer8 = new Uint8Array(wasmMemory.buffer);
        }
    } else {
        pslBuffer8 = new Uint8Array(pslByteLength);
        pslBuffer32 = new Uint32Array(pslBuffer8.buffer);
    }
    hostnameArg = EMPTY_STRING;
    pslBuffer8[LABEL_INDICES_SLOT] = 0;
};

/******************************************************************************/

// Parse and set a UTF-8 text-based suffix list. Format is same as found at:
// http://publicsuffix.org/list/
//
// `toAscii` is a converter from unicode to punycode. Required since the
// Public Suffix List contains unicode characters.
// Suggestion: use <https://github.com/bestiejs/punycode.js>

const parse = function(text, toAscii) {
    // Use short property names for better minifying results
    const rootRule = {
        l: EMPTY_STRING,    // l => label
        f: 0,               // f => flags
        c: undefined        // c => children
    };

    // Tree building
    {
        const compareLabels = function(a, b) {
            let n = a.length;
            let d = n - b.length;
            if ( d !== 0 ) { return d; }
            for ( let i = 0; i < n; i++ ) {
                d = a.charCodeAt(i) - b.charCodeAt(i);
                if ( d !== 0 ) { return d; }
            }
            return 0;
        };

        const addToTree = function(rule, exception) {
            let node = rootRule;
            let end = rule.length;
            while ( end > 0 ) {
                const beg = rule.lastIndexOf('.', end - 1);
                const label = rule.slice(beg + 1, end);
                end = beg;

                if ( Array.isArray(node.c) === false ) {
                    const child = { l: label, f: 0, c: undefined };
                    node.c = [ child ];
                    node = child;
                    continue;
                }

                let left = 0;
                let right = node.c.length;
                while ( left < right ) {
                    const i = left + right >>> 1;
                    const d = compareLabels(label, node.c[i].l);
                    if ( d < 0 ) {
                        right = i;
                        if ( right === left ) {
                            const child = {
                                l: label,
                                f: 0,
                                c: undefined
                            };
                            node.c.splice(left, 0, child);
                            node = child;
                            break;
                        }
                        continue;
                    }
                    if ( d > 0 ) {
                        left = i + 1;
                        if ( left === right ) {
                            const child = {
                                l: label,
                                f: 0,
                                c: undefined
                            };
                            node.c.splice(right, 0, child);
                            node = child;
                            break;
                        }
                        continue;
                    }
                    /* d === 0 */
                    node = node.c[i];
                    break;
                }
            }
            node.f |= 0b01;
            if ( exception ) {
                node.f |= 0b10;
            }
        };

        // 2. If no rules match, the prevailing rule is "*".
        addToTree('*', false);

        const mustPunycode = /[^a-z0-9.-]/;
        const textEnd = text.length;
        let lineBeg = 0;

        while ( lineBeg < textEnd ) {
            let lineEnd = text.indexOf('\n', lineBeg);
            if ( lineEnd === -1 ) {
                lineEnd = text.indexOf('\r', lineBeg);
                if ( lineEnd === -1 ) {
                    lineEnd = textEnd;
                }
            }
            let line = text.slice(lineBeg, lineEnd).trim();
            lineBeg = lineEnd + 1;

            // Ignore comments
            const pos = line.indexOf('//');
            if ( pos !== -1 ) {
                line = line.slice(0, pos);
            }

            // Ignore surrounding whitespaces
            line = line.trim();
            if ( line.length === 0 ) { continue; }

            const exception = line.charCodeAt(0) === 0x21 /* '!' */;
            if ( exception ) {
                line = line.slice(1);
            }

            if ( mustPunycode.test(line) ) {
                line = toAscii(line.toLowerCase());
            }

            addToTree(line, exception);
        }
    }

    {
        const labelToOffsetMap = new Map();
        const treeData = [];
        const charData = [];

        const allocate = function(n) {
            const ibuf = treeData.length;
            for ( let i = 0; i < n; i++ ) {
                treeData.push(0);
            }
            return ibuf;
        };

        const storeNode = function(ibuf, node) {
            const nChars = node.l.length;
            const nChildren = node.c !== undefined
                ? node.c.length
                : 0;
            treeData[ibuf+0] = nChildren << 16 | node.f << 8 | nChars;
            // char data
            if ( nChars <= 4 ) {
                let v = 0;
                if ( nChars > 0 ) {
                    v |= node.l.charCodeAt(0);
                    if ( nChars > 1 ) {
                        v |= node.l.charCodeAt(1) << 8;
                        if ( nChars > 2 ) {
                            v |= node.l.charCodeAt(2) << 16;
                            if ( nChars > 3 ) {
                                v |= node.l.charCodeAt(3) << 24;
                            }
                        }
                    }
                }
                treeData[ibuf+1] = v;
            } else {
                let offset = labelToOffsetMap.get(node.l);
                if ( offset === undefined ) {
                    offset = charData.length;
                    for ( let i = 0; i < nChars; i++ ) {
                        charData.push(node.l.charCodeAt(i));
                    }
                    labelToOffsetMap.set(node.l, offset);
                }
                treeData[ibuf+1] = offset;
            }
            // child nodes
            if ( Array.isArray(node.c) === false ) {
                treeData[ibuf+2] = 0;
                return;
            }
            
            const iarray = allocate(nChildren * 3);
            treeData[ibuf+2] = iarray;
            for ( let i = 0; i < nChildren; i++ ) {
                storeNode(iarray + i * 3, node.c[i]);
            }
        };

        // First 512 bytes are reserved for internal use
        allocate(512 >> 2);

        const iRootRule = allocate(3);
        storeNode(iRootRule, rootRule);
        treeData[RULES_PTR_SLOT] = iRootRule;

        const iCharData = treeData.length << 2;
        treeData[CHARDATA_PTR_SLOT] = iCharData;

        const byteLength = (treeData.length << 2) + (charData.length + 3 & ~3);
        allocateBuffers(byteLength);
        pslBuffer32.set(treeData);
        pslBuffer8.set(charData, treeData.length << 2);
    }

    fireChangedEvent();
};

/******************************************************************************/

const setHostnameArg = function(hostname) {
    const buf = pslBuffer8;
    if ( hostname === hostnameArg ) { return buf[LABEL_INDICES_SLOT]; }
    if ( hostname === null || hostname.length === 0 ) {
        hostnameArg = EMPTY_STRING;
        return (buf[LABEL_INDICES_SLOT] = 0);
    }
    hostname = hostname.toLowerCase();
    hostnameArg = hostname;
    let n = hostname.length;
    if ( n > 255 ) { n = 255; }
    buf[LABEL_INDICES_SLOT] = n;
    let i = n;
    let j = LABEL_INDICES_SLOT + 1;
    while ( i-- ) {
        const c = hostname.charCodeAt(i);
        if ( c === 0x2E /* '.' */ ) {
            buf[j+0] = i + 1;
            buf[j+1] = i;
            j += 2;
        }
        buf[i] = c;
    }
    buf[j] = 0;
    return n;
};

/******************************************************************************/

// Returns an offset to the start of the public suffix.
//
// WASM-able, because no information outside the buffer content is required.

const getPublicSuffixPosJS = function() {
    const buf8 = pslBuffer8;
    const buf32 = pslBuffer32;
    const iCharData = buf32[CHARDATA_PTR_SLOT];

    let iNode = pslBuffer32[RULES_PTR_SLOT];
    let cursorPos = -1;
    let iLabel = LABEL_INDICES_SLOT;

    // Label-lookup loop
    for (;;) {
        // Extract label indices
        const labelBeg = buf8[iLabel+1];
        const labelLen = buf8[iLabel+0] - labelBeg;
        // Match-lookup loop: binary search
        let r = buf32[iNode+0] >>> 16;
        if ( r === 0 ) { break; }
        const iCandidates = buf32[iNode+2];
        let l = 0;
        let iFound = 0;
        while ( l < r ) {
            const iCandidate = l + r >>> 1;
            const iCandidateNode = iCandidates + iCandidate + (iCandidate << 1);
            const candidateLen = buf32[iCandidateNode+0] & 0x000000FF;
            let d = labelLen - candidateLen;
            if ( d === 0 ) {
                const iCandidateChar = candidateLen <= 4
                    ? iCandidateNode + 1 << 2
                    : iCharData + buf32[iCandidateNode+1];
                for ( let i = 0; i < labelLen; i++ ) {
                    d = buf8[labelBeg+i] - buf8[iCandidateChar+i];
                    if ( d !== 0 ) { break; }
                }
            }
            if ( d < 0 ) {
                r = iCandidate;
            } else if ( d > 0 ) {
                l = iCandidate + 1;
            } else /* if ( d === 0 ) */ {
                iFound = iCandidateNode;
                break;
            }
        }
        // 2. If no rules match, the prevailing rule is "*".
        if ( iFound === 0 ) {
            if ( buf32[iCandidates + 1] !== 0x2A /* '*' */ ) { break; }
            buf8[SUFFIX_NOT_FOUND_SLOT] = 1;
            iFound = iCandidates;
        }
        iNode = iFound;
        // 5. If the prevailing rule is a exception rule, modify it by
        //    removing the leftmost label.
        if ( (buf32[iNode+0] & 0x00000200) !== 0 ) {
            if ( iLabel > LABEL_INDICES_SLOT ) {
                return iLabel - 2;
            }
            break;
        }
        if ( (buf32[iNode+0] & 0x00000100) !== 0 ) {
            cursorPos = iLabel;
        }
        if ( labelBeg === 0 ) { break; }
        iLabel += 2;
    }

    return cursorPos;
};

let getPublicSuffixPosWASM;
let getPublicSuffixPos = getPublicSuffixPosJS;

/******************************************************************************/

const getPublicSuffix = function(hostname) {
    if ( pslBuffer32 === undefined ) { return EMPTY_STRING; }

    const hostnameLen = setHostnameArg(hostname);
    const buf8 = pslBuffer8;
    if ( hostnameLen === 0 || buf8[0] === 0x2E /* '.' */ ) {
        return EMPTY_STRING;
    }

    const cursorPos = getPublicSuffixPos();
    if ( cursorPos === -1 ) {
        return EMPTY_STRING;
    }

    const beg = buf8[cursorPos + 1];
    return beg === 0 ? hostnameArg : hostnameArg.slice(beg);
};

/******************************************************************************/

const getDomain = function(hostname) {
    if ( pslBuffer32 === undefined ) { return EMPTY_STRING; }

    const hostnameLen = setHostnameArg(hostname);
    const buf8 = pslBuffer8;
    if ( hostnameLen === 0 || buf8[0] === 0x2E /* '.' */ ) {
        return EMPTY_STRING;
    }

    const cursorPos = getPublicSuffixPos();
    if ( cursorPos === -1 || buf8[cursorPos + 1] === 0 ) {
        return EMPTY_STRING;
    }

    // 7. The registered or registrable domain is the public suffix plus one
    //    additional label.
    const beg = buf8[cursorPos + 3];
    return beg === 0 ? hostnameArg : hostnameArg.slice(beg);
};

/******************************************************************************/

const suffixInPSL = function(hostname) {
    if ( pslBuffer32 === undefined ) { return false; }

    const hostnameLen = setHostnameArg(hostname);
    const buf8 = pslBuffer8;
    if ( hostnameLen === 0 || buf8[0] === 0x2E /* '.' */ ) {
        return false;
    }

    buf8[SUFFIX_NOT_FOUND_SLOT] = 0;
    const cursorPos = getPublicSuffixPos();
    return cursorPos !== -1 &&
           buf8[cursorPos + 1] === 0 &&
           buf8[SUFFIX_NOT_FOUND_SLOT] !== 1;
};

/******************************************************************************/

const toSelfie = function(encoder) {
    if ( pslBuffer8 === undefined ) { return ''; }
    if ( encoder instanceof Object ) {
        const bufferStr = encoder.encode(pslBuffer8.buffer, pslByteLength);
        return `${SELFIE_MAGIC}\t${bufferStr}`;
    }
    return {
        magic: SELFIE_MAGIC,
        buf32: pslBuffer32.subarray(0, pslByteLength >> 2),
    };
};

const fromSelfie = function(selfie, decoder) {
    let byteLength = 0;
    if (
        typeof selfie === 'string' &&
        selfie.length !== 0 &&
        decoder instanceof Object
    ) {
        const pos = selfie.indexOf('\t');
        if ( pos === -1 || selfie.slice(0, pos) !== `${SELFIE_MAGIC}` ) {
            return false;
        }
        const bufferStr = selfie.slice(pos + 1);
        byteLength = decoder.decodeSize(bufferStr);
        if ( byteLength === 0 ) { return false; }
        allocateBuffers(byteLength);
        decoder.decode(bufferStr, pslBuffer8.buffer);
    } else if (
        selfie instanceof Object &&
        selfie.magic === SELFIE_MAGIC &&
        selfie.buf32 instanceof Uint32Array
    ) {
        byteLength = selfie.buf32.length << 2;
        allocateBuffers(byteLength);
        pslBuffer32.set(selfie.buf32);
    } else {
        return false;
    }

    // Important!
    hostnameArg = EMPTY_STRING;
    pslBuffer8[LABEL_INDICES_SLOT] = 0;

    fireChangedEvent();

    return true;
};

/******************************************************************************/

// The WASM module is entirely optional, the JS implementation will be
// used should the WASM module be unavailable for whatever reason.

const enableWASM = (( ) => {
    let wasmPromise;

    const getWasmInstance = async function(wasmModuleFetcher, path) {
        if ( typeof WebAssembly !== 'object' ) { return false; }
        // The wasm code will work only if CPU is natively little-endian,
        // as we use native uint32 array in our js code.
        const uint32s = new Uint32Array(1);
        const uint8s = new Uint8Array(uint32s.buffer);
        uint32s[0] = 1;
        if ( uint8s[0] !== 1 ) { return false; }

        try {
            const module = await wasmModuleFetcher(`${path}publicsuffixlist`);
            if (  module instanceof WebAssembly.Module === false ) {
                return false;
            }
            const pageCount = pslBuffer8 !== undefined
                ? pslBuffer8.byteLength + 0xFFFF >>> 16
                : 1;
            const memory = new WebAssembly.Memory({ initial: pageCount });
            const instance = await WebAssembly.instantiate(module, {
                imports: { memory }
            });
            if (  instance instanceof WebAssembly.Instance === false ) {
                return false;
            }
            const curPageCount = memory.buffer.byteLength >>> 16;
            const newPageCount = pslBuffer8 !== undefined
                ? pslBuffer8.byteLength + 0xFFFF >>> 16
                : 0;
            if ( newPageCount > curPageCount ) {
                memory.grow(newPageCount - curPageCount);
            }
            if ( pslBuffer32 !== undefined ) {
                const buf8 = new Uint8Array(memory.buffer);
                const buf32 = new Uint32Array(memory.buffer);
                buf32.set(pslBuffer32);
                pslBuffer8 = buf8;
                pslBuffer32 = buf32;
            }
            wasmMemory = memory;
            getPublicSuffixPosWASM = instance.exports.getPublicSuffixPos;
            getPublicSuffixPos = getPublicSuffixPosWASM;
            return true;
        } catch(reason) {
            console.info(reason);
        }
        return false;
    };

    return async function(wasmModuleFetcher, path) {
        if ( getPublicSuffixPosWASM instanceof Function ) { return true; }
        if ( wasmPromise instanceof Promise === false ) {
            wasmPromise = getWasmInstance(wasmModuleFetcher, path);
        }
        return wasmPromise;
    };
})();

const disableWASM = function() {
    if ( getPublicSuffixPosWASM instanceof Function ) {
        getPublicSuffixPos = getPublicSuffixPosJS;
        getPublicSuffixPosWASM = undefined;
    }
    if ( wasmMemory === undefined ) { return; }
    if ( pslBuffer32 !== undefined ) {
        const buf8 = new Uint8Array(pslByteLength);
        const buf32 = new Uint32Array(buf8.buffer);
        buf32.set(pslBuffer32);
        pslBuffer8 = buf8;
        pslBuffer32 = buf32;
    }
    wasmMemory = undefined;
};

/******************************************************************************/

return ({
    version: '2.0',
    parse,
    getDomain,
    suffixInPSL,
    getPublicSuffix,
    toSelfie, fromSelfie,
    disableWASM, enableWASM,
});

/******************************************************************************/

// <<<<<<<< end of anonymous namespace
})();

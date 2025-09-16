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

/*******************************************************************************

  The original prototype was to develop an idea I had about using jump indices
  in a TypedArray for quickly matching hostnames (or more generally strings)[1].
  Once I had a working, un-optimized prototype, I realized I had ended up
  with something formally named a "trie": <https://en.wikipedia.org/wiki/Trie>,
  hence the name. I have no idea whether the implementation here or one
  resembling it has been done elsewhere.

  "HN" in HNTrieContainer stands for "HostName", because the trie is
  specialized to deal with matching hostnames -- which is a bit more
  complicated than matching plain strings.

  For example, `www.abc.com` is deemed matching `abc.com`, because the former
  is a subdomain of the latter. The opposite is of course not true.

  The resulting read-only tries created as a result of using HNTrieContainer
  are simply just typed arrays filled with integers. The matching algorithm is
  just a matter of reading/comparing these integers, and further using them as
  indices in the array as a way to move around in the trie.

  [1] To solve <https://github.com/gorhill/uBlock/issues/3193>

  Since this trie is specialized for matching hostnames, the stored
  strings are reversed internally, because of hostname comparison logic:

  Correct matching:
    index      0123456
               abc.com
                     |
           www.abc.com
    index  01234567890

  Incorrect matching (typically used for plain strings):
    index  0123456
           abc.com
           |
           www.abc.com
    index  01234567890

  ------------------------------------------------------------------------------

  1st iteration:
    - https://github.com/gorhill/uBlock/blob/ff58107dac3a32607f8113e39ed5015584506813/src/js/hntrie.js
    - Suitable for small to medium set of hostnames
    - One buffer per trie

  2nd iteration: goal was to make matches() method wasm-able
    - https://github.com/gorhill/uBlock/blob/c3b0fd31f64bd7ffecdd282fb1208fe07aac3eb0/src/js/hntrie.js
    - Suitable for small to medium set of hostnames
    - Distinct tries all share same buffer:
      - Reduced memory footprint
        - https://stackoverflow.com/questions/45803829/memory-overhead-of-typed-arrays-vs-strings/45808835#45808835
      - Reusing needle character lookups for all tries
        - This significantly reduce the number of String.charCodeAt() calls
    - Slightly improved creation time

  This is the 3rd iteration: goal was to make add() method wasm-able and
  further improve memory/CPU efficiency.

  This 3rd iteration has the following new traits:
    - Suitable for small to large set of hostnames
    - Support multiple trie containers (instanciable)
    - Designed to hold large number of hostnames
    - Hostnames can be added at any time (instead of all at once)
      - This means pre-sorting is no longer a requirement
    - The trie is always compact
      - There is no longer a need for a `vacuum` method
      - This makes the add() method wasm-able
    - It can return the exact hostname which caused the match
    - serializable/unserializable available for fast loading
    - Distinct trie reference support the iteration protocol, thus allowing
      to extract all the hostnames in the trie

  Its primary purpose is to replace the use of Set() as a mean to hold
  large number of hostnames (ex. FilterHostnameDict in static filtering
  engine).

  A HNTrieContainer is mostly a large buffer in which distinct but related
  tries are stored. The memory layout of the buffer is as follow:

    0-254: needle being processed
      255: length of needle
  256-259: offset to start of trie data section (=> trie0)
  260-263: offset to end of trie data section (=> trie1)
  264-267: offset to start of character data section  (=> char0)
  268-271: offset to end of character data section (=> char1)
      272: start of trie data section

*/

const PAGE_SIZE   = 65536;
//                                             i32 /  i8
const TRIE0_SLOT  = 256 >>> 2;              //  64 / 256
const TRIE1_SLOT  = TRIE0_SLOT + 1;         //  65 / 260
const CHAR0_SLOT  = TRIE0_SLOT + 2;         //  66 / 264
const CHAR1_SLOT  = TRIE0_SLOT + 3;         //  67 / 268
const TRIE0_START = TRIE0_SLOT + 4 << 2;    //       272

const roundToPageSize = v => (v + PAGE_SIZE-1) & ~(PAGE_SIZE-1);

// http://www.cse.yorku.ca/~oz/hash.html#djb2
const i32Checksum = (buf32) => {
    const n = buf32.length;
    let hash = 177573 ^ n;
    for ( let i = 0; i < n; i++ ) {
        hash = (hash << 5) + hash ^ buf32[i];
    }
    return hash;
};

class HNTrieContainer {

    constructor() {
        const len = PAGE_SIZE * 2;
        this.buf = new Uint8Array(len);
        this.buf32 = new Uint32Array(this.buf.buffer);
        this.needle = '';
        this.buf32[TRIE0_SLOT] = TRIE0_START;
        this.buf32[TRIE1_SLOT] = this.buf32[TRIE0_SLOT];
        this.buf32[CHAR0_SLOT] = len >>> 1;
        this.buf32[CHAR1_SLOT] = this.buf32[CHAR0_SLOT];
        this.wasmMemory = null;

        this.lastStored = '';
        this.lastStoredLen = this.lastStoredIndex = 0;
    }

    //--------------------------------------------------------------------------
    // Public methods
    //--------------------------------------------------------------------------

    reset(details) {
        if (
            details instanceof Object &&
            typeof details.byteLength === 'number' &&
            typeof details.char0 === 'number'
        ) {
            if ( details.byteLength > this.buf.byteLength ) {
                this.reallocateBuf(details.byteLength);
            }
            this.buf32[CHAR0_SLOT] = details.char0;
        }
        this.buf32[TRIE1_SLOT] = this.buf32[TRIE0_SLOT];
        this.buf32[CHAR1_SLOT] = this.buf32[CHAR0_SLOT];

        this.lastStored = '';
        this.lastStoredLen = this.lastStoredIndex = 0;
    }

    setNeedle(needle) {
        if ( needle !== this.needle ) {
            const buf = this.buf;
            let i = needle.length;
            if ( i > 255 ) { i = 255; }
            buf[255] = i;
            while ( i-- ) {
                buf[i] = needle.charCodeAt(i);
            }
            this.needle = needle;
        }
        return this;
    }

    matchesJS(iroot) {
        const buf32 = this.buf32;
        const buf8 = this.buf;
        const char0 = buf32[CHAR0_SLOT];
        let ineedle = buf8[255];
        let icell = buf32[iroot+0];
        if ( icell === 0 ) { return -1; }
        let c = 0, v = 0, i0 = 0, n = 0;
        for (;;) {
            if ( ineedle === 0 ) { return -1; }
            ineedle -= 1;
            c = buf8[ineedle];
            // find first segment with a first-character match
            for (;;) {
                v = buf32[icell+2];
                i0 = char0 + (v >>> 8);
                if ( buf8[i0] === c ) { break; }
                icell = buf32[icell+0];
                if ( icell === 0 ) { return -1; }
            }
            // all characters in segment must match
            n = v & 0x7F;
            if ( n > 1 ) {
                n -= 1;
                if ( n > ineedle ) { return -1; }
                i0 += 1;
                const i1 = i0 + n;
                do {
                    ineedle -= 1;
                    if ( buf8[i0] !== buf8[ineedle] ) { return -1; }
                    i0 += 1;
                } while ( i0 < i1 );
            }
            // boundary at end of segment?
            if ( (v & 0x80) !== 0 ) {
                if ( ineedle === 0 || buf8[ineedle-1] === 0x2E /* '.' */ ) {
                    return ineedle;
                }
            }
            // next segment
            icell = buf32[icell+1];
            if ( icell === 0 ) { break; }
        }
        return -1;
    }

    createTrie() {
        // grow buffer if needed
        if ( (this.buf32[CHAR0_SLOT] - this.buf32[TRIE1_SLOT]) < 12 ) {
            this.growBuf(12, 0);
        }
        const iroot = this.buf32[TRIE1_SLOT] >>> 2;
        this.buf32[TRIE1_SLOT] += 12;
        this.buf32[iroot+0] = 0;
        this.buf32[iroot+1] = 0;
        this.buf32[iroot+2] = 0;
        return iroot;
    }

    createTrieFromIterable(hostnames) {
        const itrie = this.createTrie();
        for ( const hn of hostnames ) {
            if ( hn === '' ) { continue; }
            this.setNeedle(hn).add(itrie);
        }
        return itrie;
    }

    createTrieFromStoredDomainOpt(i, n) {
        const itrie = this.createTrie();
        const jend = i + n;
        let j = i, offset = 0, k = 0, c = 0;
        while ( j !== jend ) {
            offset = this.buf32[CHAR0_SLOT]; // Important
            k = 0;
            for (;;) {
                if ( j === jend ) { break; }
                c = this.buf[offset+j];
                j += 1;
                if ( c === 0x7C /* '|' */ ) { break; }
                if ( k === 255 ) { continue; }
                this.buf[k] = c;
                k += 1;
            }
            if ( k !== 0 ) {
                this.buf[255] = k;
                this.add(itrie);
            }
        }
        this.needle = '';   // Important
        this.buf[255] = 0;  // Important
        return itrie;
    }

    dumpTrie(iroot) {
        let hostnames = Array.from(this.trieIterator(iroot));
        if ( String.prototype.padStart instanceof Function ) {
            const maxlen = Math.min(
                hostnames.reduce((maxlen, hn) => Math.max(maxlen, hn.length), 0),
                64
            );
            hostnames = hostnames.map(hn => hn.padStart(maxlen));
        }
        for ( const hn of hostnames ) {
            console.log(hn);
        }
    }

    trieIterator(iroot) {
        return {
            value: undefined,
            done: false,
            next() {
                if ( this.icell === 0 ) {
                    if ( this.forks.length === 0 ) {
                        this.value = undefined;
                        this.done = true;
                        return this;
                    }
                    this.charPtr = this.forks.pop();
                    this.icell = this.forks.pop();
                }
                for (;;) {
                    const idown = this.container.buf32[this.icell+0];
                    if ( idown !== 0 ) {
                        this.forks.push(idown, this.charPtr);
                    }
                    const v = this.container.buf32[this.icell+2];
                    let i0 = this.container.buf32[CHAR0_SLOT] + (v >>> 8);
                    const i1 = i0 + (v & 0x7F);
                    while ( i0 < i1 ) {
                        this.charPtr -= 1;
                        this.charBuf[this.charPtr] = this.container.buf[i0];
                        i0 += 1;
                    }
                    this.icell = this.container.buf32[this.icell+1];
                    if ( (v & 0x80) !== 0 ) {
                        return this.toHostname();
                    }
                }
            },
            toHostname() {
                this.value = this.textDecoder.decode(
                    new Uint8Array(this.charBuf.buffer, this.charPtr)
                );
                return this;
            },
            container: this,
            icell: this.buf32[iroot],
            charBuf: new Uint8Array(256),
            charPtr: 256,
            forks: [],
            textDecoder: new TextDecoder(),
            [Symbol.iterator]() { return this; },
        };
    }

    // TODO:
    //   Rework code to add from a string already present in the character
    //   buffer, i.e. not having to go through setNeedle() when adding a new
    //   hostname to a trie. This will require much work though, and probably
    //   changing the order in which string segments are stored in the
    //   character buffer.
    addJS(iroot) {
        let lhnchar = this.buf[255];
        if ( lhnchar === 0 ) { return 0; }
        // grow buffer if needed
        if (
            (this.buf32[CHAR0_SLOT] - this.buf32[TRIE1_SLOT]) < 24 ||
            (this.buf.length - this.buf32[CHAR1_SLOT]) < 256
        ) {
            this.growBuf(24, 256);
        }
        let icell = this.buf32[iroot+0];
        // special case: first node in trie
        if ( icell === 0 ) {
            this.buf32[iroot+0] = this.addLeafCell(lhnchar);
            return 1;
        }
        //
        const char0 = this.buf32[CHAR0_SLOT];
        let isegchar, lsegchar, boundaryBit, inext;
        // find a matching cell: move down
        for (;;) {
            const v = this.buf32[icell+2];
            let isegchar0 = char0 + (v >>> 8);
            // if first character is no match, move to next descendant
            if ( this.buf[isegchar0] !== this.buf[lhnchar-1] ) {
                inext = this.buf32[icell+0];
                if ( inext === 0 ) {
                    this.buf32[icell+0] = this.addLeafCell(lhnchar);
                    return 1;
                }
                icell = inext;
                continue;
            }
            // 1st character was tested
            isegchar = 1;
            lhnchar -= 1;
            // find 1st mismatch in rest of segment
            lsegchar = v & 0x7F;
            if ( lsegchar !== 1 ) {
                for (;;) {
                    if ( isegchar === lsegchar ) { break; }
                    if ( lhnchar === 0 ) { break; }
                    if ( this.buf[isegchar0+isegchar] !== this.buf[lhnchar-1] ) { break; }
                    isegchar += 1;
                    lhnchar -= 1;
                }
            }
            boundaryBit = v & 0x80;
            // all segment characters matched
            if ( isegchar === lsegchar ) {
                // needle remainder: no
                if ( lhnchar === 0 ) {
                    // boundary: yes, already present
                    if ( boundaryBit !== 0 ) { return 0; }
                    // boundary: no, mark as boundary
                    this.buf32[icell+2] = v | 0x80;
                }
                // needle remainder: yes
                else {
                    // remainder is at label boundary? if yes, no need to add
                    // the rest since the shortest match is always reported
                    if ( boundaryBit !== 0 ) {
                        if ( this.buf[lhnchar-1] === 0x2E /* '.' */ ) { return -1; }
                    }
                    inext = this.buf32[icell+1];
                    if ( inext !== 0 ) {
                        icell = inext;
                        continue;
                    }
                    // add needle remainder
                    this.buf32[icell+1] = this.addLeafCell(lhnchar);
                }
            }
            // some segment characters matched
            else {
                // split current cell
                isegchar0 -= char0;
                this.buf32[icell+2] = isegchar0 << 8 | isegchar;
                inext = this.addCell(
                    0,
                    this.buf32[icell+1],
                    isegchar0 + isegchar << 8 | boundaryBit | lsegchar - isegchar
                );
                this.buf32[icell+1] = inext;
                // needle remainder: yes, need new cell for remaining characters
                if ( lhnchar !== 0 ) {
                    this.buf32[inext+0] = this.addLeafCell(lhnchar);
                }
                // needle remainder: no, need boundary cell
                else {
                    this.buf32[icell+2] |= 0x80;
                }
            }
            return 1;
        }
    }

    optimize() {
        this.shrinkBuf();
        return {
            byteLength: this.buf.byteLength,
            char0: this.buf32[CHAR0_SLOT],
        };
    }

    toSelfie() {
        const buf32 = this.buf32.subarray(0, this.buf32[CHAR1_SLOT] + 3 >>> 2);
        return { buf32, checksum: i32Checksum(buf32) };
    }

    fromSelfie(selfie) {
        if ( typeof selfie !== 'object' || selfie === null ) { return false; }
        if ( selfie.buf32 instanceof Uint32Array === false ) { return false; }
        if ( selfie.checksum !== i32Checksum(selfie.buf32) ) { return false; }
        this.needle = '';
        let byteLength = selfie.buf32.length << 2;
        if ( byteLength === 0 ) { return false; }
        byteLength = roundToPageSize(byteLength);
        if ( this.wasmMemory !== null ) {
            const pageCountBefore = this.buf.length >>> 16;
            const pageCountAfter = byteLength >>> 16;
            if ( pageCountAfter > pageCountBefore ) {
                this.wasmMemory.grow(pageCountAfter - pageCountBefore);
                this.buf = new Uint8Array(this.wasmMemory.buffer);
                this.buf32 = new Uint32Array(this.buf.buffer);
            }
            this.buf32.set(selfie.buf32);
        } else {
            this.buf32 = selfie.buf32;
            this.buf = new Uint8Array(this.buf32.buffer);
        }
        // https://github.com/uBlockOrigin/uBlock-issues/issues/2925
        this.buf[255] = 0;
        return true;
    }

    // The following *Hostname() methods can be used to store hostname strings
    // outside the trie. This is useful to store/match hostnames which are
    // not part of a collection, and yet still benefit from storing the strings
    // into a trie container's character buffer.
    // TODO: WASM version of matchesHostname()

    storeHostname(hn) {
        let n = hn.length;
        if ( n > 255 ) {
            hn = hn.slice(-255);
            n = 255;
        }
        if ( n === this.lastStoredLen && hn === this.lastStored ) {
            return this.lastStoredIndex;
        }
        this.lastStored = hn;
        this.lastStoredLen = n;
        if ( (this.buf.length - this.buf32[CHAR1_SLOT]) < n ) {
            this.growBuf(0, n);
        }
        const offset = this.buf32[CHAR1_SLOT];
        this.buf32[CHAR1_SLOT] = offset + n;
        const buf8 = this.buf;
        for ( let i = 0; i < n; i++ ) {
            buf8[offset+i] = hn.charCodeAt(i);
        }
        return (this.lastStoredIndex = offset - this.buf32[CHAR0_SLOT]);
    }

    extractHostname(i, n) {
        const textDecoder = new TextDecoder();
        const offset = this.buf32[CHAR0_SLOT] + i;
        return textDecoder.decode(this.buf.subarray(offset, offset + n));
    }

    storeDomainOpt(s) {
        let n = s.length;
        if ( n === this.lastStoredLen && s === this.lastStored ) {
            return this.lastStoredIndex;
        }
        this.lastStored = s;
        this.lastStoredLen = n;
        if ( (this.buf.length - this.buf32[CHAR1_SLOT]) < n ) {
            this.growBuf(0, n);
        }
        const offset = this.buf32[CHAR1_SLOT];
        this.buf32[CHAR1_SLOT] = offset + n;
        const buf8 = this.buf;
        for ( let i = 0; i < n; i++ ) {
            buf8[offset+i] = s.charCodeAt(i);
        }
        return (this.lastStoredIndex = offset - this.buf32[CHAR0_SLOT]);
    }

    extractDomainOpt(i, n) {
        const textDecoder = new TextDecoder();
        const offset = this.buf32[CHAR0_SLOT] + i;
        return textDecoder.decode(this.buf.subarray(offset, offset + n));
    }

    matchesHostname(hn, i, n) {
        this.setNeedle(hn);
        const buf8 = this.buf;
        const hr = buf8[255];
        if ( n > hr ) { return false; }
        const hl = hr - n;
        const nl = this.buf32[CHAR0_SLOT] + i;
        for ( let j = 0; j < n; j++ ) {
            if ( buf8[nl+j] !== buf8[hl+j] ) { return false; }
        }
        return n === hr || hn.charCodeAt(hl-1) === 0x2E /* '.' */;
    }

    async enableWASM(wasmModuleFetcher, path) {
        if ( typeof WebAssembly === 'undefined' ) { return false; }
        if ( this.wasmMemory instanceof WebAssembly.Memory ) { return true; }
        const module = await getWasmModule(wasmModuleFetcher, path);
        if ( module instanceof WebAssembly.Module === false ) { return false; }
        const memory = new WebAssembly.Memory({ initial: 2 });
        const instance = await WebAssembly.instantiate(module, {
            imports: {
                memory,
                growBuf: this.growBuf.bind(this, 24, 256)
            }
        });
        if ( instance instanceof WebAssembly.Instance === false ) { return false; }
        this.wasmMemory = memory;
        const curPageCount = memory.buffer.byteLength >>> 16;
        const newPageCount = roundToPageSize(this.buf.byteLength) >>> 16;
        if ( newPageCount > curPageCount ) {
            memory.grow(newPageCount - curPageCount);
        }
        const buf = new Uint8Array(memory.buffer);
        buf.set(this.buf);
        this.buf = buf;
        this.buf32 = new Uint32Array(this.buf.buffer);
        this.matches = this.matchesWASM = instance.exports.matches;
        this.add = this.addWASM = instance.exports.add;
        return true;
    }

    dumpInfo() {
        return [
            `Buffer size (Uint8Array): ${this.buf32[CHAR1_SLOT].toLocaleString('en')}`,
            `  Char segment size: ${(this.buf32[CHAR1_SLOT] - this.buf32[CHAR0_SLOT]).toLocaleString('en')}`,
            `WASM: ${this.wasmMemory === null ? 'disabled' : 'enabled'}`,
        ].join('\n');
    }

    //--------------------------------------------------------------------------
    // Private methods
    //--------------------------------------------------------------------------

    addCell(idown, iright, v) {
        let icell = this.buf32[TRIE1_SLOT];
        this.buf32[TRIE1_SLOT] = icell + 12;
        icell >>>= 2;
        this.buf32[icell+0] = idown;
        this.buf32[icell+1] = iright;
        this.buf32[icell+2] = v;
        return icell;
    }

    addLeafCell(lsegchar) {
        const r = this.buf32[TRIE1_SLOT] >>> 2;
        let i = r;
        while ( lsegchar > 127 ) {
            this.buf32[i+0] = 0;
            this.buf32[i+1] = i + 3;
            this.buf32[i+2] = this.addSegment(lsegchar, lsegchar - 127);
            lsegchar -= 127;
            i += 3;
        }
        this.buf32[i+0] = 0;
        this.buf32[i+1] = 0;
        this.buf32[i+2] = this.addSegment(lsegchar, 0) | 0x80;
        this.buf32[TRIE1_SLOT] = i + 3 << 2;
        return r;
    }

    addSegment(lsegchar, lsegend) {
        if ( lsegchar === 0 ) { return 0; }
        let char1 = this.buf32[CHAR1_SLOT];
        const isegchar = char1 - this.buf32[CHAR0_SLOT];
        let i = lsegchar;
        do {
            this.buf[char1++] = this.buf[--i];
        } while ( i !== lsegend );
        this.buf32[CHAR1_SLOT] = char1;
        return isegchar << 8 | lsegchar - lsegend;
    }

    growBuf(trieGrow, charGrow) {
        const char0 = Math.max(
            roundToPageSize(this.buf32[TRIE1_SLOT] + trieGrow),
            this.buf32[CHAR0_SLOT]
        );
        const char1 = char0 + this.buf32[CHAR1_SLOT] - this.buf32[CHAR0_SLOT];
        const bufLen = Math.max(
            roundToPageSize(char1 + charGrow),
            this.buf.length
        );
        this.resizeBuf(bufLen, char0);
    }

    shrinkBuf() {
        // Can't shrink WebAssembly.Memory
        if ( this.wasmMemory !== null ) { return; }
        const char0 = this.buf32[TRIE1_SLOT] + 24;
        const char1 = char0 + this.buf32[CHAR1_SLOT] - this.buf32[CHAR0_SLOT];
        const bufLen = char1 + 256;
        this.resizeBuf(bufLen, char0);
    }

    resizeBuf(bufLen, char0) {
        bufLen = roundToPageSize(bufLen);
        if ( bufLen === this.buf.length && char0 === this.buf32[CHAR0_SLOT] ) {
            return;
        }
        const charDataLen = this.buf32[CHAR1_SLOT] - this.buf32[CHAR0_SLOT];
        if ( this.wasmMemory !== null ) {
            const pageCount = (bufLen >>> 16) - (this.buf.byteLength >>> 16);
            if ( pageCount > 0 ) {
                this.wasmMemory.grow(pageCount);
                this.buf = new Uint8Array(this.wasmMemory.buffer);
                this.buf32 = new Uint32Array(this.wasmMemory.buffer);
            }
        } else if ( bufLen !== this.buf.length ) {
            const newBuf = new Uint8Array(bufLen);
            newBuf.set(
                new Uint8Array(
                    this.buf.buffer,
                    0,
                    this.buf32[TRIE1_SLOT]
                ),
                0
            );
            newBuf.set(
                new Uint8Array(
                    this.buf.buffer,
                    this.buf32[CHAR0_SLOT],
                    charDataLen
                ),
                char0
            );
            this.buf = newBuf;
            this.buf32 = new Uint32Array(this.buf.buffer);
            this.buf32[CHAR0_SLOT] = char0;
            this.buf32[CHAR1_SLOT] = char0 + charDataLen;
        }
        if ( char0 !== this.buf32[CHAR0_SLOT] ) {
            this.buf.set(
                new Uint8Array(
                    this.buf.buffer,
                    this.buf32[CHAR0_SLOT],
                    charDataLen
                ),
                char0
            );
            this.buf32[CHAR0_SLOT] = char0;
            this.buf32[CHAR1_SLOT] = char0 + charDataLen;
        }
    }

    reallocateBuf(newSize) {
        newSize = roundToPageSize(newSize);
        if ( newSize === this.buf.length ) { return; }
        if ( this.wasmMemory === null ) {
            const newBuf = new Uint8Array(newSize);
            newBuf.set(
                newBuf.length < this.buf.length
                    ? this.buf.subarray(0, newBuf.length)
                    : this.buf
            );
            this.buf = newBuf;
        } else {
            const growBy =
                ((newSize + 0xFFFF) >>> 16) - (this.buf.length >>> 16);
            if ( growBy <= 0 ) { return; }
            this.wasmMemory.grow(growBy);
            this.buf = new Uint8Array(this.wasmMemory.buffer);
        }
        this.buf32 = new Uint32Array(this.buf.buffer);
    }
}

HNTrieContainer.prototype.matches = HNTrieContainer.prototype.matchesJS;
HNTrieContainer.prototype.matchesWASM = null;

HNTrieContainer.prototype.add = HNTrieContainer.prototype.addJS;
HNTrieContainer.prototype.addWASM = null;

/******************************************************************************/

// Code below is to attempt to load a WASM module which implements:
//
// - HNTrieContainer.add()
// - HNTrieContainer.matches()
//
// The WASM module is entirely optional, the JS implementations will be
// used should the WASM module be unavailable for whatever reason.

const getWasmModule = (( ) => {
    let wasmModulePromise;

    return async function(wasmModuleFetcher, path) {
        if ( wasmModulePromise instanceof Promise ) {
            return wasmModulePromise;
        }

        // The wasm module will work only if CPU is natively little-endian,
        // as we use native uint32 array in our js code.
        const uint32s = new Uint32Array(1);
        const uint8s = new Uint8Array(uint32s.buffer);
        uint32s[0] = 1;
        if ( uint8s[0] !== 1 ) { return; }

        wasmModulePromise = wasmModuleFetcher(`${path}hntrie`).catch(reason => {
            console.info(reason);
        });

        return wasmModulePromise;
    };
})();

/******************************************************************************/

export default HNTrieContainer;

/*******************************************************************************

    lz4-block-codec-js.js
        A javascript wrapper around a pure javascript implementation of
        LZ4 block format codec.
    Copyright (C) 2018 Raymond Hill

    BSD-2-Clause License (http://www.opensource.org/licenses/bsd-license.php)

    Redistribution and use in source and binary forms, with or without
    modification, are permitted provided that the following conditions are
    met:

    1. Redistributions of source code must retain the above copyright
    notice, this list of conditions and the following disclaimer.

    2. Redistributions in binary form must reproduce the above
    copyright notice, this list of conditions and the following disclaimer
    in the documentation and/or other materials provided with the
    distribution.

    THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
    "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
    LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
    A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
    OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
    SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
    LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
    DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
    THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
    (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
    OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

    Home: https://github.com/gorhill/lz4-wasm

    I used the same license as the one picked by creator of LZ4 out of respect
    for his creation, see https://lz4.github.io/lz4/

*/

'use strict';

/******************************************************************************/

(function(context) {                    // >>>> Start of private namespace

/******************************************************************************/

const growOutputBuffer = function(instance, size) {
    if (
        instance.outputBuffer === undefined ||
        instance.outputBuffer.byteLength < size
    ) {
        instance.outputBuffer = new ArrayBuffer(size + 0xFFFF & 0x7FFF0000);
    }
    return instance.outputBuffer;
};

const encodeBound = function(size) {
    return size > 0x7E000000 ?
        0 :
        size + (size / 255 | 0) + 16;
};

const encodeBlock = function(instance, iBuf, oOffset) {
    let iLen = iBuf.byteLength;
    if ( iLen >= 0x7E000000 ) { throw new RangeError(); }

    // "The last match must start at least 12 bytes before end of block"
    let lastMatchPos = iLen - 12;

    // "The last 5 bytes are always literals"
    let lastLiteralPos = iLen - 5;

    if ( instance.hashTable === undefined ) {
        instance.hashTable = new Int32Array(65536);
    }
    instance.hashTable.fill(-65536);

    if ( iBuf instanceof ArrayBuffer ) {
        iBuf = new Uint8Array(iBuf);
    }

    let oLen = oOffset + encodeBound(iLen);
    let oBuf = new Uint8Array(growOutputBuffer(instance, oLen), 0, oLen);
    let iPos = 0;
    let oPos = oOffset;
    let anchorPos = 0;

    // sequence-finding loop
    for (;;) {
        let refPos;
        let mOffset;
        let sequence = iBuf[iPos] << 8 | iBuf[iPos+1] << 16 | iBuf[iPos+2] << 24;

        // match-finding loop
        while ( iPos <= lastMatchPos ) {
            sequence = sequence >>> 8 | iBuf[iPos+3] << 24;
            let hash = (sequence * 0x9E37 & 0xFFFF) + (sequence * 0x79B1 >>> 16) & 0xFFFF;
            refPos = instance.hashTable[hash];
            instance.hashTable[hash] = iPos;
            mOffset = iPos - refPos;
            if (
                mOffset < 65536 &&
                iBuf[refPos+0] === ((sequence       ) & 0xFF) &&
                iBuf[refPos+1] === ((sequence >>>  8) & 0xFF) &&
                iBuf[refPos+2] === ((sequence >>> 16) & 0xFF) &&
                iBuf[refPos+3] === ((sequence >>> 24) & 0xFF)
            ) {
                break;
            }
            iPos += 1;
        }

        // no match found
        if ( iPos > lastMatchPos ) { break; }

        // match found
        let lLen = iPos - anchorPos;
        let mLen = iPos;
        iPos += 4; refPos += 4;
        while ( iPos < lastLiteralPos && iBuf[iPos] === iBuf[refPos] ) {
            iPos += 1; refPos += 1;
        }
        mLen = iPos - mLen;
        let token = mLen < 19 ? mLen - 4 : 15;

        // write token, length of literals if needed
        if ( lLen >= 15 ) {
            oBuf[oPos++] = 0xF0 | token;
            let l = lLen - 15;
            while ( l >= 255 ) {
                oBuf[oPos++] = 255;
                l -= 255;
            }
            oBuf[oPos++] = l;
        } else {
            oBuf[oPos++] = (lLen << 4) | token;
        }

        // write literals
        while ( lLen-- ) {
            oBuf[oPos++] = iBuf[anchorPos++];
        }

        if ( mLen === 0 ) { break; }

        // write offset of match
        oBuf[oPos+0] = mOffset;
        oBuf[oPos+1] = mOffset >>> 8;
        oPos += 2;

        // write length of match if needed
        if ( mLen >= 19 ) {
            let l = mLen - 19;
            while ( l >= 255 ) {
                oBuf[oPos++] = 255;
                l -= 255;
            }
            oBuf[oPos++] = l;
        }

        anchorPos = iPos;
    }

    // last sequence is literals only
    let lLen = iLen - anchorPos;
    if ( lLen >= 15 ) {
        oBuf[oPos++] = 0xF0;
        let l = lLen - 15;
        while ( l >= 255 ) {
            oBuf[oPos++] = 255;
            l -= 255;
        }
        oBuf[oPos++] = l;
    } else {
        oBuf[oPos++] = lLen << 4;
    }
    while ( lLen-- ) {
        oBuf[oPos++] = iBuf[anchorPos++];
    }

    return new Uint8Array(oBuf.buffer, 0, oPos);
};

const decodeBlock = function(instance, iBuf, iOffset, oLen) {
    let iLen = iBuf.byteLength;
    let oBuf = new Uint8Array(growOutputBuffer(instance, oLen), 0, oLen);
    let iPos = iOffset, oPos = 0;

    while ( iPos < iLen ) {
        let token = iBuf[iPos++];

        // literals
        let clen = token >>> 4;

        // length of literals
        if ( clen !== 0 ) {
            if ( clen === 15 ) {
                let l;
                for (;;) {
                    l = iBuf[iPos++];
                    if ( l !== 255 ) { break; }
                    clen += 255;
                }
                clen += l;
            }

            // copy literals
            let end = iPos + clen;
            while ( iPos < end ) {
                oBuf[oPos++] = iBuf[iPos++];
            }
            if ( iPos === iLen ) { break; }
        }

        // match
        let mOffset = iBuf[iPos+0] | (iBuf[iPos+1] << 8);
        if ( mOffset === 0 || mOffset > oPos ) { return; }
        iPos += 2;

        // length of match
        clen = (token & 0x0F) + 4;
        if ( clen === 19 ) {
            let l;
            for (;;) {
                l = iBuf[iPos++];
                if ( l !== 255 ) { break; }
                clen += 255;
            }
            clen += l;
        }

        // copy match
        let mPos = oPos - mOffset;
        let end = oPos + clen;
        while ( oPos < end ) {
            oBuf[oPos++] = oBuf[mPos++];
        }
    }

    return oBuf;
};

/******************************************************************************/

context.LZ4BlockJS = function() {
    this.hashTable = undefined;
    this.outputBuffer = undefined;
};

context.LZ4BlockJS.prototype = {
    flavor: 'js',
    init: function() {
        return Promise.resolve(true);
    },

    reset: function() {
        this.hashTable = undefined;
        this.outputBuffer = undefined;
    },

    bytesInUse: function() {
        let bytesInUse = 0;
        if ( this.hashTable !== undefined ) {
            bytesInUse += this.hashTable.byteLength;
        }
        if ( this.outputBuffer !== undefined ) {
            bytesInUse += this.outputBuffer.byteLength;
        }
        return bytesInUse;
    },

    encodeBlock: function(input, outputOffset) {
        if ( input instanceof ArrayBuffer ) {
            input = new Uint8Array(input);
        } else if ( input instanceof Uint8Array === false ) {
            throw new TypeError();
        }
        return encodeBlock(this, input, outputOffset);
    },

    decodeBlock: function(input, inputOffset, outputSize) {
        if ( input instanceof ArrayBuffer ) {
            input = new Uint8Array(input);
        } else if ( input instanceof Uint8Array === false ) {
            throw new TypeError();
        }
        return decodeBlock(this, input, inputOffset, outputSize);
    }
};

/******************************************************************************/

})(this || self);                       // <<<< End of private namespace

/******************************************************************************/

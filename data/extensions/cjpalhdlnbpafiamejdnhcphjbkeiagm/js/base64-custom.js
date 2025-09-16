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

/******************************************************************************/

// Custom base64 codecs. These codecs are meant to encode/decode typed arrays
// to/from strings.

// https://github.com/uBlockOrigin/uBlock-issues/issues/461
//   Provide a fallback encoding for Chromium 59 and less by issuing a plain
//   JSON string. The fallback can be removed once min supported version is
//   above 59.

// TODO: rename µBlock.base64 to µBlock.SparseBase64, now that
//       µBlock.DenseBase64 has been introduced.
// TODO: Should no longer need to test presence of TextEncoder/TextDecoder.

const valToDigit = new Uint8Array(64);
const digitToVal = new Uint8Array(128);
{
    const chars = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz@%';
    for ( let i = 0, n = chars.length; i < n; i++ ) {
        const c = chars.charCodeAt(i);
        valToDigit[i] = c;
        digitToVal[c] = i;
    }
}

// The dense base64 codec is best for typed buffers which values are
// more random. For example, buffer contents as a result of compression
// contain less repetitive values and thus the content is more
// random-looking.

// TODO: Investigate that in Firefox, creating a new Uint8Array from the
//       ArrayBuffer fails, the content of the resulting Uint8Array is
//       non-sensical. WASM-related?

export const denseBase64 = {
    magic: 'DenseBase64_1',

    encode: function(input) {
        const m = input.length % 3;
        const n = input.length - m;
        let outputLength = n / 3 * 4;
        if ( m !== 0 ) {
            outputLength += m + 1;
        }
        const output = new Uint8Array(outputLength);
        let j = 0;
        for ( let i = 0; i < n; i += 3) {
            const i1 = input[i+0];
            const i2 = input[i+1];
            const i3 = input[i+2];
            output[j+0] = valToDigit[                     i1 >>> 2];
            output[j+1] = valToDigit[i1 << 4 & 0b110000 | i2 >>> 4];
            output[j+2] = valToDigit[i2 << 2 & 0b111100 | i3 >>> 6];
            output[j+3] = valToDigit[i3      & 0b111111           ];
            j += 4;
        }
        if ( m !== 0 ) {
            const i1 = input[n];
            output[j+0] = valToDigit[i1 >>> 2];
            if ( m === 1 ) {    // 1 value
                output[j+1] = valToDigit[i1 << 4 & 0b110000];
            } else {            // 2 values
                const i2 = input[n+1];
                output[j+1] = valToDigit[i1 << 4 & 0b110000 | i2 >>> 4];
                output[j+2] = valToDigit[i2 << 2 & 0b111100           ];
            }
        }
        const textDecoder = new TextDecoder();
        const b64str = textDecoder.decode(output);
        return this.magic + b64str;
    },

    decode: function(instr, arrbuf) {
        if ( instr.startsWith(this.magic) === false ) {
            throw new Error('Invalid µBlock.denseBase64 encoding');
        }
        const outputLength = this.decodeSize(instr);
        const outbuf = arrbuf instanceof ArrayBuffer === false
            ? new Uint8Array(outputLength)
            : new Uint8Array(arrbuf);
        const inputLength = instr.length - this.magic.length;
        let i = this.magic.length;
        let j = 0;
        const m = inputLength & 3;
        const n = i + inputLength - m;
        while ( i < n ) {
            const i1 = digitToVal[instr.charCodeAt(i+0)];
            const i2 = digitToVal[instr.charCodeAt(i+1)];
            const i3 = digitToVal[instr.charCodeAt(i+2)];
            const i4 = digitToVal[instr.charCodeAt(i+3)];
            i += 4;
            outbuf[j+0] = i1 << 2              | i2 >>> 4;
            outbuf[j+1] = i2 << 4 & 0b11110000 | i3 >>> 2;
            outbuf[j+2] = i3 << 6 & 0b11000000 | i4;
            j += 3;
        }
        if ( m !== 0 ) {
            const i1 = digitToVal[instr.charCodeAt(i+0)];
            const i2 = digitToVal[instr.charCodeAt(i+1)];
            outbuf[j+0] = i1 << 2 | i2 >>> 4;
            if ( m === 3 ) {
                const i3 = digitToVal[instr.charCodeAt(i+2)];
                outbuf[j+1] = i2 << 4 & 0b11110000 | i3 >>> 2;
            }
        }
        return outbuf;
    },

    decodeSize: function(instr) {
        if ( instr.startsWith(this.magic) === false ) { return 0; }
        const inputLength = instr.length - this.magic.length;
        const m = inputLength & 3;
        const n = inputLength - m;
        let outputLength = (n >>> 2) * 3;
        if ( m !== 0 ) {
            outputLength += m - 1;
        }
        return outputLength;
    },
};

/******************************************************************************/

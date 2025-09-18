/*******************************************************************************

    uBlock Origin - a browser extension to block requests.
    Copyright (C) 2024-present Raymond Hill

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
 * 
 * Structured-Cloneable to Unicode-Only SERIALIZER
 * 
 * Purpose:
 * 
 * Serialize/deserialize arbitrary JS data to/from well-formed Unicode strings.
 * 
 * The browser does not expose an API to serialize structured-cloneable types
 * into a single string. JSON.stringify() does not support complex JavaScript
 * objects, and does not support references to composite types. Unless the
 * data to serialize is only JS strings, it is difficult to easily switch
 * from one type of storage to another.
 * 
 * Serializing to a well-formed Unicode string allows to store structured-
 * cloneable data to any storage. Not all storages support storing binary data,
 * but all storages support storing Unicode strings.
 * 
 * Structured-cloneable types:
 * https://developer.mozilla.org/en-US/docs/Web/API/Web_Workers_API/Structured_clone_algorithm#supported_types
 * 
 * ----------------+------------------+------------------+----------------------
 * Data types      | String           | JSONable         | structured-cloneable
 * ================+============================================================
 * document.cookie | Yes              | No               | No
 * ----------------+------------------+------------------+----------------------
 * localStorage    | Yes              | No               | No
 * ----------------+------------------+------------------+----------------------
 * IndexedDB       | Yes              | Yes              | Yes
 * ----------------+------------------+------------------+----------------------
 * browser.storage | Yes              | Yes              | No
 * ----------------+------------------+------------------+----------------------
 * Cache API       | Yes              | No               | No
 * ----------------+------------------+------------------+----------------------
 * 
 * The above table shows that only JS strings can be persisted natively to all
 * types of storage. The purpose of this library is to convert
 * structure-cloneable data (which is a superset of JSONable data) into a
 * single JS string. The resulting string is meant to be as small as possible.
 * As a result, it is not human-readable, though it contains only printable
 * ASCII characters -- and possibly Unicode characters beyond ASCII.
 * 
 * The resulting JS string will not contain characters which require escaping
 * should it be converted to a JSON value. However it may contain characters
 * which require escaping should it be converted to a URI component.
 * 
 * Characteristics:
 * 
 * - Serializes/deserializes data to/from a single well-formed Unicode string
 * - Strings do not require escaping, i.e. they are stored as-is
 * - Supports multiple references to same object
 * - Supports reference cycles
 * - Supports synchronous and asynchronous API
 * - Supports usage of Worker
 * - Optionally supports LZ4 compression
 * 
 * TODO:
 * 
 * - Harden against unexpected conditions, such as corrupted string during
 *   deserialization.
 * - Evaluate supporting checksum.
 * 
 * */

const VERSION = 1;
const SEPARATORCHAR = ' ';
const SEPARATORCHARCODE = SEPARATORCHAR.charCodeAt(0);
const SENTINELCHAR = '!';
const SENTINELCHARCODE = SENTINELCHAR.charCodeAt(0);
const MAGICPREFIX = `UOSC_${VERSION}${SEPARATORCHAR}`;
const MAGICLZ4PREFIX = `UOSC/lz4_${VERSION}${SEPARATORCHAR}`;
const FAILMARK = Number.MAX_SAFE_INTEGER;
// Avoid characters which require escaping when serialized to JSON:
const SAFECHARS = "&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[]^_`abcdefghijklmnopqrstuvwxyz{|}~";
const NUMSAFECHARS = SAFECHARS.length;
const BITS_PER_SAFECHARS = Math.log2(NUMSAFECHARS);

const { intToChar, intToCharCode, charCodeToInt } = (( ) => {
    const intToChar = [];
    const intToCharCode = [];
    const charCodeToInt = [];
    for ( let i = 0; i < NUMSAFECHARS; i++ ) {
        intToChar[i] = SAFECHARS.charAt(i);
        intToCharCode[i] = SAFECHARS.charCodeAt(i);
        charCodeToInt[i] = 0;
    }
    for ( let i = NUMSAFECHARS; i < 128; i++ ) {
        intToChar[i] = '';
        intToCharCode[i] = 0;
        charCodeToInt[i] = 0;
    }
    for ( let i = 0; i < SAFECHARS.length; i++ ) {
        charCodeToInt[SAFECHARS.charCodeAt(i)] = i;
    }
    return { intToChar, intToCharCode, charCodeToInt };
})();

let iota = 1;
const I_STRING_SMALL      = iota++;
const I_STRING_LARGE      = iota++;
const I_ZERO              = iota++;
const I_INTEGER_SMALL_POS = iota++;
const I_INTEGER_SMALL_NEG = iota++;
const I_INTEGER_LARGE_POS = iota++;
const I_INTEGER_LARGE_NEG = iota++;
const I_BOOL_FALSE        = iota++;
const I_BOOL_TRUE         = iota++;
const I_NULL              = iota++;
const I_UNDEFINED         = iota++;
const I_FLOAT             = iota++;
const I_REGEXP            = iota++;
const I_DATE              = iota++;
const I_REFERENCE         = iota++;
const I_OBJECT_SMALL      = iota++;
const I_OBJECT_LARGE      = iota++;
const I_ARRAY_SMALL       = iota++;
const I_ARRAY_LARGE       = iota++;
const I_SET_SMALL         = iota++;
const I_SET_LARGE         = iota++;
const I_MAP_SMALL         = iota++;
const I_MAP_LARGE         = iota++;
const I_ARRAYBUFFER       = iota++;
const I_INT8ARRAY         = iota++;
const I_UINT8ARRAY        = iota++;
const I_UINT8CLAMPEDARRAY = iota++;
const I_INT16ARRAY        = iota++;
const I_UINT16ARRAY       = iota++;
const I_INT32ARRAY        = iota++;
const I_UINT32ARRAY       = iota++;
const I_FLOAT32ARRAY      = iota++;
const I_FLOAT64ARRAY      = iota++;
const I_DATAVIEW          = iota++;

const C_STRING_SMALL      = intToChar[I_STRING_SMALL];
const C_STRING_LARGE      = intToChar[I_STRING_LARGE];
const C_ZERO              = intToChar[I_ZERO];
const C_INTEGER_SMALL_POS = intToChar[I_INTEGER_SMALL_POS];
const C_INTEGER_SMALL_NEG = intToChar[I_INTEGER_SMALL_NEG];
const C_INTEGER_LARGE_POS = intToChar[I_INTEGER_LARGE_POS];
const C_INTEGER_LARGE_NEG = intToChar[I_INTEGER_LARGE_NEG];
const C_BOOL_FALSE        = intToChar[I_BOOL_FALSE];
const C_BOOL_TRUE         = intToChar[I_BOOL_TRUE];
const C_NULL              = intToChar[I_NULL];
const C_UNDEFINED         = intToChar[I_UNDEFINED];
const C_FLOAT             = intToChar[I_FLOAT];
const C_REGEXP            = intToChar[I_REGEXP];
const C_DATE              = intToChar[I_DATE];
const C_REFERENCE         = intToChar[I_REFERENCE];
const C_OBJECT_SMALL      = intToChar[I_OBJECT_SMALL];
const C_OBJECT_LARGE      = intToChar[I_OBJECT_LARGE];
const C_ARRAY_SMALL       = intToChar[I_ARRAY_SMALL];
const C_ARRAY_LARGE       = intToChar[I_ARRAY_LARGE];
const C_SET_SMALL         = intToChar[I_SET_SMALL];
const C_SET_LARGE         = intToChar[I_SET_LARGE];
const C_MAP_SMALL         = intToChar[I_MAP_SMALL];
const C_MAP_LARGE         = intToChar[I_MAP_LARGE];
const C_ARRAYBUFFER       = intToChar[I_ARRAYBUFFER];
const C_INT8ARRAY         = intToChar[I_INT8ARRAY];
const C_UINT8ARRAY        = intToChar[I_UINT8ARRAY];
const C_UINT8CLAMPEDARRAY = intToChar[I_UINT8CLAMPEDARRAY];
const C_INT16ARRAY        = intToChar[I_INT16ARRAY];
const C_UINT16ARRAY       = intToChar[I_UINT16ARRAY];
const C_INT32ARRAY        = intToChar[I_INT32ARRAY];
const C_UINT32ARRAY       = intToChar[I_UINT32ARRAY];
const C_FLOAT32ARRAY      = intToChar[I_FLOAT32ARRAY];
const C_FLOAT64ARRAY      = intToChar[I_FLOAT64ARRAY];
const C_DATAVIEW          = intToChar[I_DATAVIEW];

// Just reuse already defined constants, we just need distinct values
const I_STRING            = I_STRING_SMALL;
const I_NUMBER            = I_FLOAT;
const I_BOOL              = I_BOOL_FALSE;
const I_OBJECT            = I_OBJECT_SMALL;
const I_ARRAY             = I_ARRAY_SMALL;
const I_SET               = I_SET_SMALL;
const I_MAP               = I_MAP_SMALL;

const typeToSerializedInt = {
    'string': I_STRING,
    'number': I_NUMBER,
    'boolean': I_BOOL,
    'object': I_OBJECT,
};

const xtypeToSerializedInt = {
    '[object RegExp]': I_REGEXP,
    '[object Date]': I_DATE,
    '[object Array]': I_ARRAY,
    '[object Set]': I_SET,
    '[object Map]': I_MAP,
    '[object ArrayBuffer]': I_ARRAYBUFFER,
    '[object Int8Array]': I_INT8ARRAY,
    '[object Uint8Array]': I_UINT8ARRAY,
    '[object Uint8ClampedArray]': I_UINT8CLAMPEDARRAY,
    '[object Int16Array]': I_INT16ARRAY,
    '[object Uint16Array]': I_UINT16ARRAY,
    '[object Int32Array]': I_INT32ARRAY,
    '[object Uint32Array]': I_UINT32ARRAY,
    '[object Float32Array]': I_FLOAT32ARRAY,
    '[object Float64Array]': I_FLOAT64ARRAY,
    '[object DataView]': I_DATAVIEW,
};

const xtypeToSerializedChar = {
    '[object Int8Array]': C_INT8ARRAY,
    '[object Uint8Array]': C_UINT8ARRAY,
    '[object Uint8ClampedArray]': C_UINT8CLAMPEDARRAY,
    '[object Int16Array]': C_INT16ARRAY,
    '[object Uint16Array]': C_UINT16ARRAY,
    '[object Int32Array]': C_INT32ARRAY,
    '[object Uint32Array]': C_UINT32ARRAY,
    '[object Float32Array]': C_FLOAT32ARRAY,
    '[object Float64Array]': C_FLOAT64ARRAY,
};

const toArrayBufferViewConstructor = {
    [`${I_INT8ARRAY}`]: Int8Array,
    [`${I_UINT8ARRAY}`]: Uint8Array,
    [`${I_UINT8CLAMPEDARRAY}`]: Uint8ClampedArray,
    [`${I_INT16ARRAY}`]: Int16Array,
    [`${I_UINT16ARRAY}`]: Uint16Array,
    [`${I_INT32ARRAY}`]: Int32Array,
    [`${I_UINT32ARRAY}`]: Uint32Array,
    [`${I_FLOAT32ARRAY}`]: Float32Array,
    [`${I_FLOAT64ARRAY}`]: Float64Array,
    [`${I_DATAVIEW}`]: DataView,
};

/******************************************************************************/

const textCodec = {
    decoder: null,
    encoder: null,
    decode(...args) {
        if ( this.decoder === null ) {
            this.decoder = new globalThis.TextDecoder();
        }
        return this.decoder.decode(...args);
    },
    encode(...args) {
        if ( this.encoder === null ) {
            this.encoder = new globalThis.TextEncoder();
        }
        return this.encoder.encode(...args);
    },
    encodeInto(...args) {
        if ( this.encoder === null ) {
            this.encoder = new globalThis.TextEncoder();
        }
        return this.encoder.encodeInto(...args);
    },
};

const isInteger = Number.isInteger;

const writeRefs = new Map();
const writeBuffer = [];

const readRefs = new Map();
let readStr = '';
let readPtr = 0;
let readEnd = 0;

let refCounter = 1;

let uint8Input = null;

const uint8InputFromAsciiStr = s => {
    if ( uint8Input === null || uint8Input.length < s.length ) {
        uint8Input = new Uint8Array(s.length + 0x03FF & ~0x03FF);
    }
    textCodec.encodeInto(s, uint8Input);
    return uint8Input;
};

const isInstanceOf = (o, s) => {
    return typeof o === 'object' && o !== null && (
        s === 'Object' || Object.prototype.toString.call(o) === `[object ${s}]`
    );
};

const shouldCompress = (s, options) =>
    options.compress === true && (
        options.compressThreshold === undefined ||
        options.compressThreshold <= s.length
    );

/*******************************************************************************
 * 
 * A large Uint is always a positive integer (can be zero), assumed to be
 * large, i.e. > NUMSAFECHARS -- but not necessarily. The serialized value has
 * always at least one digit, and is always followed by a separator.
 * 
 * */

const strFromLargeUint = i => {
    let r = 0, s = '';
    for (;;) {
        r = i % NUMSAFECHARS;
        s += intToChar[r];
        i -= r;
        if ( i === 0 ) { break; }
        i /= NUMSAFECHARS;
    }
    return s + SEPARATORCHAR;
};

const deserializeLargeUint = ( ) => {
    let c = readStr.charCodeAt(readPtr++);
    let n = charCodeToInt[c];
    let m = 1;
    while ( (c = readStr.charCodeAt(readPtr++)) !== SEPARATORCHARCODE ) {
        m *= NUMSAFECHARS;
        n += m * charCodeToInt[c];
    }
    return n;
};

/*******************************************************************************
 * 
 * Methods specific to ArrayBuffer objects to serialize optimally according to
 * the content of the buffer.
 * 
 * In sparse mode, number of output bytes per input int32 (4-byte) value:
 * [v === zero]: 1 byte (separator)
 * [v !== zero]: n digits + 1 byte (separator)
 * 
 * */

const sparseValueLen = v => v !== 0
    ? (Math.log2(v) / BITS_PER_SAFECHARS | 0) + 2
    : 1;

const analyzeArrayBuffer = arrbuf => {
    const byteLength = arrbuf.byteLength;
    const uint32len = byteLength >>> 2;
    const uint32arr = new Uint32Array(arrbuf, 0, uint32len);
    let notzeroCount = 0;
    for ( let i = uint32len-1; i >= 0; i-- ) {
        if ( uint32arr[i] === 0 ) { continue; }
        notzeroCount = i + 1;
        break;
    }
    const end = notzeroCount + 1 <= uint32len ? notzeroCount << 2 : byteLength;
    const endUint32 = end >>> 2;
    const remUint8 = end & 0b11;
    const denseSize = endUint32 * 5 + (remUint8 ? remUint8 + 1 : 0);
    let sparseSize = 0;
    for ( let i = 0; i < endUint32; i++ ) {
        sparseSize += sparseValueLen(uint32arr[i]);
        if ( sparseSize > denseSize ) {
            return { end, dense: true, denseSize };
        }
    }
    if ( remUint8 !== 0 ) {
        sparseSize += 1; // sentinel
        const uint8arr = new Uint8Array(arrbuf, endUint32 << 2);
        for ( let i = 0; i < remUint8; i++ ) {
            sparseSize += sparseValueLen(uint8arr[i]);
        }
    }
    return { end, dense: false, sparseSize };
};

const denseArrayBufferToStr = (arrbuf, details) => {
    const end = details.end;
    const m = end % 4;
    const n = end - m;
    const uin32len = n >>> 2;
    const uint32arr = new Uint32Array(arrbuf, 0, uin32len);
    const output = new Uint8Array(details.denseSize);
    let j = 0, v = 0;
    for ( let i = 0; i < uin32len; i++ ) {
        v = uint32arr[i];
        output[j+0] = intToCharCode[v % NUMSAFECHARS];
        v = v / NUMSAFECHARS | 0;
        output[j+1] = intToCharCode[v % NUMSAFECHARS];
        v = v / NUMSAFECHARS | 0;
        output[j+2] = intToCharCode[v % NUMSAFECHARS];
        v = v / NUMSAFECHARS | 0;
        output[j+3] = intToCharCode[v % NUMSAFECHARS];
        v = v / NUMSAFECHARS | 0;
        output[j+4] = intToCharCode[v];
        j += 5;
    }
    if ( m !== 0 ) {
        const uint8arr = new Uint8Array(arrbuf, n);
        v = uint8arr[0];
        if ( m > 1 ) {
            v += uint8arr[1] << 8;
            if ( m > 2 ) {
                v += uint8arr[2] << 16;
            }
        }
        output[j+0] = intToCharCode[v % NUMSAFECHARS];
        v = v / NUMSAFECHARS | 0;
        output[j+1] = intToCharCode[v % NUMSAFECHARS];
        if ( m > 1 ) {
            v = v / NUMSAFECHARS | 0;
            output[j+2] = intToCharCode[v % NUMSAFECHARS];
            if ( m > 2 ) {
                v = v / NUMSAFECHARS | 0;
                output[j+3] = intToCharCode[v % NUMSAFECHARS];
            }
        }
    }
    return textCodec.decode(output);
};

const BASE88_POW1 = NUMSAFECHARS;
const BASE88_POW2 = NUMSAFECHARS * BASE88_POW1;
const BASE88_POW3 = NUMSAFECHARS * BASE88_POW2;
const BASE88_POW4 = NUMSAFECHARS * BASE88_POW3;

const denseArrayBufferFromStr = (denseStr, arrbuf) => {
    const input = uint8InputFromAsciiStr(denseStr);
    const end = denseStr.length;
    const m = end % 5;
    const n = end - m;
    const uin32len = n / 5 * 4 >>> 2;
    const uint32arr = new Uint32Array(arrbuf, 0, uin32len);
    let j = 0, v = 0;
    for ( let i = 0; i < n; i += 5 ) {
        v  = charCodeToInt[input[i+0]];
        v += charCodeToInt[input[i+1]] * BASE88_POW1;
        v += charCodeToInt[input[i+2]] * BASE88_POW2;
        v += charCodeToInt[input[i+3]] * BASE88_POW3;
        v += charCodeToInt[input[i+4]] * BASE88_POW4;
        uint32arr[j++] = v;
    }
    if ( m === 0 ) { return; }
    v  = charCodeToInt[input[n+0]] +
         charCodeToInt[input[n+1]] * BASE88_POW1;
    if ( m > 2 ) {
        v += charCodeToInt[input[n+2]] * BASE88_POW2;
        if ( m > 3 ) {
            v += charCodeToInt[input[n+3]] * BASE88_POW3;
        }
    }
    const uint8arr = new Uint8Array(arrbuf, j << 2);
    uint8arr[0] = v & 255;
    if ( v !== 0 ) {
        v >>>= 8;
        uint8arr[1] = v & 255;
        if ( v !== 0 ) {
            v >>>= 8;
            uint8arr[2] = v & 255;
        }
    }
};

const sparseArrayBufferToStr = (arrbuf, details) => {
    const end = details.end;
    const uint8out = new Uint8Array(details.sparseSize);
    const uint32len = end >>> 2;
    const uint32arr = new Uint32Array(arrbuf, 0, uint32len);
    let j = 0, n = 0, r = 0;
    for ( let i = 0; i < uint32len; i++ ) {
        n = uint32arr[i];
        if ( n !== 0 ) {
            for (;;) {
                r = n % NUMSAFECHARS;
                uint8out[j++] = intToCharCode[r];
                n -= r;
                if ( n === 0 ) { break; }
                n /= NUMSAFECHARS;
            }
        }
        uint8out[j++] = SEPARATORCHARCODE;
    }
    const uint8rem = end & 0b11;
    if ( uint8rem !== 0 ) {
        uint8out[j++] = SENTINELCHARCODE;
        const uint8arr = new Uint8Array(arrbuf, end - uint8rem, uint8rem);
        for ( let i = 0; i < uint8rem; i++ ) {
            n = uint8arr[i];
            if ( n !== 0 ) {
                for (;;) {
                    r = n % NUMSAFECHARS;
                    uint8out[j++] = intToCharCode[r];
                    n -= r;
                    if ( n === 0 ) { break; }
                    n /= NUMSAFECHARS;
                }
            }
            uint8out[j++] = SEPARATORCHARCODE;
        }
    }
    return textCodec.decode(uint8out);
};

const sparseArrayBufferFromStr = (sparseStr, arrbuf) => {
    const sparseLen = sparseStr.length;
    const input = uint8InputFromAsciiStr(sparseStr);
    const end = arrbuf.byteLength;
    const uint32len = end >>> 2;
    const uint32arr = new Uint32Array(arrbuf, 0, uint32len);
    let i = 0, j = 0, c = 0, n = 0, m = 0;
    for ( ; j < sparseLen; i++ ) {
        c = input[j++];
        if ( c === SEPARATORCHARCODE ) { continue; }
        if ( c === SENTINELCHARCODE ) { break; }
        n = charCodeToInt[c];
        m = 1;
        for (;;) {
            c = input[j++];
            if ( c === SEPARATORCHARCODE ) { break; }
            m *= NUMSAFECHARS;
            n += m * charCodeToInt[c];
        }
        uint32arr[i] = n;
    }
    if ( c === SENTINELCHARCODE ) {
        i <<= 2;
        const uint8arr = new Uint8Array(arrbuf, i);
        for ( ; j < sparseLen; i++ ) {
            c = input[j++];
            if ( c === SEPARATORCHARCODE ) { continue; }
            n = charCodeToInt[c];
            m = 1;
            for (;;) {
                c = input[j++];
                if ( c === SEPARATORCHARCODE ) { break; }
                m *= NUMSAFECHARS;
                n += m * charCodeToInt[c];
            }
            uint8arr[i] = n;
        }
    }
};

/******************************************************************************/

const _serialize = data => {
    // Primitive types
    if ( data === 0 ) {
        writeBuffer.push(C_ZERO);
        return;
    }
    if ( data === null ) {
        writeBuffer.push(C_NULL);
        return;
    }
    if ( data === undefined ) {
        writeBuffer.push(C_UNDEFINED);
        return;
    }
    // Type name
    switch ( typeToSerializedInt[typeof data] ) {
    case I_STRING: {
        const length = data.length;
        if ( length < NUMSAFECHARS ) {
            writeBuffer.push(C_STRING_SMALL + intToChar[length], data);
        } else {
            writeBuffer.push(C_STRING_LARGE + strFromLargeUint(length), data);
        }
        return;
    }
    case I_NUMBER:
        if ( isInteger(data) ) {
            if ( data >= NUMSAFECHARS ) {
                writeBuffer.push(C_INTEGER_LARGE_POS + strFromLargeUint(data));
            } else if ( data > 0 ) {
                writeBuffer.push(C_INTEGER_SMALL_POS + intToChar[data]);
            } else if ( data > -NUMSAFECHARS ) {
                writeBuffer.push(C_INTEGER_SMALL_NEG + intToChar[-data]);
            } else {
                writeBuffer.push(C_INTEGER_LARGE_NEG + strFromLargeUint(-data));
            }
        } else {
            const s = `${data}`;
            writeBuffer.push(C_FLOAT + strFromLargeUint(s.length) + s);
        }
        return;
    case I_BOOL:
        writeBuffer.push(data ? C_BOOL_TRUE : C_BOOL_FALSE);
        return;
    case I_OBJECT:
        break;
    default:
        return;
    }
    const xtypeName = Object.prototype.toString.call(data);
    const xtypeInt = xtypeToSerializedInt[xtypeName];
    if ( xtypeInt === I_REGEXP ) {
        writeBuffer.push(C_REGEXP);
        _serialize(data.source);
        _serialize(data.flags);
        return;
    }
    if ( xtypeInt === I_DATE ) {
        writeBuffer.push(C_DATE);
        _serialize(data.getTime());
        return;
    }
    // Reference to composite types
    const ref = writeRefs.get(data);
    if ( ref !== undefined ) {
        writeBuffer.push(C_REFERENCE + strFromLargeUint(ref));
        return;
    }
    // Remember reference
    writeRefs.set(data, refCounter++);
    // Extended type name
    switch ( xtypeInt ) {
    case I_ARRAY: {
        const size = data.length;
        if ( size < NUMSAFECHARS ) {
            writeBuffer.push(C_ARRAY_SMALL + intToChar[size]);
        } else {
            writeBuffer.push(C_ARRAY_LARGE + strFromLargeUint(size));
        }
        for ( const v of data ) {
            _serialize(v);
        }
        return;
    }
    case I_SET: {
        const size = data.size;
        if ( size < NUMSAFECHARS ) {
            writeBuffer.push(C_SET_SMALL + intToChar[size]);
        } else {
            writeBuffer.push(C_SET_LARGE + strFromLargeUint(size));
        }
        for ( const v of data ) {
            _serialize(v);
        }
        return;
    }
    case I_MAP: {
        const size = data.size;
        if ( size < NUMSAFECHARS ) {
            writeBuffer.push(C_MAP_SMALL + intToChar[size]);
        } else {
            writeBuffer.push(C_MAP_LARGE + strFromLargeUint(size));
        }
        for ( const [ k, v ] of data ) {
            _serialize(k);
            _serialize(v);
        }
        return;
    }
    case I_ARRAYBUFFER: {
        const byteLength = data.byteLength;
        writeBuffer.push(C_ARRAYBUFFER + strFromLargeUint(byteLength));
        _serialize(data.maxByteLength);
        const arrbuffDetails = analyzeArrayBuffer(data);
        _serialize(arrbuffDetails.dense);
        const str = arrbuffDetails.dense
            ? denseArrayBufferToStr(data, arrbuffDetails)
            : sparseArrayBufferToStr(data, arrbuffDetails);
        _serialize(str);
        //console.log(`arrbuf size=${byteLength} content size=${arrbuffDetails.end} dense=${arrbuffDetails.dense} array size=${arrbuffDetails.dense ? arrbuffDetails.denseSize : arrbuffDetails.sparseSize} serialized size=${str.length}`);
        return;
    }
    case I_INT8ARRAY:
    case I_UINT8ARRAY:
    case I_UINT8CLAMPEDARRAY:
    case I_INT16ARRAY:
    case I_UINT16ARRAY:
    case I_INT32ARRAY:
    case I_UINT32ARRAY:
    case I_FLOAT32ARRAY:
    case I_FLOAT64ARRAY:
        writeBuffer.push(
            xtypeToSerializedChar[xtypeName],
            strFromLargeUint(data.byteOffset),
            strFromLargeUint(data.length)
        );
        _serialize(data.buffer);
        return;
    case I_DATAVIEW:
        writeBuffer.push(C_DATAVIEW, strFromLargeUint(data.byteOffset), strFromLargeUint(data.byteLength));
        _serialize(data.buffer);
        return;
    default: {
        const keys = Object.keys(data);
        const size = keys.length;
        if ( size < NUMSAFECHARS ) {
            writeBuffer.push(C_OBJECT_SMALL + intToChar[size]);
        } else {
            writeBuffer.push(C_OBJECT_LARGE + strFromLargeUint(size));
        }
        for ( const key of keys ) {
            _serialize(key);
            _serialize(data[key]);
        }
        break;
    }
    }
};

/******************************************************************************/

const _deserialize = ( ) => {
    if ( readPtr >= readEnd ) { return; }
    const type = charCodeToInt[readStr.charCodeAt(readPtr++)];
    switch ( type ) {
    // Primitive types
    case I_STRING_SMALL:
    case I_STRING_LARGE: {
        const size = type === I_STRING_SMALL
            ? charCodeToInt[readStr.charCodeAt(readPtr++)]
            : deserializeLargeUint();
        const beg = readPtr;
        readPtr += size;
        return readStr.slice(beg, readPtr);
    }
    case I_ZERO:
        return 0;
    case I_INTEGER_SMALL_POS:
        return charCodeToInt[readStr.charCodeAt(readPtr++)];
    case I_INTEGER_SMALL_NEG:
        return -charCodeToInt[readStr.charCodeAt(readPtr++)];
    case I_INTEGER_LARGE_POS:
        return deserializeLargeUint();
    case I_INTEGER_LARGE_NEG:
        return -deserializeLargeUint();
    case I_BOOL_FALSE:
        return false;
    case I_BOOL_TRUE:
        return true;
    case I_NULL:
        return null;
    case I_UNDEFINED:
        return;
    case I_FLOAT: {
        const size = deserializeLargeUint();
        const beg = readPtr;
        readPtr += size;
        return parseFloat(readStr.slice(beg, readPtr));
    }
    case I_REGEXP: {
        const source = _deserialize();
        const flags = _deserialize();
        return new RegExp(source, flags);
    }
    case I_DATE: {
        const time = _deserialize();
        return new Date(time);
    }
    case I_REFERENCE: {
        const ref = deserializeLargeUint();
        return readRefs.get(ref);
    }
    case I_OBJECT_SMALL:
    case I_OBJECT_LARGE: {
        const out = {};
        readRefs.set(refCounter++, out);
        const entries = [];
        const size = type === I_OBJECT_SMALL
            ? charCodeToInt[readStr.charCodeAt(readPtr++)]
            : deserializeLargeUint();
        for ( let i = 0; i < size; i++ ) {
            const k = _deserialize();
            const v = _deserialize();
            entries.push([ k, v ]);
        }
        Object.assign(out, Object.fromEntries(entries));
        return out;
    }
    case I_ARRAY_SMALL:
    case I_ARRAY_LARGE: {
        const out = [];
        readRefs.set(refCounter++, out);
        const size = type === I_ARRAY_SMALL
            ? charCodeToInt[readStr.charCodeAt(readPtr++)]
            : deserializeLargeUint();
        for ( let i = 0; i < size; i++ ) {
            out.push(_deserialize());
        }
        return out;
    }
    case I_SET_SMALL:
    case I_SET_LARGE: {
        const out = new Set();
        readRefs.set(refCounter++, out);
        const size = type === I_SET_SMALL
            ? charCodeToInt[readStr.charCodeAt(readPtr++)]
            : deserializeLargeUint();
        for ( let i = 0; i < size; i++ ) {
            out.add(_deserialize());
        }
        return out;
    }
    case I_MAP_SMALL:
    case I_MAP_LARGE: {
        const out = new Map();
        readRefs.set(refCounter++, out);
        const size = type === I_MAP_SMALL
            ? charCodeToInt[readStr.charCodeAt(readPtr++)]
            : deserializeLargeUint();
        for ( let i = 0; i < size; i++ ) {
            const k = _deserialize();
            const v = _deserialize();
            out.set(k, v);
        }
        return out;
    }
    case I_ARRAYBUFFER: {
        const byteLength = deserializeLargeUint();
        const maxByteLength = _deserialize();
        let options;
        if ( maxByteLength !== 0 && maxByteLength !== byteLength ) {
            options = { maxByteLength };
        }
        const arrbuf = new ArrayBuffer(byteLength, options);
        const dense = _deserialize();
        const str = _deserialize();
        if ( dense ) {
            denseArrayBufferFromStr(str, arrbuf);
        } else {
            sparseArrayBufferFromStr(str, arrbuf);
        }
        readRefs.set(refCounter++, arrbuf);
        return arrbuf;
    }
    case I_INT8ARRAY:
    case I_UINT8ARRAY:
    case I_UINT8CLAMPEDARRAY:
    case I_INT16ARRAY:
    case I_UINT16ARRAY:
    case I_INT32ARRAY:
    case I_UINT32ARRAY:
    case I_FLOAT32ARRAY:
    case I_FLOAT64ARRAY:
    case I_DATAVIEW: {
        const byteOffset = deserializeLargeUint();
        const length = deserializeLargeUint();
        const ref = refCounter++;
        const arrayBuffer = _deserialize();
        const ctor = toArrayBufferViewConstructor[`${type}`];
        const out = new ctor(arrayBuffer, byteOffset, length);
        readRefs.set(ref, out);
        return out;
    }
    default:
        break;
    }
    readPtr = FAILMARK;
};

/*******************************************************************************
 * 
 * LZ4 block compression/decompression
 * 
 * Imported from:
 * https://github.com/gorhill/lz4-wasm/blob/8995cdef7b/dist/lz4-block-codec-js.js
 * 
 * Customized to avoid external dependencies as I entertain the idea of
 * spinning off the serializer as a standalone utility for all to use.
 * 
 * */
 
class LZ4BlockJS {
    constructor() {
        this.hashTable = undefined;
        this.outputBuffer = undefined;
    }
    reset() {
        this.hashTable = undefined;
        this.outputBuffer = undefined;
    }
    growOutputBuffer(size) {
        if ( this.outputBuffer !== undefined ) {
            if ( this.outputBuffer.byteLength >= size ) { return; }
        }
        this.outputBuffer = new ArrayBuffer(size + 0xFFFF & 0x7FFF0000);
    }
    encodeBound(size) {
        return size > 0x7E000000 ? 0 : size + (size / 255 | 0) + 16;
    }
    encodeBlock(iBuf, oOffset) {
        const iLen = iBuf.byteLength;
        if ( iLen >= 0x7E000000 ) { throw new RangeError(); }
        // "The last match must start at least 12 bytes before end of block"
        const lastMatchPos = iLen - 12;
        // "The last 5 bytes are always literals"
        const lastLiteralPos = iLen - 5;
        if ( this.hashTable === undefined ) {
            this.hashTable = new Int32Array(65536);
        }
        this.hashTable.fill(-65536);
        if ( isInstanceOf(iBuf, 'ArrayBuffer') ) {
            iBuf = new Uint8Array(iBuf);
        }
        const oLen = oOffset + this.encodeBound(iLen);
        this.growOutputBuffer(oLen);
        const oBuf = new Uint8Array(this.outputBuffer, 0, oLen);
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
                const hash = (sequence * 0x9E37 & 0xFFFF) + (sequence * 0x79B1 >>> 16) & 0xFFFF;
                refPos = this.hashTable[hash];
                this.hashTable[hash] = iPos;
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
            const token = mLen < 19 ? mLen - 4 : 15;
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
    }
    decodeBlock(iBuf, iOffset, oLen) {
        const iLen = iBuf.byteLength;
        this.growOutputBuffer(oLen);
        const oBuf = new Uint8Array(this.outputBuffer, 0, oLen);
        let iPos = iOffset, oPos = 0;
        while ( iPos < iLen ) {
            const token = iBuf[iPos++];
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
                const end = iPos + clen;
                while ( iPos < end ) {
                    oBuf[oPos++] = iBuf[iPos++];
                }
                if ( iPos === iLen ) { break; }
            }
            // match
            const mOffset = iBuf[iPos+0] | (iBuf[iPos+1] << 8);
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
            const end = oPos + clen;
            let mPos = oPos - mOffset;
            while ( oPos < end ) {
                oBuf[oPos++] = oBuf[mPos++];
            }
        }
        return oBuf;
    }
    encode(input, outputOffset) {
        if ( isInstanceOf(input, 'ArrayBuffer') ) {
            input = new Uint8Array(input);
        } else if ( isInstanceOf(input, 'Uint8Array') === false ) {
            throw new TypeError();
        }
        return this.encodeBlock(input, outputOffset);
    }
    decode(input, inputOffset, outputSize) {
        if ( isInstanceOf(input, 'ArrayBuffer') ) {
            input = new Uint8Array(input);
        } else if ( isInstanceOf(input, 'Uint8Array') === false ) {
            throw new TypeError();
        }
        return this.decodeBlock(input, inputOffset, outputSize);
    }
}

/*******************************************************************************
 * 
 * Synchronous APIs
 * 
 * */

export const serialize = (data, options = {}) => {
    refCounter = 1;
    _serialize(data);
    writeBuffer.unshift(MAGICPREFIX);
    const s = writeBuffer.join('');
    writeRefs.clear();
    writeBuffer.length = 0;
    if ( shouldCompress(s, options) === false ) { return s; }
    const lz4Util = new LZ4BlockJS();
    const uint8ArrayBefore = textCodec.encode(s);
    const uint8ArrayAfter = lz4Util.encode(uint8ArrayBefore, 0);
    const lz4 = {
        size: uint8ArrayBefore.length,
        data: new Uint8Array(uint8ArrayAfter),
    };
    refCounter = 1;
    _serialize(lz4);
    writeBuffer.unshift(MAGICLZ4PREFIX);
    const t = writeBuffer.join('');
    writeRefs.clear();
    writeBuffer.length = 0;
    const ratio = t.length / s.length;
    return ratio <= 0.85 ? t : s;
};

const deserializeById = (blockid, s) => {
    refCounter = 1;
    readStr = s;
    readEnd = s.length;
    readPtr = blockid.length;
    const data = _deserialize();
    readRefs.clear();
    readStr = '';
    if ( readPtr === FAILMARK ) { return; }
    return data;
};

export const deserialize = s => {
    if ( s.startsWith(MAGICLZ4PREFIX) ) {
        const lz4 = deserializeById(MAGICLZ4PREFIX, s);
        if ( lz4 ) {
            const lz4Util = new LZ4BlockJS();
            const uint8ArrayAfter = lz4Util.decode(lz4.data, 0, lz4.size);
            if ( uint8ArrayAfter ) {
                s = textCodec.decode(new Uint8Array(uint8ArrayAfter));
            }
        }
    }
    const data = s.startsWith(MAGICPREFIX)
        ? deserializeById(MAGICPREFIX, s)
        : undefined;
    uint8Input = null;
    return data;
};

export const isSerialized = s =>
    typeof s === 'string' &&
        (s.startsWith(MAGICLZ4PREFIX) || s.startsWith(MAGICPREFIX));

export const isCompressed = s =>
    typeof s === 'string' && s.startsWith(MAGICLZ4PREFIX);

/*******************************************************************************
 * 
 * Configuration
 * 
 * */

const defaultConfig = {
    threadTTL: 3000,
};

const validateConfig = {
    threadTTL: val => val > 0,
};

const currentConfig = Object.assign({}, defaultConfig);

export const getConfig = ( ) => Object.assign({}, currentConfig);

export const setConfig = config => {
    for ( const key in Object.keys(config) ) {
        if ( Object.hasOwn(defaultConfig, key) === false ) { continue; }
        const val = config[key];
        if ( typeof val !== typeof defaultConfig[key] ) { continue; }
        if ( (validateConfig[key])(val) === false ) { continue; }
        currentConfig[key] = val;
    }
};

/*******************************************************************************
 * 
 * Asynchronous APIs
 * 
 * Being asynchronous allows to support workers and future features such as
 * checksums.
 * 
 * */

const THREAD_AREYOUREADY = 1;
const THREAD_IAMREADY    = 2;
const THREAD_SERIALIZE   = 3;
const THREAD_DESERIALIZE = 4;

class MainThread {
    constructor() {
        this.name = 'main';
        this.jobs = [];
        this.workload = 0;
        this.timer = undefined;
        this.busy = 2;
    }

    process() {
        if ( this.jobs.length === 0 ) { return; }
        const job = this.jobs.shift();
        this.workload -= job.size;
        const result = job.what === THREAD_SERIALIZE
            ? serialize(job.data, job.options)
            : deserialize(job.data);
        job.resolve(result);
        this.processAsync();
        if ( this.jobs.length === 0 ) {
            this.busy = 2;
        } else if ( this.busy > 2 ) {
            this.busy -= 1;
        }
    }

    processAsync() {
        if ( this.timer !== undefined ) { return; }
        if ( this.jobs.length === 0 ) { return; }
        this.timer = globalThis.requestIdleCallback(deadline => {
            this.timer = undefined;
            globalThis.queueMicrotask(( ) => {
                this.process();
            });
            if ( deadline.timeRemaining() === 0 ) {
                this.busy += 1;
            }
        }, { timeout: 5 });
    }

    serialize(data, options) {
        return new Promise(resolve => {
            this.workload += 1;
            this.jobs.push({ what: THREAD_SERIALIZE, data, options, size: 1, resolve });
            this.processAsync();
        });
    }

    deserialize(data, options) {
        return new Promise(resolve => {
            const size = data.length;
            this.workload += size;
            this.jobs.push({ what: THREAD_DESERIALIZE, data, options, size, resolve });
            this.processAsync();
        });
    }

    get queueSize() {
        return this.jobs.length;
    }

    get workSize() {
        return this.workload * this.busy;
    }
}

class Thread {
    constructor(gcer) {
        this.name = 'worker';
        this.jobs = new Map();
        this.jobIdGenerator = 1;
        this.workload = 0;
        this.workerAccessTime = 0;
        this.workerTimer = undefined;
        this.gcer = gcer;
        this.workerPromise = new Promise(resolve => {
            let worker = null;
            try {
                worker = new Worker('js/s14e-serializer.js', { type: 'module' });
                worker.onmessage = ev => {
                    const msg = ev.data;
                    if ( isInstanceOf(msg, 'Object') === false ) { return; }
                    if ( msg.what === THREAD_IAMREADY ) {
                        worker.onmessage = ev => { this.onmessage(ev); };
                        worker.onerror = null;
                        resolve(worker);
                    }
                };
                worker.onerror = ( ) => {
                    worker.onmessage = worker.onerror = null;
                    resolve(null);
                };
                worker.postMessage({
                    what: THREAD_AREYOUREADY,
                    config: currentConfig,
                });
            } catch(ex) {
                console.info(ex);
                worker.onmessage = worker.onerror = null;
                resolve(null);
            }
        });
    }

    countdownWorker() {
        if ( this.workerTimer !== undefined ) { return; }
        this.workerTimer = setTimeout(async ( ) => {
            this.workerTimer = undefined;
            if ( this.jobs.size !== 0 ) { return; }
            const idleTime = Date.now() - this.workerAccessTime;
            if ( idleTime < currentConfig.threadTTL ) {
                return this.countdownWorker();
            }
            const worker = await this.workerPromise;
            if ( this.jobs.size !== 0 ) { return; }
            this.gcer(this);
            if ( worker === null ) { return; }
            worker.onmessage = worker.onerror = null;
            worker.terminate();
        }, currentConfig.threadTTL);
    }

    onmessage(ev) {
        this.ondone(ev.data);
    }

    ondone(job) {
        const resolve = this.jobs.get(job.id);
        if ( resolve === undefined ) { return; }
        this.jobs.delete(job.id);
        resolve(job.result);
        this.workload -= job.size;
        if ( this.jobs.size !== 0 ) { return; }
        this.countdownWorker();
    }

    async serialize(data, options) {
        return new Promise(resolve => {
            const id = this.jobIdGenerator++;
            this.workload += 1;
            this.jobs.set(id, resolve);
            return this.workerPromise.then(worker => {
                this.workerAccessTime = Date.now();
                if ( worker === null ) {
                    this.ondone({ id, result: serialize(data, options), size: 1 });
                } else {
                    worker.postMessage({ what: THREAD_SERIALIZE, id, data, options, size: 1 });
                }
            });
        });
    }

    async deserialize(data, options) {
        return new Promise(resolve => {
            const id = this.jobIdGenerator++;
            const size = data.length;
            this.workload += size;
            this.jobs.set(id, resolve);
            return this.workerPromise.then(worker => {
                this.workerAccessTime = Date.now();
                if ( worker === null ) {
                    this.ondone({ id, result: deserialize(data, options), size });
                } else {
                    worker.postMessage({ what: THREAD_DESERIALIZE, id, data, options, size });
                }
            });
        });
    }

    get queueSize() {
        return this.jobs.size;
    }

    get workSize() {
        return this.workload;
    }
}

const threads = {
    pool: [ new MainThread() ],
    thread(maxPoolSize) {
        const poolSize = this.pool.length;
        if ( poolSize !== 0 && poolSize >= maxPoolSize ) {
            if ( poolSize === 1 ) { return this.pool[0]; }
            return this.pool.reduce((a, b) => {
                //console.log(`${a.name}: q=${a.queueSize} w=${a.workSize} ${b.name}: q=${b.queueSize} w=${b.workSize}`);
                if ( b.queueSize === 0 ) { return b; }
                if ( a.queueSize === 0 ) { return a; }
                return b.workSize < a.workSize ? b : a;
            });
        }
        const thread = new Thread(thread => {
            const pos = this.pool.indexOf(thread);
            if ( pos === -1 ) { return; }
            this.pool.splice(pos, 1);
        });
        this.pool.push(thread);
        return thread;
    },
};

export async function serializeAsync(data, options = {}) {
    const maxThreadCount = options.multithreaded || 0;
    if ( maxThreadCount === 0 ) {
        return serialize(data, options);
    }
    const thread = threads.thread(maxThreadCount);
    //console.log(`serializeAsync: thread=${thread.name} workload=${thread.workSize}`);
    const result = await thread.serialize(data, options);
    if ( result !== undefined ) { return result; }
    return serialize(data, options);
}

export async function deserializeAsync(data, options = {}) {
    if ( isSerialized(data) === false ) { return data; }
    const maxThreadCount = options.multithreaded || 0;
    if ( maxThreadCount === 0 ) {
        return deserialize(data, options);
    }
    const thread = threads.thread(maxThreadCount);
    //console.log(`deserializeAsync: thread=${thread.name} data=${data.length} workload=${thread.workSize}`);
    const result = await thread.deserialize(data, options);
    if ( result !== undefined ) { return result; }
    return deserialize(data, options);
}

/*******************************************************************************
 * 
 * Worker-only code
 * 
 * */

if ( isInstanceOf(globalThis, 'DedicatedWorkerGlobalScope') ) {
    globalThis.onmessage = ev => {
        const msg = ev.data;
        switch ( msg.what ) {
        case THREAD_AREYOUREADY:
            setConfig(msg.config);
            globalThis.postMessage({ what: THREAD_IAMREADY });
            break;
        case THREAD_SERIALIZE: {
            const result = serialize(msg.data, msg.options);
            globalThis.postMessage({ id: msg.id, size: msg.size, result });
            break;
        }
        case THREAD_DESERIALIZE: {
            let result;
            try {
                result = deserialize(msg.data);
            } catch(ex) {
                console.error(ex);
            } finally {
                globalThis.postMessage({ id: msg.id, size: msg.size, result });
            }
            break;
        }
        default:
            break;
        }
    };
}

/******************************************************************************/

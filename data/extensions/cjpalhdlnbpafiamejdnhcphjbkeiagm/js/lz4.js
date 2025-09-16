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

/* global lz4BlockCodec */

import µb from './background.js';

/*******************************************************************************

    Experimental support for storage compression.

    For background information on the topic, see:
    https://github.com/uBlockOrigin/uBlock-issues/issues/141#issuecomment-407737186

**/

/******************************************************************************/

let promisedInstance;
let textEncoder, textDecoder;
let ttlCount = 0;
let ttlDelay = 60000;

const init = function() {
    ttlDelay = µb.hiddenSettings.autoUpdateAssetFetchPeriod * 2 * 1000;
    if ( promisedInstance === undefined ) {
        let flavor;
        if ( µb.hiddenSettings.disableWebAssembly === true ) {
            flavor = 'js';
        }
        promisedInstance = lz4BlockCodec.createInstance(flavor);
    }
    return promisedInstance;
};

// We can't shrink memory usage of lz4 codec instances, and in the
// current case memory usage can grow to a significant amount given
// that a single contiguous memory buffer is required to accommodate
// both input and output data. Thus a time-to-live implementation
// which will cause the wasm instance to be forgotten after enough
// time elapse without the instance being used.

const destroy = function() {
    //if ( lz4CodecInstance !== undefined ) {
    //    console.info(
    //        'uBO: freeing lz4-block-codec instance (%s KB)',
    //        lz4CodecInstance.bytesInUse() >>> 10
    //    );
    //}
    promisedInstance = undefined;
    textEncoder = textDecoder = undefined;
    ttlCount = 0;
};

const ttlTimer = vAPI.defer.create(destroy);

const ttlManage = function(count) {
    ttlTimer.off();
    ttlCount += count;
    if ( ttlCount > 0 ) { return; }
    ttlTimer.on(ttlDelay);
};

const encodeValue = function(lz4CodecInstance, dataIn) {
    if ( !lz4CodecInstance ) { return; }
    //let t0 = window.performance.now();
    if ( textEncoder === undefined ) {
        textEncoder = new TextEncoder();
    }
    const inputArray = textEncoder.encode(dataIn);
    const inputSize = inputArray.byteLength;
    const outputArray = lz4CodecInstance.encodeBlock(inputArray, 8);
    if ( outputArray instanceof Uint8Array === false ) { return; }
    outputArray[0] = 0x18;
    outputArray[1] = 0x4D;
    outputArray[2] = 0x22;
    outputArray[3] = 0x04;
    outputArray[4] = (inputSize >>>  0) & 0xFF;
    outputArray[5] = (inputSize >>>  8) & 0xFF;
    outputArray[6] = (inputSize >>> 16) & 0xFF;
    outputArray[7] = (inputSize >>> 24) & 0xFF;
    //console.info(
    //    'uBO: [%s] compressed %d KB => %d KB (%s%%) in %s ms',
    //    inputArray.byteLength >> 10,
    //    outputArray.byteLength >> 10,
    //    (outputArray.byteLength / inputArray.byteLength * 100).toFixed(0),
    //    (window.performance.now() - t0).toFixed(1)
    //);
    return outputArray;
};

const decodeValue = function(lz4CodecInstance, inputArray) {
    if ( !lz4CodecInstance ) { return; }
    //let t0 = window.performance.now();
    if (
        inputArray[0] !== 0x18 || inputArray[1] !== 0x4D ||
        inputArray[2] !== 0x22 || inputArray[3] !== 0x04
    ) {
        console.error('decodeValue: invalid input array');
        return;
    }
    const outputSize = 
        (inputArray[4] <<  0) | (inputArray[5] <<  8) |
        (inputArray[6] << 16) | (inputArray[7] << 24);
    const outputArray = lz4CodecInstance.decodeBlock(inputArray, 8, outputSize);
    if ( outputArray instanceof Uint8Array === false ) { return; }
    if ( textDecoder === undefined ) {
        textDecoder = new TextDecoder();
    }
    const s = textDecoder.decode(outputArray);
    //console.info(
    //    'uBO: [%s] decompressed %d KB => %d KB (%s%%) in %s ms',
    //    inputArray.byteLength >>> 10,
    //    outputSize >>> 10,
    //    (inputArray.byteLength / outputSize * 100).toFixed(0),
    //    (window.performance.now() - t0).toFixed(1)
    //);
    return s;
};

const lz4Codec = {
    // Arguments:
    //   dataIn: must be a string
    // Returns:
    //   A Uint8Array, or the input string as is if compression is not
    //   possible.
    encode: async function(dataIn, serialize = undefined) {
        if ( typeof dataIn !== 'string' || dataIn.length < 4096 ) {
            return dataIn;
        }
        ttlManage(1);
        const lz4CodecInstance = await init();
        let dataOut = encodeValue(lz4CodecInstance, dataIn);
        ttlManage(-1);
        if ( serialize instanceof Function ) {
            dataOut = await serialize(dataOut);
        }
        return dataOut || dataIn;
    },
    // Arguments:
    //   dataIn: must be a Uint8Array
    // Returns:
    //   A string, or the input argument as is if decompression is not
    //   possible.
    decode: async function(dataIn, deserialize = undefined) {
        if ( deserialize instanceof Function ) {
            dataIn = await deserialize(dataIn);
        }
        if ( dataIn instanceof Uint8Array === false ) {
            return dataIn;
        }
        ttlManage(1);
        const lz4CodecInstance = await init();
        const dataOut = decodeValue(lz4CodecInstance, dataIn);
        ttlManage(-1);
        return dataOut || dataIn;
    },
    relinquish: function() {
        ttlDelay = 1;
        ttlManage(0);
    },
};

/******************************************************************************/

export default lz4Codec;

/******************************************************************************/

/*******************************************************************************

    lz4-block-codec-any.js
        A wrapper to instantiate a wasm- and/or js-based LZ4 block
        encoder/decoder.
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

const wd = (function() {
    let url = document.currentScript.src;
    let match = /[^\/]+$/.exec(url);
    return match !== null ?
        url.slice(0, match.index) :
        '';
})();

const removeScript = function(script) {
    if ( !script ) { return; }
    if ( script.parentNode === null ) { return; }
    script.parentNode.removeChild(script);
};

const createInstanceWASM = function() {
    if ( context.LZ4BlockWASM instanceof Function ) {
        const instance = new context.LZ4BlockWASM();
        return instance.init().then(ok => ok ? instance : null);
    }
    if ( context.LZ4BlockWASM === null ) {
        return Promise.resolve(null);
    }
    return new Promise(resolve => {
        const script = document.createElement('script');
        script.src = wd + 'lz4-block-codec-wasm.js';
        script.addEventListener('load', ( ) => {
            if ( context.LZ4BlockWASM instanceof Function === false ) {
                context.LZ4BlockWASM = null;
                resolve(null);
                return;
            }
            const instance = new context.LZ4BlockWASM();
            instance.init().then(ok => { resolve(ok ? instance : null); });
        });
        script.addEventListener('error', ( ) => {
            context.LZ4BlockWASM = null;
            resolve(null);
        });
        document.head.appendChild(script);
        removeScript(script);
    });
};

const createInstanceJS = function() {
    if ( context.LZ4BlockJS instanceof Function ) {
        const instance = new context.LZ4BlockJS();
        return instance.init().then(ok => ok ? instance : null);
    }
    if ( context.LZ4BlockJS === null ) {
        return Promise.resolve(null);
    }
    return new Promise(resolve => {
        const script = document.createElement('script');
        script.src = wd + 'lz4-block-codec-js.js';
        script.addEventListener('load', ( ) => {
            if ( context.LZ4BlockJS instanceof Function === false ) {
                context.LZ4BlockJS = null;
                resolve(null);
                return;
            }
            const instance = new context.LZ4BlockJS();
            instance.init().then(ok => { resolve(ok ? instance : null); });
        });
        script.addEventListener('error', ( ) => {
            context.LZ4BlockJS = null;
            resolve(null);
        });
        document.head.appendChild(script);
        removeScript(script);
    });
};

/******************************************************************************/

context.lz4BlockCodec = {
    createInstance: function(flavor) {
        let instantiator;
        if ( flavor === 'wasm' ) {
            instantiator = createInstanceWASM;
        } else if ( flavor === 'js' ) {
            instantiator = createInstanceJS;
        } else {
            instantiator = createInstanceWASM || createInstanceJS;
        }
        return (instantiator)().then(instance => {
            if ( instance ) { return instance; }
            if ( flavor === undefined ) {
                return createInstanceJS();
            }
            return null;
        });
    },
    reset: function() {
        context.LZ4BlockWASM = undefined;
        context.LZ4BlockJS = undefined;
    }
};

/******************************************************************************/

})(this || self);                       // <<<< End of private namespace

/******************************************************************************/

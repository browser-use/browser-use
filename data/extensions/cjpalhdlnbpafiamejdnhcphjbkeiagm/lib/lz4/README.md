## Purpose

The purpose of this library is to implement LZ4 compression/decompression,
as documented at the official LZ4 repository:

https://github.com/lz4/lz4/blob/dev/doc/lz4_Block_format.md

The files in this directory are developed as a separate project at:

https://github.com/gorhill/lz4-wasm

## Files

### `lz4-block-codec-any.js`

The purpose is to instantiate a WebAssembly- or pure javascript-based
LZ4 block codec.

If the chosen implementation is not specified, there will be an attempt to
create a WebAssembly-based instance. If for whatever reason this fails, a
pure javascript-based instance will be created.

The script for either instance are dynamically loaded and only when needed,
such that no resources are wasted by keeping in memory code which won't be
used.
 
### `lz4-block-codec-wasm.js`

This contains the code to instantiate WebAssembly-based LZ4 block codec. Note
that the WebAssembly module is loaded using a `same-origin` fetch, hence
ensuring that no code outside the package is loaded.

### `lz4-block-codec-js.js`

This contains the code to instantiate pure javascript-based LZ4 block codec.

This is used as a fallback implementation should WebAssembly not be available
for whatever reason.

### `lz4-block-codec.wasm`

This is the WebAssembly module, loaded by `lz4-block-codec-wasm.js` using a
`same-origin` fetch.

### `lz4-block-codec.wat`

The WebAssembly source code used to generate the WebAssembly module `lz4-block-codec.wasm`.

    wat2wasm ./lz4-block-codec.wat -o ./lz4-block-codec.wasm
    wasm-opt ./lz4-block-codec.wasm -O4 -o ./lz4-block-codec.wasm

You can get `wat2wasm` at <https://github.com/WebAssembly/wabt>, and `wasm-opt` at <https://github.com/WebAssembly/binaryen>.

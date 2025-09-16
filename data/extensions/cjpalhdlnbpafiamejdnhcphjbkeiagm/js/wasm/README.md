### For code reviewers

All `wasm` files in that directory where created by compiling the
corresponding `wat` file using the command (using `hntrie.wat`/`hntrie.wasm`
as example):

    wat2wasm hntrie.wat -o hntrie.wasm

Assuming:

- The command is executed from within the present directory.

### `wat2wasm` tool

The `wat2wasm` tool can be downloaded from an official WebAssembly project:
<https://github.com/WebAssembly/wabt/releases/tag/1.0.29>

### `wat2wasm` tool online

You can also use the following online `wat2wasm` tool:
<https://webassembly.github.io/wabt/demo/wat2wasm/>.

Just paste the whole content of the `wat` file to compile into the WAT pane.
Click "Download" button to retrieve the resulting `wasm` file.
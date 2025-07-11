# rollup-plugin-off-main-thread

Use Rollup with workers and ES6 modules _today_.

```
$ npm install --save @surma/rollup-plugin-off-main-thread
```

Workers are JavaScript’s version of threads. [Workers are important to use][when workers] as the main thread is already overloaded, especially on slower or older devices.

This plugin takes care of shimming module support in workers and allows you to use `new Worker()`.

OMT is the result of merging loadz0r and workz0r.

## Usage

I set up [a gist] to show a full setup with OMT.

### Config

```js
// rollup.config.js
import OMT from "@surma/rollup-plugin-off-main-thread";

export default {
  input: ["src/main.js"],
  output: {
    dir: "dist",
    // You _must_ use either “amd” or “esm” as your format.
    // But note that only very few browsers have native support for
    // modules in workers.
    format: "amd"
  },
  plugins: [OMT()]
};
```

### Auto bundling

In your project's code use a module-relative path via `new URL` to include a Worker:

```js
const worker = new Worker(new URL("worker.js", import.meta.url), {
  type: "module"
});
```

This will just work.

If required, the plugin also supports plain literal paths:

```js
const worker = new Worker("./worker.js", { type: "module" });
```

However, those are less portable: in Rollup they would result in module-relative
path, but if used directly in the browser, they'll be relative to the document
URL instead.

Hence, they're deprecated and `new URL` pattern is encouraged instead for portability.

### Importing workers as URLs

If your worker constructor doesn't match `workerRegexp` (see options below), you might find it easier to import the worker as a URL. In your project's code:

```js
import workerURL from "omt:./worker.js";
import paintWorkletURL from "omt:./paint-worklet.js";

const worker = new Worker(workerURL, { name: "main-worker" });
CSS.paintWorklet.addModule(paintWorkletURL);
```

`./worker.js` and `./paint-worklet.js` will be added to the output as chunks.

## Options

```js
{
  // ...
  plugins: [OMT(options)];
}
```

- `loader`: A string containing the EJS template for the amd loader. If `undefined`, OMT will use `loader.ejs`.
- `useEval`: Use `fetch()` + `eval()` to load dependencies instead of `<script>` tags and `importScripts()`. _This is not CSP compliant, but is required if you want to use dynamic imports in ServiceWorker_.
- `workerRegexp`: A RegExp to find `new Workers()` calls. The second capture group _must_ capture the provided file name without the quotes.
- `amdFunctionName`: Function name to use instead of AMD’s `define`.
- `prependLoader`: A function that determines whether the loader code should be prepended to a certain chunk. Should return true if the load is suppsoed to be prepended.
- `urlLoaderScheme`: Scheme to use when importing workers as URLs. If `undefined`, OMT will use `"omt"`.

[when workers]: https://dassur.ma/things/when-workers
[a gist]: https://gist.github.com/surma/a02db7b53eb3e7870bf539b906ff6ff6

---

License Apache-2.0

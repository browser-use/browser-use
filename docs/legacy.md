# Previous Browser Use versions

The migration removes the old Python planner, browser stack, model wrappers, and Rust beta.
It retains their historical source through Git tags.

Applications that require the previous API can keep an exact package version:

```sh
uv add 'browser-use==0.13.13'
```

Use a separate environment for each major version.
Provider integrations also need the exact SDK versions that their application tested.
The new package retains OpenAI and Anthropic integrations through Pi browser helpers.
It does not install a second legacy agent.

[Previous source](https://github.com/browser-use/browser-use/tree/3df5806a0d097a1546d92c49bcf1b28c9972c3bd)

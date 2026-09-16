# README artwork, diagram, and demo sources

## Header artwork

The orange key-shaped bridge is an existing painting from the
[Browser Use website](https://browser-use.com/lander/plates/browsers-8dd60aa0.jpg).
The README displays the original image at a maximum width of 720 pixels and links
it to the website. It is hosted on the website, so cloning the repository does
not download the artwork.

## Product diagram

`which-product-light.svg` and `which-product-dark.svg` are editable SVGs.
They are adapted from [the SDK product diagram](https://github.com/browser-use/sdk/blob/bfc0140801caf6a4c518c811f03674135efbd4aa/docs/cloud/images/which-product-light.svg),
introduced in [SDK PR #241](https://github.com/browser-use/sdk/pull/241).

The README version shows three paths:

- Path 1, fully hosted cloud: our hosted agent → Browser Use CLI → cloud browser.
- Path 2, CLI: your existing agent → Browser Use CLI → local or cloud browser.
- Path 3, Python library: the open source Browser Use agent → local or cloud browser.
  The agent and its Python library are one block, with no CLI step.

Keep the light and dark SVGs structurally identical when changing the diagram.
The SDK source remains the reference for the hosted stack; this README adds the
Python-library path and omits the Playwright branch.

## Benchmark plot

`../hard_benchmark_v2.jpg` is a lossless crop of the
[original plot](https://github.com/browser-use/browser-use/blob/f5f58c6ef4e6b95728f8b304015bb29f00bddd69/static/hard_benchmark_v2.jpg).
Only the top 80 pixels containing the title were removed; all retained pixels
are unchanged. The title appears as a README heading instead.

## Driving-test demo

The inline GIF is converted from [Johannes Dittrich's public driving-test video](https://x.com/mathisdittrich/status/2078619618265141560).
It preserves the full 20.4-second recording at 960×540, 10 frames per second,
with an infinite loop. The source recording already obscures the contact fields.
No demo footage was generated.

The GIF is hosted as a [GitHub attachment](https://github.com/user-attachments/assets/135885e8-1141-4e10-b719-bf690ae7d260)
so cloning the repository does not download the animation.

# README artwork, diagram, and demo sources

## Header artwork

The orange key-shaped bridge is an existing painting from the
[Browser Use website](https://browser-use.com/lander/plates/browsers-8dd60aa0.jpg).
The README displays the original image at a maximum width of 720 pixels and links
it to the website. It is hosted on the website, so cloning the repository does
not download the artwork.

## Product diagram

`which-product-{light,dark}{,-mobile}.svg` are copied from the
[SDK docs](https://github.com/browser-use/sdk/tree/c63645d081ed14a5d2e785033f6b1afeb300405b/docs/cloud/images),
where `scripts/diagrams/` generates them (`task docs:diagrams`). Regenerate there
and copy the four files here; phones under 600 px get the mobile variants.

The figure shows the README's three paths: the hosted V4 agent drives a cloud
browser, while the Browser Use CLI and the Python library drive a cloud or local
browser.

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

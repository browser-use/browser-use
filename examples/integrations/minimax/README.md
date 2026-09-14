# MiniMax image generation

This example registers MiniMax text-to-image generation as a Browser Use tool. The agent gathers visual requirements in the browser, calls the tool, and saves the generated image locally.

## Setup

Install the repository dependencies and export both API keys:

```bash
uv sync
export BROWSER_USE_API_KEY='your-browser-use-api-key'
export MINIMAX_API_KEY='your-minimax-api-key'
```

The example uses the global API by default. To use the API in China, set the image API base URL:

```bash
export MINIMAX_IMAGE_BASE_URL='https://api.minimaxi.com/v1'
```

`MINIMAX_IMAGE_BASE_URL` must be an API base URL ending in `/v1`; the example appends `/image_generation` when it sends a request.

## Run

From the repository root:

```bash
uv run python examples/integrations/minimax/image_generation.py
```

Generated images are written to `examples/integrations/minimax/output/`.

See the [global image generation guide](https://platform.minimax.io/docs/guides/image-generation) or the [China image generation guide](https://platform.minimaxi.com/docs/guides/image-generation) for API details.

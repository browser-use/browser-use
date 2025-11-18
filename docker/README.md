# Docker Setup for Browser-Use

This directory contains the optimized Docker build system for browser-use, achieving < 30 second builds.

## Quick Start

```bash
# Build base images (only needed once or when dependencies change)
./docker/build-base-images.sh

# Build browser-use
docker build -f Dockerfile.fast -t browseruse .

# Or use the standard Dockerfile (slower but self-contained)
docker build -t browseruse .
```

## Files

- `Dockerfile` - Standard self-contained build (~2 min)
- `Dockerfile.fast` - Fast build using pre-built base images (~30 sec)
- `docker/` - Base image definitions and build script
  - `base-images/system/` - Python + minimal system deps
  - `base-images/chromium/` - Adds Chromium browser
  - `base-images/python-deps/` - Adds Python dependencies
  - `build-base-images.sh` - Script to build all base images

## Performance

| Build Type | Time |
|------------|------|
| Standard Dockerfile | ~2 minutes |
| Fast build (with base images) | ~30 seconds |
| Rebuild after code change | ~16 seconds |

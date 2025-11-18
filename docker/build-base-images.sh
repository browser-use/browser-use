#!/bin/bash
# Build script for browser-use base images
set -euo pipefail

# Configuration
REGISTRY="${DOCKER_REGISTRY:-browseruse}"
PLATFORMS="${PLATFORMS:-linux/amd64}"
PUSH="${PUSH:-false}"

# Build function
build_image() {
    local name=$1
    local dockerfile=$2
    local build_args="${3:-}"
    
    echo "[INFO] Building ${name}..."
    
    local build_cmd="docker build"
    local tag_args="-t ${REGISTRY}/${name}:latest -t ${REGISTRY}/${name}:$(date +%Y%m%d)"
    
    # Use buildx for multi-platform or push
    if [[ "$PLATFORMS" == *","* ]] || [ "$PUSH" = "true" ]; then
        build_cmd="docker buildx build --platform=$PLATFORMS"
        [ "$PUSH" = "true" ] && build_cmd="$build_cmd --push" || build_cmd="$build_cmd"
    fi
    
    $build_cmd $tag_args $build_args -f $dockerfile ../../..
}

# Main
cd "$(dirname "$0")"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --push) PUSH=true; shift ;;
        --registry) REGISTRY="$2"; shift 2 ;;
        --platforms) PLATFORMS="$2"; shift 2 ;;
        --help)
            echo "Usage: $0 [--push] [--registry REG] [--platforms P]"
            exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Create buildx builder if needed
if [[ "$PLATFORMS" == *","* ]] || [ "$PUSH" = "true" ]; then
    docker buildx inspect browseruse-builder >/dev/null 2>&1 || \
        docker buildx create --name browseruse-builder --use
    docker buildx use browseruse-builder
fi

# Build images in order
build_image "base-system" "base-images/system/Dockerfile"
build_image "base-chromium" "base-images/chromium/Dockerfile" "--build-arg BASE_TAG=latest"
build_image "base-python-deps" "base-images/python-deps/Dockerfile" "--build-arg BASE_TAG=latest"

echo "[INFO] Build complete. Use: FROM ${REGISTRY}/base-python-deps:latest"

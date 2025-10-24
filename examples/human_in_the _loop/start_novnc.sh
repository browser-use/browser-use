#!/usr/bin/env bash

# Script to start a VNC server with noVNC web interface for remote desktop access
# This is commonly used for headless environments or Docker containers

# Exit on any error, undefined variables, and pipe failures
set -euo pipefail

# Configuration variables with default values
# These can be overridden by setting environment variables

DISPLAY_NUM=${VNC_DISPLAY:-100}             # X11 display number (default: 100)
RESOLUTION=${VNC_RESOLUTION:-1280x800x24}   # Screen resolution and color depth (default: 1280x800x24)
VNC_PORT=${VNC_PORT:-5900}                  # VNC server port (default: 5900)
NOVNC_PORT=${NOVNC_PORT:-3001}              # noVNC web interface port (default: 3001)

# Start Xvfb (X Virtual Framebuffer) - a virtual X server
# This creates a virtual display that can be accessed remotely
Xvfb :${DISPLAY_NUM} -screen 0 ${RESOLUTION} -nolisten tcp -noreset &
XVFB_PID=$!  # Store the process ID for cleanup later

# Wait for Xvfb to be ready (up to 4 seconds with 0.1s intervals)
# xdpyinfo checks if the X server is responding

for _ in {1..40}; do
  if xdpyinfo >/dev/null 2>&1; then break; fi
  sleep 0.1
done

# Start x11vnc server to share the virtual display
# -display: specify which X display to share
# -forever: keep running after client disconnects
# -shared: allow multiple clients to connect
# -nopw: no password required (for development/testing)
# -rfbport: VNC server port
# -listen 0.0.0.0: accept connections from any IP
# -ncache: enable pixel caching for better performance

x11vnc -display :${DISPLAY_NUM} -forever -shared -nopw \
  -rfbport ${VNC_PORT} -listen 0.0.0.0 -ncache 10 -ncache_cr &
VNC_PID=$!  # Store the process ID for cleanup later

# Start websockify to provide web-based VNC access via noVNC
# This creates a WebSocket proxy that converts VNC protocol to WebSocket
# --web: serve the noVNC web client from this directory

websockify --web=/usr/share/novnc ${NOVNC_PORT} localhost:${VNC_PORT} &
WS_PID=$!  # Store the process ID for cleanup later

# Cleanup function to properly terminate all processes

cleanup() {
  # Send TERM signal to all processes (graceful shutdown)
  kill -TERM ${WS_PID} ${VNC_PID} ${XVFB_PID} 2>/dev/null || true
  # Wait for processes to finish gracefully
  wait ${WS_PID} ${VNC_PID} ${XVFB_PID} 2>/dev/null || true
  # Remove the PID file
  rm -f /tmp/novnc.pids
}

# Set up signal handlers to ensure cleanup on script termination
# EXIT: normal script exit
# TERM: termination signal
# INT: interrupt signal (Ctrl+C)
trap cleanup EXIT TERM INT

# Save process IDs to a file for external monitoring/cleanup
echo "$XVFB_PID $VNC_PID $WS_PID" > /tmp/novnc.pids

# Wait for all background processes to complete
# Keeps the script running until one of the processes exits
wait $XVFB_PID $VNC_PID $WS_PID

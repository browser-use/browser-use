# Human-in-the-Loop Browser Use Example

This example demonstrates how to integrate human interaction with browser-use by providing a web-based VNC interface that allows users to manually control the browser when needed.

## ⚠️ Linux-Only Example

**This example only works on Linux machines** because it relies on several Linux-specific packages and X11 display system components that are not available on macOS or Windows.

## Required Linux Packages

The following packages must be installed on your Linux machine for this example to work:

```bash
# Install noVNC stack: Xvfb, x11vnc, fluxbox, novnc, websockify
apt-get update && apt-get install -y --no-install-recommends \
    xvfb x11vnc fluxbox novnc websockify xdotool \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
```

### Package Explanations

- **`xvfb`**: X Virtual Framebuffer - creates a virtual X11 display server
- **`x11vnc`**: VNC server that shares the X11 display over the network
- **`fluxbox`**: Lightweight window manager for the virtual display
- **`novnc`**: Web-based VNC client that runs in browsers
- **`websockify`**: WebSocket proxy that converts VNC protocol to WebSocket
- **`xdotool`**: Command-line X11 automation tool

## How It Works

1. **Virtual Display**: `Xvfb` creates a virtual X11 display (`:100`)
2. **VNC Server**: `x11vnc` shares this display over VNC protocol
3. **Web Interface**: `websockify` + `novnc` provide a web-based VNC client
4. **Browser Control**: The browser runs in the virtual display, accessible via web browser
5. **Human Handoff**: When the agent needs human input, it provides a URL to the VNC interface

The agent will automatically launch the VNC server and provide a URL where you can manually control the browser when needed.

## Why Linux-Only?

- **X11 System**: Requires Linux's X11 display system for virtual displays
- **Package Dependencies**: The VNC stack packages are Linux-specific
- **Process Management**: Uses Linux-specific process management and signal handling
- **File System**: Relies on Linux file system paths and permissions

For cross-platform alternatives, consider using cloud-based solutions or platform-specific remote desktop tools.

#!/bin/bash
# Browser-Use MCP Server Installation Helper
# 
# This script helps you add the Browser-Use MCP server to Claude Code

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCP_SERVER_SCRIPT="$SCRIPT_DIR/mcp-server"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🔧 Browser-Use MCP Server Installation${NC}"
echo "=================================================="
echo

# Check if mcp-server script exists
if [ ! -f "$MCP_SERVER_SCRIPT" ]; then
    echo -e "${RED}❌ Error: MCP server script not found at $MCP_SERVER_SCRIPT${NC}"
    exit 1
fi

# Make sure it's executable
chmod +x "$MCP_SERVER_SCRIPT"

echo -e "${GREEN}✅ MCP server script found and ready${NC}"
echo

# Check if claude command is available
if ! command -v claude &> /dev/null; then
    echo -e "${YELLOW}⚠️  Warning: 'claude' command not found${NC}"
    echo "Make sure Claude Code is installed and the 'claude' command is in your PATH"
    echo
fi

# Provide installation commands
echo -e "${BLUE}📋 Installation Commands${NC}"
echo "========================"
echo
echo "To add the MCP server to Claude Code, run one of these commands:"
echo
echo -e "${GREEN}# Basic installation (project scope):${NC}"
echo "claude mcp add browser-use $MCP_SERVER_SCRIPT"
echo
echo -e "${GREEN}# User-wide installation:${NC}"
echo "claude mcp add --scope user browser-use $MCP_SERVER_SCRIPT"
echo
echo -e "${GREEN}# Global installation:${NC}"
echo "claude mcp add --scope global browser-use $MCP_SERVER_SCRIPT"
echo

echo -e "${BLUE}🛠️  Available Tools After Installation${NC}"
echo "======================================="
echo "• browser_navigate(url, wait_until, timeout)"
echo "• browser_click(selector, timeout)"
echo "• browser_type(selector, text, timeout)"
echo "• browser_screenshot(timeout)"
echo "• browser_scroll(direction, amount, timeout)"
echo "• browser_status(timeout)"
echo "• browser_wait_for_element(selector, timeout)"
echo "• browser_server_status()"
echo "• browser_server_start(port, debug)"
echo

echo -e "${BLUE}🚀 Quick Test${NC}"
echo "============="
echo "After installation, you can test by asking Claude Code:"
echo "\"Use the browser_server_start tool to start the browser server, then navigate to https://example.com and take a screenshot\""
echo

echo -e "${YELLOW}💡 Note: The MCP server will automatically start the Browser Action Server when needed${NC}"
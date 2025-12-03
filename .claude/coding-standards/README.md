# Coding Standards

This directory contains language-specific coding standards and conventions that all code implementations must follow.

## Purpose

These standards ensure consistency, maintainability, and quality across the codebase. The coder agent will reference these files when implementing tasks.

## Structure

### Coding Standards
- `general.md` - Language-agnostic coding principles
- `python.md` - Python-specific standards
- `typescript.md` - TypeScript-specific standards
- `golang.md` - Go-specific standards
- `dotnetcore.md` - .NET Core/C#-specific standards

### Testing Standards
- `testing-standards.md` - Standards for writing and maintaining tests

## Usage

### For Coder Agents
The coder agent will:
1. First check byterover MCP server (if available) for project-specific rules
2. Then read the appropriate language-specific standards file
3. Apply both sets of rules during implementation

### For Tester Agents
The tester agents (test-creator, backend-tester, frontend-tester) will:
1. First check byterover MCP server (if available) for testing patterns
2. Then read `testing-standards.md` for testing best practices
3. Apply testing standards when writing or validating tests

## Adding New Languages

Create a new `{language}.md` file following the template structure used in existing files.

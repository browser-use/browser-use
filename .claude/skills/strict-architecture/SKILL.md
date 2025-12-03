---
name: strict-architecture
description: Enforces universal strict governance rules (500 lines, 5 funcs, 4 args) and interface-first I/O for Python, Golang, and .NET.
---

# Strict Architecture Governance

These rules apply to ALL code in this project, regardless of language.

## 1. Universal Limits (Non-Negotiable)
These constraints apply to every source file:
- **MAX_LINES**: 500 lines per file. (Split file if exceeded)
- **MAX_FUNCS**: 5 public functions/methods per class/struct.
- **MAX_ARGS**: 4 arguments per function/constructor.
- **NO_DEFAULTS**: No default argument values allowed.
- **NO_ENV_VARS**: No reading environment variables inside constructors or methods (pass values in).

## 2. Implementation Patterns by Language

### 🐍 Python Implementation
- **Interfaces**: Use `typing.Protocol` for all dependencies.
  ```python
  class IClient(Protocol):
      def fetch(self) -> dict: ...
  ```
- **Config**: Use `@dataclass` for configuration objects if args > 4.
- **Env Block**: Reject `os.environ` or `os.getenv` anywhere except `main.py`.

### 🐹 Golang Implementation
- **Interfaces**: Define `type Service interface` for all dependencies.
- **Config**: Use strict structs for config.
- **Env Block**: Reject `os.Getenv` anywhere except `main.go`.
- **Forbidden**: Do not use struct pointers for dependencies; use interfaces.

### 🔷 .NET / C# Implementation
- **Interfaces**: Use `IInterface` prefix.
- **Config**: Use `IOptions<T>` pattern or simple POCO config objects.
- **Env Block**: Reject `Environment.GetEnvironmentVariable` anywhere except `Program.cs`.

## 3. Enforcement Checklist
Before saving any file, verify:
1. [ ] Is the file < 500 lines?
2. [ ] Does the constructor have dependencies passed as Interfaces?
3. [ ] Are there 0 calls to env var readers?
4. [ ] Are there 0 default arguments?

# General Coding Standards

Language-agnostic principles that apply to all code.

## Mandatory Rules
- **No default argument values** - Be explicit about all inputs
- **No global mutable state** - Pass values as arguments instead
- **No side effects** - Functions should be pure
- **No silent failures** - Handle errors explicitly
- **No hardcoded values** - Use constants or configuration
- **Reuse existing service classes** - Before creating a new service class always check if there is an existing one that can be reused

## Code Organization

### File Structure
- One primary class/module per file
- File names should clearly indicate their purpose
- Group related functionality together, for example:
  - ./src/clients: any client implementations that perform network or disk I/O including their interfaces
  - ./src/models: any data structures that are used to represent data
  - ./src/repositories: any data access objects or repositories
  - ./src/services: any business logic or application services
- Keep files focused and cohesive

### File Size Limits
- **Maximum 500 lines per file**
- When a file exceeds 500 lines, extract the largest function into its own class and file
- Maintain single responsibility principle - oversized files often indicate too many responsibilities
- Apply this limit to all backend code (services, repositories, controllers, etc.)

### Naming Conventions
- Use descriptive, meaningful names
- Avoid abbreviations unless widely understood
- Be consistent with naming patterns across the codebase

## Function Design

### Arguments and Parameters
- **No default argument values** - Be explicit about all inputs
- **Pass values as arguments** - Don't read environment variables or global state directly inside functions
- **Dependency injection** - Pass dependencies as parameters rather than accessing them globally
- Keep parameter lists manageable (consider objects/structs for many parameters)

### Function Responsibilities
- Single Responsibility Principle - each function does one thing well
- Pure functions preferred - same inputs produce same outputs
- Minimize side effects
- Explicit error handling

## Configuration Management

### Environment Variables
- Read environment variables at application startup/initialization
- Pass configuration values down through function arguments
- Never read `process.env`, `os.getenv()`, or equivalent directly in business logic
- Use configuration objects/classes to encapsulate settings

### Example Pattern
```
// ❌ BAD - Reading env var inside function
function connectDatabase() {
  const host = process.env.DB_HOST;
  return connect(host);
}

// ✅ GOOD - Configuration passed as argument
function connectDatabase(config) {
  return connect(config.dbHost);
}
```

## Error Handling

- Explicit error types/classes
- No silent failures
- Propagate errors appropriately
- Log errors with context
- Don't catch errors you can't handle

## Testing Considerations

- Write the test first, then the code
- Avoid hard dependencies on external systems
- Use interfaces/protocols for dependencies
- Make side effects explicit and controllable
- **Assert entire JSON responses** - When testing endpoints, assert the complete JSON response object matches expected output rather than checking individual properties. This ensures no unexpected fields are present.

## Documentation

- Document public APIs
- Explain "why" not just "what"
- Keep comments up to date
- Use type annotations/hints where available

## Code Quality

- Prefer readability over cleverness
- Avoid premature optimization
- Follow language idioms and conventions
- Use linting and formatting tools
- Keep functions and classes small and focused

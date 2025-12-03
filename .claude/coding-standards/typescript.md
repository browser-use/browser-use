# TypeScript Coding Standards

TypeScript-specific coding standards and conventions.

## File Organization

### Module Structure
- **One class per file** (unless closely related helper classes)
- File name should match the class name in PascalCase or kebab-case
- Barrel exports via index.ts files for clean imports
- Organize by feature/domain, not by type

### Example
```typescript
// UserRepository.ts or user-repository.ts - contains UserRepository class
// DatabaseConnection.ts or database-connection.ts - contains DatabaseConnection class
```

## Class Design

### Class Structure
```typescript
export class UserRepository {
  private readonly maxRetries = 3;
  
  constructor(
    private readonly dbConnection: DatabaseConnection,
    private readonly logger: Logger
  ) {}
  
  public async findUser(userId: string): Promise<User> {
    // Implementation
  }
  
  private validateUserId(userId: string): void {
    // Private helper
  }
}
```

### Key Rules
- One primary class per file
- Dependencies injected via constructor
- Use `readonly` for immutable properties
- No default parameter values
- Explicit access modifiers (public, private, protected)
- Use interfaces for contracts

## Function Design

### No Default Arguments
```typescript
// ❌ BAD - Default arguments
function createUser(name: string, email: string, role: string = "user"): User {
  // ...
}

// ✅ GOOD - Explicit arguments
function createUser(name: string, email: string, role: string): User {
  // ...
}
```

### No Environment Variable Access
```typescript
// ❌ BAD - Reading env vars in function
function connectToDatabase(): DatabaseConnection {
  const host = process.env.DB_HOST;
  const port = process.env.DB_PORT;
  return connect(host, port);
}

// ✅ GOOD - Configuration passed as arguments
function connectToDatabase(config: DatabaseConfig): DatabaseConnection {
  return connect(config.host, config.port);
}

// Configuration read at startup
interface DatabaseConfig {
  host: string;
  port: number;
}

const config: DatabaseConfig = {
  host: process.env.DB_HOST!,
  port: parseInt(process.env.DB_PORT!, 10)
};

const db = connectToDatabase(config);
```

### Type Annotations
```typescript
// Always use explicit types
function processUsers(
  users: User[], 
  filterActive: boolean
): User[] {
  // Implementation
}

// Use return type annotations
async function fetchUser(id: string): Promise<User> {
  // Implementation
}

// Avoid 'any' - use 'unknown' if type is truly unknown
function parseData(data: unknown): ParsedData {
  // Type guard and parse
}
```

## Interfaces and Types

### Prefer Interfaces for Objects
```typescript
// ✅ GOOD - Interface for object shapes
interface User {
  id: string;
  name: string;
  email: string;
}

interface UserRepository {
  findById(id: string): Promise<User>;
  save(user: User): Promise<void>;
}
```

### Use Type for Unions and Utilities
```typescript
// ✅ GOOD - Type for unions
type Status = "pending" | "active" | "inactive";

type Result<T> = Success<T> | Failure;

// Utility types
type ReadonlyUser = Readonly<User>;
type PartialUser = Partial<User>;
```

## Error Handling

### Custom Error Classes
```typescript
export class UserNotFoundError extends Error {
  constructor(userId: string) {
    super(`User ${userId} not found`);
    this.name = "UserNotFoundError";
  }
}

export class ValidationError extends Error {
  constructor(
    message: string,
    public readonly field: string
  ) {
    super(message);
    this.name = "ValidationError";
  }
}
```

### Error Propagation
```typescript
// ✅ GOOD - Let errors propagate
async function getUser(userId: string): Promise<User> {
  const user = await repository.findById(userId);
  if (!user) {
    throw new UserNotFoundError(userId);
  }
  return user;
}

// ❌ BAD - Silent failure
async function getUser(userId: string): Promise<User | null> {
  try {
    return await repository.findById(userId);
  } catch (error) {
    return null; // Don't hide errors!
  }
}
```

## Configuration Management

### Startup Configuration
```typescript
// config.ts
interface DatabaseConfig {
  host: string;
  port: number;
  username: string;
  password: string;
}

export class Config {
  public readonly database: DatabaseConfig;
  
  private constructor(database: DatabaseConfig) {
    this.database = database;
  }
  
  public static fromEnv(): Config {
    return new Config({
      host: process.env.DB_HOST!,
      port: parseInt(process.env.DB_PORT!, 10),
      username: process.env.DB_USER!,
      password: process.env.DB_PASSWORD!
    });
  }
}

// main.ts
const config = Config.fromEnv();
const repository = new UserRepository(config.database);
```

## Dependency Injection

### Constructor Injection
```typescript
// ✅ GOOD - Dependencies injected
export class UserService {
  constructor(
    private readonly repository: UserRepository,
    private readonly emailSender: EmailSender,
    private readonly logger: Logger
  ) {}
  
  public async registerUser(email: string, name: string): Promise<User> {
    const user = await this.repository.create(email, name);
    await this.emailSender.sendWelcome(user);
    this.logger.info(`User registered: ${user.id}`);
    return user;
  }
}
```

## Async/Await

### Always Use Async/Await
```typescript
// ✅ GOOD - Async/await
async function fetchUserData(userId: string): Promise<UserData> {
  const user = await userRepository.findById(userId);
  const orders = await orderRepository.findByUserId(userId);
  return { user, orders };
}

// ❌ BAD - Promise chains
function fetchUserData(userId: string): Promise<UserData> {
  return userRepository.findById(userId)
    .then(user => orderRepository.findByUserId(userId)
      .then(orders => ({ user, orders })));
}
```

## Testing

### Testable Design
```typescript
// ✅ GOOD - Easy to test with dependency injection
export class UserService {
  constructor(
    private readonly repository: UserRepository,
    private readonly emailSender: EmailSender
  ) {}
  
  public async registerUser(email: string, name: string): Promise<User> {
    const user = await this.repository.create(email, name);
    await this.emailSender.sendWelcome(user);
    return user;
  }
}

// Test with mocks
describe("UserService", () => {
  it("should register user and send welcome email", async () => {
    const mockRepo = createMock<UserRepository>();
    const mockSender = createMock<EmailSender>();
    const service = new UserService(mockRepo, mockSender);
    // ... test logic
  });
});
```

## Code Style

### Formatting
- Use Prettier or similar formatter
- Line length: 80-100 characters
- 2 spaces for indentation
- Semicolons required
- Single quotes for strings

### Naming
- `camelCase` for variables, functions, methods
- `PascalCase` for classes, interfaces, types, enums
- `UPPER_SNAKE_CASE` for constants
- `_leadingUnderscore` for private fields (optional with private keyword)

### JSDoc Comments
```typescript
/**
 * Calculate total price including tax.
 * 
 * @param items - List of items with price property
 * @param taxRate - Tax rate as decimal (e.g., 0.08 for 8%)
 * @returns Total price including tax
 * @throws {ValidationError} If tax rate is negative
 */
function calculateTotal(items: Item[], taxRate: number): number {
  // Implementation
}
```

## Imports

### Organization
```typescript
// Node built-ins
import { readFile } from "fs/promises";
import * as path from "path";

// Third-party
import express from "express";
import { Logger } from "winston";

// Local - absolute imports
import { User } from "@/models/User";
import { UserRepository } from "@/repositories/UserRepository";

// Local - relative imports (if not using path aliases)
import { User } from "../models/User";
import { UserRepository } from "../repositories/UserRepository";
```

### Avoid
- `import * as` unless necessary
- Circular dependencies
- Side-effect imports (unless intentional)

## Enums vs Union Types

### Prefer Union Types
```typescript
// ✅ GOOD - Union type (more flexible)
type Status = "pending" | "active" | "inactive";

// Use enums only when you need reverse mapping or namespacing
enum HttpStatus {
  OK = 200,
  NotFound = 404,
  ServerError = 500
}
```

## Null Safety

### Strict Null Checks
```typescript
// Always enable strictNullChecks in tsconfig.json

// ✅ GOOD - Explicit null handling
function findUser(id: string): User | null {
  // ...
}

const user = findUser("123");
if (user !== null) {
  console.log(user.name); // Safe
}

// Use optional chaining
const userName = user?.name;

// Use nullish coalescing
const displayName = user?.name ?? "Anonymous";

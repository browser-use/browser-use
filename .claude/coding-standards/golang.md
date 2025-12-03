# Go Coding Standards

Go-specific coding standards and conventions.

## File Organization

### Package Structure
- **One primary type per file** (unless closely related types)
- File name should describe the primary type/functionality in snake_case
- Group related functionality in the same package
- Keep packages focused and cohesive

### Example
```go
// user_repository.go - contains UserRepository type
// database_connection.go - contains DatabaseConnection type
```

## Type Design

### Struct Structure
```go
// UserRepository handles user data operations
type UserRepository struct {
    db     *sql.DB
    logger Logger
}

// NewUserRepository creates a new UserRepository with dependencies
func NewUserRepository(db *sql.DB, logger Logger) *UserRepository {
    return &UserRepository{
        db:     db,
        logger: logger,
    }
}

// FindUser retrieves a user by ID
func (r *UserRepository) FindUser(ctx context.Context, userID string) (*User, error) {
    // Implementation
}

// validateUserID is a private helper method
func (r *UserRepository) validateUserID(userID string) error {
    // Implementation
}
```

### Key Rules
- One primary type per file
- Constructor functions (New*) for dependency injection
- No default parameter values (Go doesn't support them)
- Exported names start with uppercase
- Unexported names start with lowercase
- Use interfaces for contracts

## Function Design

### No Default Arguments
```go
// Go doesn't support default arguments, so this is enforced by the language

// ✅ GOOD - All parameters explicit
func CreateUser(name, email, role string) (*User, error) {
    // Implementation
}

// If you need optional parameters, use functional options pattern
type UserOption func(*User)

func WithRole(role string) UserOption {
    return func(u *User) {
        u.Role = role
    }
}

func CreateUser(name, email string, opts ...UserOption) (*User, error) {
    user := &User{Name: name, Email: email}
    for _, opt := range opts {
        opt(user)
    }
    return user, nil
}
```

### No Environment Variable Access
```go
// ❌ BAD - Reading env vars in function
func ConnectToDatabase() (*sql.DB, error) {
    host := os.Getenv("DB_HOST")
    port := os.Getenv("DB_PORT")
    return connect(host, port)
}

// ✅ GOOD - Configuration passed as arguments
func ConnectToDatabase(config DatabaseConfig) (*sql.DB, error) {
    return connect(config.Host, config.Port)
}

// Configuration read at startup
type DatabaseConfig struct {
    Host     string
    Port     int
    Username string
    Password string
}

func LoadConfig() DatabaseConfig {
    return DatabaseConfig{
        Host:     os.Getenv("DB_HOST"),
        Port:     mustParseInt(os.Getenv("DB_PORT")),
        Username: os.Getenv("DB_USER"),
        Password: os.Getenv("DB_PASSWORD"),
    }
}

// In main
config := LoadConfig()
db, err := ConnectToDatabase(config)
```

### Context as First Parameter
```go
// ✅ GOOD - Context always first parameter
func (r *UserRepository) FindUser(ctx context.Context, userID string) (*User, error) {
    // Implementation
}

func ProcessUsers(ctx context.Context, users []User, filterActive bool) ([]User, error) {
    // Implementation
}
```

## Error Handling

### Custom Error Types
```go
// Sentinel errors
var (
    ErrUserNotFound = errors.New("user not found")
    ErrInvalidInput = errors.New("invalid input")
)

// Custom error types
type ValidationError struct {
    Field   string
    Message string
}

func (e *ValidationError) Error() string {
    return fmt.Sprintf("validation error on field %s: %s", e.Field, e.Message)
}

// Error wrapping
func (r *UserRepository) FindUser(ctx context.Context, userID string) (*User, error) {
    user, err := r.db.QueryUser(ctx, userID)
    if err != nil {
        return nil, fmt.Errorf("failed to find user %s: %w", userID, err)
    }
    return user, nil
}
```

### Error Propagation
```go
// ✅ GOOD - Propagate errors with context
func GetUser(ctx context.Context, repo *UserRepository, userID string) (*User, error) {
    user, err := repo.FindUser(ctx, userID)
    if err != nil {
        return nil, fmt.Errorf("get user: %w", err)
    }
    return user, nil
}

// ❌ BAD - Silent failure
func GetUser(ctx context.Context, repo *UserRepository, userID string) *User {
    user, err := repo.FindUser(ctx, userID)
    if err != nil {
        return nil // Don't hide errors!
    }
    return user
}
```

## Interfaces

### Small, Focused Interfaces
```go
// ✅ GOOD - Small, focused interfaces
type UserFinder interface {
    FindUser(ctx context.Context, userID string) (*User, error)
}

type UserSaver interface {
    SaveUser(ctx context.Context, user *User) error
}

// Compose interfaces when needed
type UserRepository interface {
    UserFinder
    UserSaver
}
```

### Accept Interfaces, Return Structs
```go
// ✅ GOOD - Accept interface, return concrete type
func NewUserService(repo UserRepository, sender EmailSender) *UserService {
    return &UserService{
        repo:   repo,
        sender: sender,
    }
}

// ❌ BAD - Returning interface unnecessarily
func NewUserService(repo UserRepository, sender EmailSender) UserService {
    return &userService{
        repo:   repo,
        sender: sender,
    }
}
```

## Configuration Management

### Startup Configuration
```go
// config.go
type Config struct {
    Database DatabaseConfig
    Server   ServerConfig
}

type DatabaseConfig struct {
    Host     string
    Port     int
    Username string
    Password string
}

type ServerConfig struct {
    Port         int
    ReadTimeout  time.Duration
    WriteTimeout time.Duration
}

func LoadConfig() (*Config, error) {
    return &Config{
        Database: DatabaseConfig{
            Host:     getEnv("DB_HOST", "localhost"),
            Port:     getEnvInt("DB_PORT", 5432),
            Username: os.Getenv("DB_USER"),
            Password: os.Getenv("DB_PASSWORD"),
        },
        Server: ServerConfig{
            Port:         getEnvInt("SERVER_PORT", 8080),
            ReadTimeout:  getEnvDuration("READ_TIMEOUT", 10*time.Second),
            WriteTimeout: getEnvDuration("WRITE_TIMEOUT", 10*time.Second),
        },
    }, nil
}

func getEnv(key, defaultValue string) string {
    if value := os.Getenv(key); value != "" {
        return value
    }
    return defaultValue
}
```

## Dependency Injection

### Constructor Functions
```go
// ✅ GOOD - Dependencies injected via constructor
type UserService struct {
    repo   UserRepository
    sender EmailSender
    logger Logger
}

func NewUserService(repo UserRepository, sender EmailSender, logger Logger) *UserService {
    return &UserService{
        repo:   repo,
        sender: sender,
        logger: logger,
    }
}

func (s *UserService) RegisterUser(ctx context.Context, email, name string) (*User, error) {
    user, err := s.repo.CreateUser(ctx, email, name)
    if err != nil {
        return nil, fmt.Errorf("create user: %w", err)
    }
    
    if err := s.sender.SendWelcome(ctx, user); err != nil {
        s.logger.Error("failed to send welcome email", "error", err)
    }
    
    return user, nil
}
```

## Concurrency

### Use Context for Cancellation
```go
// ✅ GOOD - Respect context cancellation
func (r *UserRepository) FindUsers(ctx context.Context, filter UserFilter) ([]User, error) {
    select {
    case <-ctx.Done():
        return nil, ctx.Err()
    default:
    }
    
    // Query implementation
}
```

### Goroutine Management
```go
// ✅ GOOD - Wait for goroutines to complete
func ProcessUsers(ctx context.Context, users []User) error {
    var wg sync.WaitGroup
    errCh := make(chan error, len(users))
    
    for _, user := range users {
        wg.Add(1)
        go func(u User) {
            defer wg.Done()
            if err := processUser(ctx, u); err != nil {
                errCh <- err
            }
        }(user)
    }
    
    wg.Wait()
    close(errCh)
    
    // Check for errors
    for err := range errCh {
        if err != nil {
            return err
        }
    }
    
    return nil
}
```

## Testing

### Table-Driven Tests
```go
func TestCreateUser(t *testing.T) {
    tests := []struct {
        name    string
        email   string
        role    string
        wantErr bool
    }{
        {
            name:    "valid user",
            email:   "test@example.com",
            role:    "admin",
            wantErr: false,
        },
        {
            name:    "invalid email",
            email:   "invalid",
            role:    "user",
            wantErr: true,
        },
    }
    
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            _, err := CreateUser(tt.name, tt.email, tt.role)
            if (err != nil) != tt.wantErr {
                t.Errorf("CreateUser() error = %v, wantErr %v", err, tt.wantErr)
            }
        })
    }
}
```

### Testable Design with Interfaces
```go
// ✅ GOOD - Easy to test with interfaces
type UserService struct {
    repo   UserRepository
    sender EmailSender
}

// Test with mocks
func TestRegisterUser(t *testing.T) {
    mockRepo := &MockUserRepository{}
    mockSender := &MockEmailSender{}
    service := NewUserService(mockRepo, mockSender)
    
    // Test implementation
}
```

## Code Style

### Formatting
- Use `gofmt` or `goimports` (always)
- Line length: aim for 80-100 characters
- Tabs for indentation (enforced by gofmt)

### Naming
- `MixedCaps` or `mixedCaps` (no underscores)
- Exported: `UserRepository`, `FindUser`
- Unexported: `userRepository`, `findUser`
- Acronyms: `HTTPServer`, `URLPath` (all caps)
- Constants: `MaxRetries`, `DefaultTimeout` (not UPPER_SNAKE_CASE)

### Comments
```go
// Package user provides user management functionality.
package user

// UserRepository handles user data persistence.
type UserRepository struct {
    db *sql.DB
}

// NewUserRepository creates a new UserRepository.
// It requires a valid database connection.
func NewUserRepository(db *sql.DB) *UserRepository {
    return &UserRepository{db: db}
}

// FindUser retrieves a user by ID.
// It returns ErrUserNotFound if the user doesn't exist.
func (r *UserRepository) FindUser(ctx context.Context, userID string) (*User, error) {
    // Implementation
}
```

## Package Organization

### Import Grouping
```go
import (
    // Standard library
    "context"
    "fmt"
    "time"
    
    // Third-party
    "github.com/lib/pq"
    "go.uber.org/zap"
    
    // Local
    "github.com/yourorg/yourproject/internal/models"
    "github.com/yourorg/yourproject/internal/repository"
)
```

### Package Names
- Short, concise, lowercase
- No underscores or mixedCaps
- Singular form: `user`, not `users`
- Avoid generic names: `util`, `common`, `base`

## Pointers vs Values

### When to Use Pointers
```go
// ✅ Use pointers for:
// - Large structs
// - Structs that need to be modified
// - Implementing interfaces with pointer receivers

type User struct {
    ID    string
    Name  string
    Email string
}

// Pointer receiver for modification
func (u *User) UpdateEmail(email string) {
    u.Email = email
}

// Value receiver for read-only
func (u User) GetDisplayName() string {
    return u.Name
}

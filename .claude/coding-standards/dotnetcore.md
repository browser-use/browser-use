# .NET Core Coding Standards

.NET Core/C# specific coding standards and conventions.

## File Organization

### Namespace and File Structure
- **One primary class per file** (unless closely related helper classes)
- File name should match the class name exactly (PascalCase)
- Namespace should reflect directory structure
- Group related functionality in feature-based folders

### Example
```csharp
// UserRepository.cs - contains UserRepository class
// DatabaseConnection.cs - contains DatabaseConnection class

namespace MyApp.Repositories
{
    public class UserRepository
    {
        // Implementation
    }
}
```

## Class Design

### Class Structure
```csharp
namespace MyApp.Services
{
    /// <summary>
    /// Manages user-related operations.
    /// </summary>
    public class UserService
    {
        // Constants
        private const int MaxRetries = 3;

        // Fields (readonly preferred)
        private readonly IUserRepository _repository;
        private readonly ILogger<UserService> _logger;

        // Constructor - Dependency Injection
        public UserService(IUserRepository repository, ILogger<UserService> logger)
        {
            _repository = repository ?? throw new ArgumentNullException(nameof(repository));
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
        }

        // Public methods
        public async Task<User> GetUserAsync(string userId)
        {
            // Implementation
        }

        // Private methods
        private void ValidateUserId(string userId)
        {
            // Implementation
        }
    }
}
```

### Key Rules
- One primary class per file
- Dependencies injected via constructor
- Use `readonly` for immutable fields
- No default parameter values
- Field naming: `_camelCase` for private fields
- Use dependency injection exclusively
- Validate constructor parameters (null checks)

## Function Design

### No Default Arguments
```csharp
// ❌ BAD - Default arguments
public User CreateUser(string name, string email, string role = "user")
{
    // ...
}

// ✅ GOOD - Explicit arguments
public User CreateUser(string name, string email, string role)
{
    // ...
}
```

### No Environment Variable Access
```csharp
// ❌ BAD - Reading env vars in method
public DatabaseConnection ConnectToDatabase()
{
    var host = Environment.GetEnvironmentVariable("DB_HOST");
    var port = Environment.GetEnvironmentVariable("DB_PORT");
    return Connect(host, port);
}

// ✅ GOOD - Configuration passed as arguments
public DatabaseConnection ConnectToDatabase(DatabaseConfig config)
{
    return Connect(config.Host, config.Port);
}

// Configuration class
public class DatabaseConfig
{
    public string Host { get; set; }
    public int Port { get; set; }
}

// Configuration read at startup in Startup.cs or Program.cs
var config = new DatabaseConfig
{
    Host = Environment.GetEnvironmentVariable("DB_HOST"),
    Port = int.Parse(Environment.GetEnvironmentVariable("DB_PORT"))
};

var connection = ConnectToDatabase(config);
```

### Explicit Typing
```csharp
// ✅ GOOD - Explicit types
public async Task<List<User>> ProcessUsersAsync(List<User> users, bool filterActive)
{
    // Implementation
}

// Avoid 'var' when type is not obvious
// ✅ GOOD - var is acceptable when type is clear from right side
var repository = new UserRepository(connection, logger);
var users = await repository.GetAllUsersAsync();

// ❌ BAD - var when type is not obvious
var result = ProcessData();  // What type is result?
```

## Error Handling

### Custom Exception Classes
```csharp
namespace MyApp.Exceptions
{
    /// <summary>
    /// Exception thrown when a user is not found.
    /// </summary>
    public class UserNotFoundException : Exception
    {
        public string UserId { get; }

        public UserNotFoundException(string userId)
            : base($"User with ID '{userId}' was not found.")
        {
            UserId = userId;
        }

        public UserNotFoundException(string userId, Exception innerException)
            : base($"User with ID '{userId}' was not found.", innerException)
        {
            UserId = userId;
        }
    }

    public class ValidationException : Exception
    {
        public string Field { get; }

        public ValidationException(string field, string message)
            : base(message)
        {
            Field = field;
        }
    }
}
```

### Error Propagation
```csharp
// ✅ GOOD - Let errors propagate
public async Task<User> GetUserAsync(string userId)
{
    var user = await _repository.FindByIdAsync(userId);
    if (user == null)
    {
        throw new UserNotFoundException(userId);
    }
    return user;
}

// ❌ BAD - Silent failure
public async Task<User> GetUserAsync(string userId)
{
    try
    {
        return await _repository.FindByIdAsync(userId);
    }
    catch (Exception)
    {
        return null; // Don't hide errors!
    }
}

// ✅ GOOD - Wrap and rethrow with context
public async Task<User> GetUserAsync(string userId)
{
    try
    {
        return await _repository.FindByIdAsync(userId);
    }
    catch (DatabaseException ex)
    {
        throw new UserNotFoundException(userId, ex);
    }
}
```

## Configuration Management

### Startup Configuration
```csharp
// appsettings.json
{
  "Database": {
    "Host": "localhost",
    "Port": 5432,
    "Username": "user",
    "Password": "password"
  }
}

// DatabaseConfig.cs
namespace MyApp.Configuration
{
    public class DatabaseConfig
    {
        public string Host { get; set; }
        public int Port { get; set; }
        public string Username { get; set; }
        public string Password { get; set; }
    }
}

// Program.cs (.NET 6+)
var builder = WebApplication.CreateBuilder(args);

// Bind configuration
builder.Services.Configure<DatabaseConfig>(
    builder.Configuration.GetSection("Database"));

// Or inject as singleton
var dbConfig = builder.Configuration
    .GetSection("Database")
    .Get<DatabaseConfig>();
builder.Services.AddSingleton(dbConfig);

// Startup.cs (older .NET Core)
public class Startup
{
    public IConfiguration Configuration { get; }

    public Startup(IConfiguration configuration)
    {
        Configuration = configuration;
    }

    public void ConfigureServices(IServiceCollection services)
    {
        services.Configure<DatabaseConfig>(
            Configuration.GetSection("Database"));
    }
}

// Using in a service
public class UserRepository
{
    private readonly DatabaseConfig _config;

    public UserRepository(IOptions<DatabaseConfig> config)
    {
        _config = config.Value;
    }
}
```

## Dependency Injection

### Constructor Injection
```csharp
// ✅ GOOD - Dependencies injected via constructor
public class UserService
{
    private readonly IUserRepository _repository;
    private readonly IEmailSender _emailSender;
    private readonly ILogger<UserService> _logger;

    public UserService(
        IUserRepository repository,
        IEmailSender emailSender,
        ILogger<UserService> logger)
    {
        _repository = repository ?? throw new ArgumentNullException(nameof(repository));
        _emailSender = emailSender ?? throw new ArgumentNullException(nameof(emailSender));
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));
    }

    public async Task<User> RegisterUserAsync(string email, string name)
    {
        var user = await _repository.CreateAsync(email, name);
        await _emailSender.SendWelcomeAsync(user);
        _logger.LogInformation("User {UserId} registered successfully", user.Id);
        return user;
    }
}

// Register in Program.cs or Startup.cs
services.AddScoped<IUserRepository, UserRepository>();
services.AddScoped<IEmailSender, EmailSender>();
services.AddScoped<UserService>();
```

### Service Lifetimes
```csharp
// Transient - Created each time they're requested
services.AddTransient<IEmailSender, EmailSender>();

// Scoped - Created once per request (web apps)
services.AddScoped<IUserRepository, UserRepository>();

// Singleton - Created once for the application lifetime
services.AddSingleton<ICacheService, CacheService>();
```

## Async/Await Best Practices

### Always Use Async/Await for I/O Operations
```csharp
// ✅ GOOD - Async all the way
public async Task<User> GetUserAsync(string userId)
{
    var user = await _repository.FindByIdAsync(userId);
    var orders = await _orderRepository.GetByUserIdAsync(userId);
    return user;
}

// ❌ BAD - Blocking on async code
public User GetUser(string userId)
{
    var user = _repository.FindByIdAsync(userId).Result; // Don't use .Result!
    return user;
}

// ❌ BAD - Unnecessary async
public async Task<int> CalculateSum(int a, int b)
{
    return a + b; // No await, should not be async
}

// ✅ GOOD - No async keyword needed
public Task<int> CalculateSum(int a, int b)
{
    return Task.FromResult(a + b);
}
```

### ConfigureAwait
```csharp
// In library code, use ConfigureAwait(false)
public async Task<User> GetUserAsync(string userId)
{
    var user = await _repository.FindByIdAsync(userId).ConfigureAwait(false);
    return user;
}

// In ASP.NET Core apps, ConfigureAwait is generally not needed
// as there's no synchronization context
```

### Avoid Async Void
```csharp
// ❌ BAD - Async void (only allowed in event handlers)
public async void ProcessUser(User user)
{
    await _repository.SaveAsync(user);
}

// ✅ GOOD - Async Task
public async Task ProcessUserAsync(User user)
{
    await _repository.SaveAsync(user);
}
```

## LINQ Usage Patterns

### Prefer Method Syntax
```csharp
// ✅ GOOD - Method syntax (preferred for most cases)
var activeUsers = users
    .Where(u => u.IsActive)
    .OrderBy(u => u.Name)
    .Select(u => new UserDto { Name = u.Name, Email = u.Email })
    .ToList();

// ✅ ACCEPTABLE - Query syntax (useful for complex joins)
var userOrders = from user in users
                 join order in orders on user.Id equals order.UserId
                 where user.IsActive
                 select new { user.Name, order.Total };
```

### Deferred Execution
```csharp
// ✅ GOOD - Understand deferred execution
var query = users.Where(u => u.IsActive); // Not executed yet
var count = query.Count(); // Executed here
var list = query.ToList(); // Executed again here

// ✅ GOOD - Materialize once if needed multiple times
var activeUsers = users.Where(u => u.IsActive).ToList();
var count = activeUsers.Count;
var first = activeUsers.FirstOrDefault();
```

## Nullable Reference Types

### Enable Nullable Reference Types
```csharp
// In .csproj
<PropertyGroup>
  <Nullable>enable</Nullable>
</PropertyGroup>

// In code
public class UserService
{
    // Non-nullable - must be initialized
    private readonly IUserRepository _repository;

    // Nullable - can be null
    private string? _cachedUserName;

    public UserService(IUserRepository repository)
    {
        _repository = repository;
    }

    public async Task<User?> FindUserAsync(string userId)
    {
        return await _repository.FindByIdAsync(userId);
    }

    public async Task<User> GetUserAsync(string userId)
    {
        var user = await _repository.FindByIdAsync(userId);
        if (user == null)
        {
            throw new UserNotFoundException(userId);
        }
        return user; // Compiler knows this is not null
    }
}
```

### Null-Forgiving Operator (Use Sparingly)
```csharp
// ❌ AVOID - Null-forgiving operator
var user = await _repository.FindByIdAsync(userId);
Console.WriteLine(user!.Name); // Suppresses null warning

// ✅ GOOD - Explicit null check
var user = await _repository.FindByIdAsync(userId);
if (user != null)
{
    Console.WriteLine(user.Name);
}
```

## Testing

### Testable Design with Dependency Injection
```csharp
// ✅ GOOD - Easy to test with interfaces
public interface IUserRepository
{
    Task<User?> FindByIdAsync(string userId);
    Task<User> CreateAsync(string email, string name);
}

public class UserService
{
    private readonly IUserRepository _repository;
    private readonly IEmailSender _emailSender;

    public UserService(IUserRepository repository, IEmailSender emailSender)
    {
        _repository = repository;
        _emailSender = emailSender;
    }

    public async Task<User> RegisterUserAsync(string email, string name)
    {
        var user = await _repository.CreateAsync(email, name);
        await _emailSender.SendWelcomeAsync(user);
        return user;
    }
}

// Test with mocks (using Moq)
[Fact]
public async Task RegisterUserAsync_ShouldCreateUserAndSendEmail()
{
    // Arrange
    var mockRepo = new Mock<IUserRepository>();
    var mockSender = new Mock<IEmailSender>();
    var service = new UserService(mockRepo.Object, mockSender.Object);

    var expectedUser = new User { Id = "123", Email = "test@example.com" };
    mockRepo.Setup(r => r.CreateAsync("test@example.com", "Test"))
        .ReturnsAsync(expectedUser);

    // Act
    var result = await service.RegisterUserAsync("test@example.com", "Test");

    // Assert
    Assert.Equal(expectedUser.Id, result.Id);
    mockSender.Verify(s => s.SendWelcomeAsync(expectedUser), Times.Once);
}
```

## Code Style

### Formatting
- Use Visual Studio or Rider formatter, or EditorConfig
- Line length: 120 characters (reasonable maximum)
- 4 spaces for indentation
- Braces on new line (Allman style)
- Use expression-bodied members for simple methods

### Naming Conventions
- `PascalCase` for classes, methods, properties, public fields
- `camelCase` for local variables, parameters
- `_camelCase` for private fields
- `IPascalCase` for interfaces (prefix with I)
- `UPPER_SNAKE_CASE` for constants (or PascalCase)

### XML Documentation
```csharp
/// <summary>
/// Calculates the total price including tax.
/// </summary>
/// <param name="items">List of items to calculate total for.</param>
/// <param name="taxRate">Tax rate as decimal (e.g., 0.08 for 8%).</param>
/// <returns>Total price including tax.</returns>
/// <exception cref="ArgumentNullException">Thrown when items is null.</exception>
/// <exception cref="ArgumentException">Thrown when tax rate is negative.</exception>
public decimal CalculateTotal(List<Item> items, decimal taxRate)
{
    if (items == null)
        throw new ArgumentNullException(nameof(items));
    if (taxRate < 0)
        throw new ArgumentException("Tax rate cannot be negative", nameof(taxRate));

    // Implementation
}
```

## Controller Design (ASP.NET Core)

### Controllers Must Be Thin
Controllers should only orchestrate calls to services. All business logic must be in the service layer.

```csharp
// ❌ BAD - Business logic in controller
[ApiController]
[Route("api/[controller]")]
public class UsersController : ControllerBase
{
    private readonly IUserRepository _repository;

    public UsersController(IUserRepository repository)
    {
        _repository = repository;
    }

    [HttpGet("{id}")]
    public async Task<IActionResult> GetUser(string id)
    {
        // ❌ BAD - Validation logic in controller
        if (string.IsNullOrEmpty(id))
        {
            return BadRequest("User ID is required");
        }

        // ❌ BAD - Direct repository access
        var user = await _repository.FindByIdAsync(id);

        // ❌ BAD - Business logic in controller
        if (user == null)
        {
            return NotFound($"User {id} not found");
        }

        // ❌ BAD - Data transformation in controller
        var dto = new UserDto
        {
            Name = user.Name,
            Email = user.Email
        };

        return Ok(dto);
    }
}

// ✅ GOOD - Thin controller, logic in service
[ApiController]
[Route("api/[controller]")]
public class UsersController : ControllerBase
{
    private readonly IUserService _userService;

    public UsersController(IUserService userService)
    {
        _userService = userService;
    }

    [HttpGet("{id}")]
    public async Task<ActionResult<UserDto>> GetUser(string id)
    {
        // Controller only orchestrates - all logic in service
        var user = await _userService.GetUserByIdAsync(id);
        return Ok(user);
    }
}

// Service layer with all business logic
public interface IUserService
{
    Task<UserDto> GetUserByIdAsync(string userId);
}

public class UserService : IUserService
{
    private readonly IUserRepository _repository;

    public UserService(IUserRepository repository)
    {
        _repository = repository;
    }

    public async Task<UserDto> GetUserByIdAsync(string userId)
    {
        // Validation
        if (string.IsNullOrEmpty(userId))
        {
            throw new ValidationException(nameof(userId), "User ID is required");
        }

        // Data access
        var user = await _repository.FindByIdAsync(userId);

        // Business logic
        if (user == null)
        {
            throw new UserNotFoundException(userId);
        }

        // Data transformation
        return new UserDto
        {
            Name = user.Name,
            Email = user.Email
        };
    }
}
```

### Global Exception Handling
```csharp
// Exception handling middleware
public class ExceptionHandlingMiddleware
{
    private readonly RequestDelegate _next;
    private readonly ILogger<ExceptionHandlingMiddleware> _logger;

    public ExceptionHandlingMiddleware(
        RequestDelegate next,
        ILogger<ExceptionHandlingMiddleware> logger)
    {
        _next = next;
        _logger = logger;
    }

    public async Task InvokeAsync(HttpContext context)
    {
        try
        {
            await _next(context);
        }
        catch (UserNotFoundException ex)
        {
            _logger.LogWarning(ex, "User not found: {UserId}", ex.UserId);
            context.Response.StatusCode = StatusCodes.Status404NotFound;
            await context.Response.WriteAsJsonAsync(new { error = ex.Message });
        }
        catch (ValidationException ex)
        {
            _logger.LogWarning(ex, "Validation error: {Field}", ex.Field);
            context.Response.StatusCode = StatusCodes.Status400BadRequest;
            await context.Response.WriteAsJsonAsync(new { error = ex.Message, field = ex.Field });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Unhandled exception");
            context.Response.StatusCode = StatusCodes.Status500InternalServerError;
            await context.Response.WriteAsJsonAsync(new { error = "An internal server error occurred" });
        }
    }
}

// Register in Program.cs
app.UseMiddleware<ExceptionHandlingMiddleware>();
```

### Action Filters as Decorators
```csharp
// Custom action filter for standardizing responses
public class ApiExceptionFilterAttribute : ExceptionFilterAttribute
{
    private readonly ILogger<ApiExceptionFilterAttribute> _logger;

    public ApiExceptionFilterAttribute(ILogger<ApiExceptionFilterAttribute> logger)
    {
        _logger = logger;
    }

    public override void OnException(ExceptionContext context)
    {
        if (context.Exception is UserNotFoundException notFoundEx)
        {
            context.Result = new NotFoundObjectResult(new { error = notFoundEx.Message });
            context.ExceptionHandled = true;
        }
        else if (context.Exception is ValidationException validationEx)
        {
            context.Result = new BadRequestObjectResult(new
            {
                error = validationEx.Message,
                field = validationEx.Field
            });
            context.ExceptionHandled = true;
        }
        else
        {
            _logger.LogError(context.Exception, "Unhandled exception in {Action}",
                context.ActionDescriptor.DisplayName);
            context.Result = new ObjectResult(new { error = "An internal server error occurred" })
            {
                StatusCode = StatusCodes.Status500InternalServerError
            };
            context.ExceptionHandled = true;
        }
    }
}

// Apply to controller
[ApiController]
[Route("api/[controller]")]
[ServiceFilter(typeof(ApiExceptionFilterAttribute))]
public class UsersController : ControllerBase
{
    private readonly IUserService _userService;

    public UsersController(IUserService userService)
    {
        _userService = userService;
    }

    [HttpGet("{id}")]
    public async Task<ActionResult<UserDto>> GetUser(string id)
    {
        // No try-catch needed - filter handles exceptions
        var user = await _userService.GetUserByIdAsync(id);
        return Ok(user);
    }
}

// Register filter in Program.cs
services.AddScoped<ApiExceptionFilterAttribute>();
```

## Using Directives Organization

### Order and Grouping
```csharp
// System namespaces
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;

// Microsoft namespaces
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;

// Third-party namespaces
using Newtonsoft.Json;
using AutoMapper;

// Local namespaces
using MyApp.Models;
using MyApp.Services;
using MyApp.Repositories;

namespace MyApp.Controllers
{
    // Class implementation
}
```

### Use Global Usings (.NET 6+)
```csharp
// In GlobalUsings.cs
global using System;
global using System.Collections.Generic;
global using System.Linq;
global using System.Threading.Tasks;
global using Microsoft.AspNetCore.Mvc;
global using Microsoft.Extensions.Logging;
```

## Record Types (C# 9+)

### Use Records for DTOs
```csharp
// ✅ GOOD - Record for immutable DTO
public record UserDto(string Id, string Name, string Email);

// ✅ GOOD - Record with validation
public record CreateUserRequest
{
    public string Name { get; init; }
    public string Email { get; init; }

    public CreateUserRequest(string name, string email)
    {
        if (string.IsNullOrEmpty(name))
            throw new ArgumentException("Name is required", nameof(name));
        if (string.IsNullOrEmpty(email))
            throw new ArgumentException("Email is required", nameof(email));

        Name = name;
        Email = email;
    }
}
```

## Pattern Matching

### Use Pattern Matching
```csharp
// ✅ GOOD - Modern pattern matching
public string GetUserStatus(User user) => user switch
{
    { IsActive: true, LastLoginDate: var date } when date > DateTime.Now.AddDays(-7) => "Active",
    { IsActive: true } => "Inactive",
    { IsActive: false } => "Disabled",
    _ => "Unknown"
};

// ✅ GOOD - Type pattern matching
public decimal CalculatePrice(IProduct product) => product switch
{
    PhysicalProduct p => p.Price + p.ShippingCost,
    DigitalProduct d => d.Price,
    SubscriptionProduct s => s.MonthlyPrice,
    _ => throw new ArgumentException("Unknown product type", nameof(product))
};
```

## Key Principles Summary

1. **No default parameter values** - Always explicit
2. **No environment variable access in business logic** - Read at startup, inject via configuration
3. **Dependency injection everywhere** - Constructor injection for all dependencies
4. **Thin controllers** - All logic in service layer
5. **Async all the way** - Use async/await for all I/O operations
6. **Explicit error handling** - Custom exceptions, no silent failures
7. **Nullable reference types** - Enable and use properly
8. **Interface-based design** - Makes testing easier
9. **LINQ for collections** - Prefer method syntax
10. **Immutability preferred** - Use `readonly`, records, `init` accessors

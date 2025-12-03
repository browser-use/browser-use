# Python Coding Standards

Python-specific coding standards and conventions.

## File Organization

### Module Structure
- **One class per file** (unless closely related helper classes)
- File name should match the main class name in snake_case
- Module-level constants at the top
- Imports organized: standard library, third-party, local

### Example
```python
# user_repository.py - contains UserRepository class
# database_connection.py - contains DatabaseConnection class
```

## Class Design

### Class Structure
```python
class UserRepository:
    """Class docstring explaining purpose."""
    
    # Class constants
    MAX_RETRIES = 3
    
    def __init__(self, db_connection, logger):
        """Initialize with dependencies - no defaults."""
        self.db_connection = db_connection
        self.logger = logger
    
    def find_user(self, user_id):
        """Public methods."""
        pass
    
    def _validate_user_id(self, user_id):
        """Private methods prefixed with underscore."""
        pass
```

### Key Rules
- One primary class per file
- Dependencies injected via `__init__`
- No default parameter values
- Use `@property` for computed attributes
- Use `@staticmethod` or `@classmethod` appropriately

## Function Design

### No Default Arguments
```python
# ❌ BAD - Default arguments
def create_user(name, email, role="user"):
    pass

# ✅ GOOD - Explicit arguments
def create_user(name, email, role):
    pass
```

**Exception: FastAPI Optional Form Parameters**

FastAPI 0.115.5+ requires the `= None` syntax for optional form parameters. This is the ONLY acceptable use of default parameter values:

```python
from fastapi import FastAPI, Form
from typing import Optional

app = FastAPI()

# ✅ ALLOWED - FastAPI optional form parameters
@app.post("/users")
async def create_user(
    name: str = Form(...),
    email: str = Form(...),
    phone: Optional[str] = Form(None)  # This is acceptable for FastAPI
):
    # phone is optional and defaults to None
    pass

# ❌ STILL BAD - Regular function defaults
def process_user(name, email, phone=None):  # Not allowed
    pass

# ✅ GOOD - Pass optional values explicitly
def process_user(name, email, phone):
    # If phone can be None, use Optional[str] type hint
    pass
```

**Key Points:**
- The `= None` exception applies ONLY to FastAPI `Form()` parameters
- Regular functions must still have no default values
- Use `Optional[Type]` type hints to indicate nullable parameters
- Service layer functions should never use defaults, even for optional values

### No Environment Variable Access
```python
# ❌ BAD - Reading env vars in function
def connect_to_database():
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT")
    return connect(host, port)

# ✅ GOOD - Configuration passed as arguments
def connect_to_database(host, port):
    return connect(host, port)

# Configuration read at startup
config = {
    "db_host": os.getenv("DB_HOST"),
    "db_port": os.getenv("DB_PORT")
}
db = connect_to_database(config["db_host"], config["db_port"])
```

### Type Hints
```python
from typing import List, Optional, Dict

def process_users(
    users: List[Dict[str, str]], 
    filter_active: bool
) -> List[Dict[str, str]]:
    """Always use type hints for function signatures."""
    pass
```

## Error Handling

### Custom Exceptions
```python
class UserNotFoundError(Exception):
    """Raised when user cannot be found."""
    pass

class ValidationError(Exception):
    """Raised when validation fails."""
    pass
```

### Error Propagation
```python
# ✅ GOOD - Let errors propagate
def get_user(user_id):
    user = repository.find(user_id)
    if not user:
        raise UserNotFoundError(f"User {user_id} not found")
    return user

# ❌ BAD - Silent failure
def get_user(user_id):
    try:
        return repository.find(user_id)
    except Exception:
        return None  # Don't hide errors!
```

## Configuration Management

### Startup Configuration
```python
# config.py
import os
from dataclasses import dataclass

@dataclass
class DatabaseConfig:
    """Configuration read once at startup."""
    host: str
    port: int
    username: str
    password: str
    
    @classmethod
    def from_env(cls):
        """Factory method to create from environment."""
        return cls(
            host=os.getenv("DB_HOST"),
            port=int(os.getenv("DB_PORT")),
            username=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD")
        )

# main.py
config = DatabaseConfig.from_env()
repository = UserRepository(config)
```

## Testing

### Testable Design
```python
# ✅ GOOD - Easy to test with dependency injection
class UserService:
    def __init__(self, repository, email_sender):
        self.repository = repository
        self.email_sender = email_sender
    
    def register_user(self, email, name):
        user = self.repository.create(email, name)
        self.email_sender.send_welcome(user)
        return user

# Test with mocks
def test_register_user():
    mock_repo = Mock()
    mock_sender = Mock()
    service = UserService(mock_repo, mock_sender)
    # ... test logic
```

## Code Style

### Formatting
- Use Black or similar formatter
- Line length: 88-100 characters
- 4 spaces for indentation
- 2 blank lines between top-level definitions

### Naming
- `snake_case` for functions, variables, modules
- `PascalCase` for classes
- `UPPER_SNAKE_CASE` for constants
- `_leading_underscore` for private methods

### Docstrings
```python
def calculate_total(items, tax_rate):
    """
    Calculate total price including tax.
    
    Args:
        items: List of item dictionaries with 'price' key
        tax_rate: Tax rate as decimal (e.g., 0.08 for 8%)
    
    Returns:
        Total price as float including tax
    
    Raises:
        ValueError: If tax_rate is negative
    """
    pass
```

## Controller Design (Web Frameworks)

### Route Handlers Must Not Contain Business Logic

Route handlers (controllers) should be thin orchestration layers that only:
1. Call service layer methods
2. Return the result

All business logic, validation, and data processing must be in the service layer.

#### Complete Example

```python
# services.py
class UserNotFoundError(Exception):
    """Custom exception raised when a user isn't found in the database."""
    pass

class UserService:
    """
    Manages user data. This is our "service" layer.
    It has no knowledge of HTTP, FastAPI, or web requests.
    """
    def __init__(self):
        # A mock database
        self._users = {
            1: {"id": 1, "name": "Alice", "email": "alice@example.com"},
            2: {"id": 2, "name": "Bob", "email": "bob@example.com"},
        }

    def get_user_by_id(self, user_id: int) -> dict:
        """
        Fetches a user by their ID.
        
        Returns:
            A dictionary with user data.
        
        Raises:
            UserNotFoundError: If the user ID does not exist.
        """
        user = self._users.get(user_id)
        
        if not user:
            # The service layer's only job is to state what went wrong
            # at a business-logic level.
            raise UserNotFoundError(f"User with ID {user_id} not found.")
            
        return user


# decorators.py
import functools
import asyncio
from starlette.responses import JSONResponse
from services import UserNotFoundError  # Import our custom exception

class HandleApiErrors:
    """
    A class-based decorator to standardize API *error* responses.
    
    It wraps a controller function and automatically catches 
    service-layer exceptions, translating them into the correct
    HTTP JSON error response.
    """
    
    def __call__(self, fn):
        """
        This is what gets called when the decorator wraps the function.
        'fn' is the controller function itself (e.g., 'get_user_controller').
        """
        
        # Check if the function we're wrapping is async or not
        if asyncio.iscoroutinefunction(fn):
            # It's an async function, so our wrapper must be async
            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                try:
                    # --- SUCCESS ---
                    # Call the original async controller function
                    return await fn(*args, **kwargs)

                # --- FAILURE (Specific) ---
                except UserNotFoundError as e:
                    response = {"error": str(e)}
                    return JSONResponse(status_code=404, content=response)

                # --- FAILURE (Generic) ---
                except Exception as e:
                    print(f"Unhandled exception in {fn.__name__}: {e}")
                    response = {"error": "An internal server error occurred."}
                    return JSONResponse(status_code=500, content=response)
            
            return async_wrapper
        
        else:
            # It's a regular sync function
            @functools.wraps(fn)
            def sync_wrapper(*args, **kwargs):
                try:
                    # --- SUCCESS ---
                    # Call the original sync controller function
                    return fn(*args, **kwargs)

                # --- FAILURE (Specific) ---
                except UserNotFoundError as e:
                    response = {"error": str(e)}
                    return JSONResponse(status_code=404, content=response)

                # --- FAILURE (Generic) ---
                except Exception as e:
                    print(f"Unhandled exception in {fn.__name__}: {e}")
                    response = {"error": "An internal server error occurred."}
                    return JSONResponse(status_code=500, content=response)

            return sync_wrapper


# app.py
from fastapi import FastAPI
from services import UserService
from decorators import HandleApiErrors

# --- Application Setup ---
app = FastAPI()
user_service = UserService()  # Instantiate our service

# --- Controller (Routes) ---

@app.get("/users/{user_id}", status_code=200)
@HandleApiErrors()  # <-- The decorator is applied here
async def get_user_controller(user_id: int):
    """
    This is the "clean" controller (endpoint).
    
    Its only responsibility is to orchestrate the call to the
    service layer. It just returns the raw data.
    
    - Success (200) is handled by the @app.get decorator.
    - Errors (404, 500) are handled by the @HandleApiErrors decorator.
    """
    # 1. Call the service directly
    # 2. Return the data
    # The decorator will handle exceptions, and FastAPI
    # will handle the successful serialization.
    return user_service.get_user_by_id(user_id)
```

### Key Principles

- **Controllers are thin**: Only orchestrate calls to services
- **Services contain logic**: All business logic, validation, and data access
- **Decorators handle errors**: Convert service exceptions to HTTP responses
- **Clean separation**: Controllers know nothing about business rules

## Imports

### Organization
```python
# Standard library
import os
import sys
from typing import List, Dict

# Third-party
import requests
from flask import Flask

# Local application
from .models import User
from .repositories import UserRepository
```

### Avoid
- `from module import *`
- Circular imports
- Importing at function level (unless necessary)

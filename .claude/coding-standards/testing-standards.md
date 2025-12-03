# Testing Standards

Standards for writing and maintaining tests across all testing agents.

## Mandatory Rules

### No Conditional Logic to Bypass Failures
Tests MUST NOT contain conditional `if` statements that exist solely to make tests pass artificially.

```python
# BAD - Conditional to bypass test failure
def test_user_creation():
    result = create_user("alice@example.com")
    if result is None:
        pytest.skip("User creation failed, skipping")  # Hiding the real problem!
    assert result.email == "alice@example.com"

# BAD - Environment check that masks test failure
def test_api_response():
    response = api.get_data()
    if response.status_code != 200:
        return  # Silently passing when it should fail!
    assert response.json()["success"] == True

# GOOD - Test fails when behavior is incorrect
def test_user_creation():
    result = create_user("alice@example.com")
    assert result is not None, "User creation should succeed"
    assert result.email == "alice@example.com"
```

### Acceptable Conditional Logic
Conditions in tests are ONLY acceptable for genuine environment limitations:

```python
# GOOD - Skip when required external dependency is unavailable
@pytest.mark.skipif(
    not os.environ.get("API_TOKEN"),
    reason="API_TOKEN not configured - external API tests require authentication"
)
def test_external_api_integration():
    response = external_api.fetch_data()
    assert response.status_code == 200

# GOOD - Skip platform-specific tests
@pytest.mark.skipif(
    sys.platform != "linux",
    reason="Test requires Linux-specific features"
)
def test_linux_file_permissions():
    # ...

# GOOD - Skip when database is not available
@pytest.fixture
def database_connection():
    try:
        conn = connect_to_database()
        yield conn
        conn.close()
    except ConnectionError:
        pytest.skip("Database not available for integration tests")
```

## Test Structure

### Arrange-Act-Assert Pattern
All tests MUST follow the Arrange-Act-Assert (AAA) pattern:

```python
def test_order_total_calculation():
    # Arrange - Set up test data and dependencies
    order = Order()
    order.add_item(Item(price=10.00, quantity=2))
    order.add_item(Item(price=5.50, quantity=1))

    # Act - Execute the code under test
    total = order.calculate_total()

    # Assert - Verify expected behavior
    assert total == 25.50
```

### One Concept Per Test
Each test should verify ONE specific behavior or concept:

```python
# BAD - Testing multiple unrelated behaviors
def test_user_operations():
    user = create_user("alice@example.com")
    assert user is not None
    user.update_email("bob@example.com")
    assert user.email == "bob@example.com"
    delete_user(user.id)
    assert get_user(user.id) is None

# GOOD - Separate tests for each behavior
def test_create_user_succeeds():
    user = create_user("alice@example.com")
    assert user is not None
    assert user.email == "alice@example.com"

def test_update_user_email():
    user = create_user("alice@example.com")
    user.update_email("bob@example.com")
    assert user.email == "bob@example.com"

def test_delete_user_removes_from_database():
    user = create_user("alice@example.com")
    delete_user(user.id)
    assert get_user(user.id) is None
```

### Test Independence
Tests MUST be completely independent:

```python
# BAD - Tests depend on shared state
class TestUserService:
    user = None  # Shared state!

    def test_create_user(self):
        self.user = create_user("test@example.com")
        assert self.user is not None

    def test_update_user(self):
        self.user.update_name("New Name")  # Depends on previous test!
        assert self.user.name == "New Name"

# GOOD - Each test sets up its own state
class TestUserService:
    def test_create_user(self):
        user = create_user("test@example.com")
        assert user is not None

    def test_update_user():
        user = create_user("test@example.com")
        user.update_name("New Name")
        assert user.name == "New Name"
```

## Assertions

### Complete Response Assertions
When testing API endpoints, assert the ENTIRE response structure:

```python
# BAD - Only checking individual fields
def test_get_user_endpoint():
    response = client.get("/users/1")
    assert response.status_code == 200
    assert response.json()["name"] == "Alice"
    # Missing checks for other fields - unexpected fields could slip through!

# GOOD - Assert complete response structure
def test_get_user_endpoint():
    response = client.get("/users/1")
    assert response.status_code == 200
    assert response.json() == {
        "id": 1,
        "name": "Alice",
        "email": "alice@example.com",
        "created_at": "2024-01-15T10:30:00Z"
    }
```

### Meaningful Assertion Messages
Include context in assertion messages:

```python
# BAD - No context on failure
assert result == expected

# GOOD - Clear failure message
assert result == expected, f"Expected {expected} but got {result}"

# GOOD - Using descriptive assertions
assert user.email == "alice@example.com", f"User email should be 'alice@example.com', got '{user.email}'"
```

### No Always-True Assertions
Avoid assertions that can never fail:

```python
# BAD - These always pass
assert True
assert 1 == 1
assert result is result

# BAD - Tautological check
if result:
    assert result  # Only runs when result is truthy!

# GOOD - Meaningful assertions
assert result == expected_value
assert len(items) == 5
assert user.is_active is True
```

## Test Data

### Explicit Test Data
Use explicit, readable test data:

```python
# BAD - Magic numbers and unclear values
def test_calculation():
    result = calculate(42, 7)
    assert result == 294

# GOOD - Clear, named values
def test_order_total_with_quantity_discount():
    unit_price = 10.00
    quantity = 10
    discount_rate = 0.10  # 10% discount for 10+ items

    result = calculate_order_total(unit_price, quantity, discount_rate)

    expected_total = 90.00  # (10 * 10) - 10% discount
    assert result == expected_total
```

### Factory Functions for Complex Objects
Use factories for test data creation:

```python
# BAD - Repeated object construction
def test_user_validation():
    user = User(
        id=1,
        name="Test User",
        email="test@example.com",
        created_at=datetime.now(),
        role="user"
    )
    assert validate_user(user)

# GOOD - Factory function
def create_test_user(**overrides):
    defaults = {
        "id": 1,
        "name": "Test User",
        "email": "test@example.com",
        "created_at": datetime.now(),
        "role": "user"
    }
    return User(**{**defaults, **overrides})

def test_user_validation():
    user = create_test_user()
    assert validate_user(user)

def test_admin_user_validation():
    admin = create_test_user(role="admin")
    assert validate_user(admin)
```

## Mocking and Test Doubles

### Mock at Boundaries
Mock external dependencies at system boundaries:

```python
# BAD - Mocking internal implementation details
def test_user_service():
    with patch('user_service._validate_email') as mock:
        mock.return_value = True
        result = create_user("test@example.com")

# GOOD - Mock external dependencies at boundaries
def test_user_service():
    mock_email_client = Mock(spec=EmailClient)
    mock_email_client.send.return_value = True

    service = UserService(email_client=mock_email_client)
    result = service.create_user("test@example.com")
```

### Verify Mock Interactions
When using mocks, verify they were called correctly:

```python
def test_user_notification_sends_email():
    mock_email_client = Mock(spec=EmailClient)
    service = NotificationService(email_client=mock_email_client)

    service.notify_user("user@example.com", "Welcome!")

    mock_email_client.send.assert_called_once_with(
        to="user@example.com",
        subject="Notification",
        body="Welcome!"
    )
```

## Error Testing

### Test Expected Exceptions
Explicitly test error conditions:

```python
def test_invalid_email_raises_validation_error():
    with pytest.raises(ValidationError) as exc_info:
        create_user("invalid-email")

    assert "Invalid email format" in str(exc_info.value)

def test_missing_required_field_raises_error():
    with pytest.raises(ValueError, match="name is required"):
        create_user(email="test@example.com", name=None)
```

### Test Error Messages
Verify error messages are helpful:

```python
def test_error_message_includes_context():
    with pytest.raises(NotFoundError) as exc_info:
        get_user(user_id=999)

    error = exc_info.value
    assert error.message == "User not found"
    assert error.user_id == 999
```

## Test Naming

### Descriptive Test Names
Test names should describe the behavior being tested:

```python
# BAD - Vague names
def test_user()
def test_1()
def test_error()

# GOOD - Descriptive names that explain behavior
def test_create_user_with_valid_email_succeeds()
def test_create_user_with_duplicate_email_raises_conflict_error()
def test_get_user_with_nonexistent_id_returns_none()
```

### Naming Convention by Framework

**Python (pytest)**:
```python
def test_should_return_user_when_valid_id_provided():
def test_should_raise_error_when_user_not_found():
```

**JavaScript/TypeScript (Jest)**:
```typescript
it('should return user when valid id is provided')
it('should throw error when user not found')
```

**Go**:
```go
func TestShouldReturnUserWhenValidIdProvided(t *testing.T)
func TestShouldRaiseErrorWhenUserNotFound(t *testing.T)
```

## Coverage Requirements

### Test All Code Paths
Ensure tests cover:
- Happy path (normal operation)
- Edge cases (boundary values, empty inputs)
- Error conditions (invalid inputs, failures)
- State transitions (if applicable)

### No Dead Code in Tests
Remove unused test code:

```python
# BAD - Commented out or dead code
def test_user_creation():
    # result = old_create_user("test@example.com")
    result = create_user("test@example.com")
    # if result is None:
    #     return
    assert result is not None
```

## Framework-Specific Standards

### pytest (Python)
- Use fixtures for shared setup
- Use `@pytest.mark.parametrize` for data-driven tests
- Use `conftest.py` for shared fixtures
- Use `pytest.raises` for exception testing

### Jest (JavaScript/TypeScript)
- Use `describe` blocks to group related tests
- Use `beforeEach`/`afterEach` for setup/teardown
- Use `expect().toThrow()` for exception testing
- Use `jest.mock()` for mocking modules

### Go testing
- Use table-driven tests for multiple cases
- Use subtests with `t.Run()`
- Use `testify` assertions for clearer failures
- Use interfaces for dependency injection in tests

## Critical Violations

The following are CRITICAL violations that must be fixed:

1. **Conditional bypasses** - `if` statements that skip or pass tests to hide failures
2. **Silent returns** - `return` statements in tests that prevent assertions from running
3. **Always-true assertions** - Assertions that can never fail
4. **Shared mutable state** - Tests that depend on or modify shared state
5. **Missing assertions** - Tests that execute code but don't verify behavior
6. **Incomplete response assertions** - Only checking partial API responses

## Minor Violations

The following should be fixed but are not blocking:

1. Missing assertion messages
2. Unclear test names
3. Missing test documentation
4. Duplicate test setup code (should use fixtures)

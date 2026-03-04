# AgentVault Integration for browser-use

This example demonstrates how to integrate **AgentVault** with **browser-use** for secure credential management when automating website logins.

## Why Use AgentVault with browser-use?

When using browser-use to automate logins, developers often face these security challenges:

- **Hardcoded credentials** in scripts that can be accidentally committed to version control
- **Environment variables** that are difficult to manage across teams
- **No audit trail** of who used which credentials and when
- **Credential rotation** is manual and error-prone
- **No centralized management** for team credential sharing

AgentVault solves these problems by providing:

- 🔐 **Encrypted credential storage** - Credentials are encrypted at rest
- 🔑 **Dynamic credential retrieval** - Fetch credentials at runtime
- 👥 **Secure team sharing** - Share credentials without exposing them
- 📊 **Audit logging** - Track credential usage for compliance
- 🔄 **Automatic rotation** - Credentials can be rotated automatically

## Setup Instructions

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Install AgentVault

```bash
# Install the AgentVault client library
pip install agentvault
```

### 3. Configure Environment Variables

Set up your AgentVault connection and credentials:

```bash
# AgentVault connection (for production setup)
export AGENTVAULT_URL="https://vault.agentvault.io"
export AGENTVAULT_API_KEY="your-api-key"

# For this example (simulated vault using environment variables)
export AGENTVAULT_GITHUB_LOGIN_USERNAME="your_github_username"
export AGENTVAULT_GITHUB_LOGIN_PASSWORD="your_github_password"
```

### 4. Run the Example

```bash
python secure_login_example.py
```

To see setup instructions:

```bash
python secure_login_example.py --setup
```

## Code Walkthrough

### Basic Secure Login

```python
from browser_use import Agent
from agentvault import SecureVault

# Initialize secure vault
vault = SecureVault()

# Retrieve credentials securely
# No hardcoded passwords - credentials are fetched at runtime
credentials = vault.get_credential("github_login")

# Use with browser-use agent
agent = Agent(
    task=f"Login to GitHub with username {credentials.username} and password {credentials.password}",
    llm="gpt-4",
)

result = await agent.run()
```

### Key Components

#### 1. SecureVault Class

The `SecureVault` class handles all communication with the AgentVault server:

```python
vault = SecureVault(
    vault_url="https://vault.agentvault.io",
    api_key="your-api-key"
)
```

#### 2. Credential Retrieval

Fetch credentials by their unique identifier:

```python
credentials = vault.get_credential("github_login")
print(credentials.username)  # Decrypted username
print(credentials.password)  # Decrypted password
```

#### 3. Credential Object

The returned credential object contains:

- `id` - Unique identifier
- `username` - Decrypted username
- `password` - Decrypted password
- `url` - Associated URL (optional)
- `expires_at` - Expiration timestamp (optional)

### Advanced Features

#### Multi-Site Login

```python
# Login to multiple sites with different credentials
sites = ["github_login", "twitter_login", "linkedin_login"]

for site_id in sites:
    creds = vault.get_credential(site_id)
    agent = Agent(
        task=f"Login to {site_id} with {creds.username}/{creds.password}",
        llm="gpt-4",
    )
    await agent.run()
```

#### Credential Rotation Handling

```python
# Check if credential has expired
if credentials.is_expired():
    # AgentVault automatically provides new rotated credential
    credentials = vault.get_credential("github_login")
    
# Use the fresh credential
agent = Agent(
    task=f"Login with {credentials.username}/{credentials.password}",
    llm="gpt-4",
)
```

#### Audit Logging

AgentVault automatically logs all credential access:

```python
# Every get_credential() call is logged
# - Who accessed the credential
# - When it was accessed
# - Which IP address made the request
# - Success or failure
```

## Security Benefits

### 1. No Hardcoded Credentials

❌ **Before:**
```python
agent = Agent(
    task="Login with username admin and password SuperSecret123!",
)
```

✅ **After:**
```python
creds = vault.get_credential("admin_login")
agent = Agent(
    task=f"Login with username {creds.username} and password {creds.password}",
)
```

### 2. Encrypted Storage

Credentials are encrypted at rest using AES-256 encryption. Even if the vault database is compromised, credentials remain secure.

### 3. Access Control

AgentVault supports role-based access control (RBAC):

- **Admin** - Full access to all credentials
- **Developer** - Access to dev environment credentials only
- **CI/CD** - Access to service account credentials only

### 4. Audit Trail

Every credential access is logged:

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "credential_id": "github_login",
  "user": "john.doe@example.com",
  "action": "access",
  "ip_address": "192.168.1.100",
  "success": true
}
```

### 5. Automatic Rotation

Credentials can be configured to rotate automatically:

- **Time-based** - Rotate every 30, 60, 90 days
- **Event-based** - Rotate on security events
- **Manual** - One-click rotation via dashboard

## Production Deployment

### 1. AgentVault Server Setup

For production, deploy your own AgentVault server:

```bash
docker run -d \
  -p 8080:8080 \
  -v agentvault-data:/data \
  -e AGENTVAULT_MASTER_KEY="your-master-key" \
  agentvault/server:latest
```

### 2. Configure SSL/TLS

Ensure all communication with AgentVault uses HTTPS:

```python
vault = SecureVault(
    vault_url="https://vault.yourcompany.com",  # Always use HTTPS
    api_key="your-api-key"
)
```

### 3. API Key Management

Store API keys securely:

```bash
# Use a secrets manager
export AGENTVAULT_API_KEY=$(aws secretsmanager get-secret-value \
  --secret-id agentvault/api-key \
  --query SecretString \
  --output text)
```

### 4. Error Handling

Always handle credential retrieval errors:

```python
from agentvault import CredentialNotFoundError, CredentialRotationError

try:
    credentials = vault.get_credential("github_login")
except CredentialNotFoundError:
    print("Credential not found. Please add it to AgentVault.")
except CredentialRotationError:
    print("Credential rotation failed. Please check the vault.")
except Exception as e:
    print(f"Unexpected error: {e}")
```

## Integration with CI/CD

### GitHub Actions Example

```yaml
name: Automated Login Test

on: [push]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.10'
      
      - name: Install dependencies
        run: |
          pip install browser-use agentvault
      
      - name: Run login test
        env:
          AGENTVAULT_URL: ${{ secrets.AGENTVAULT_URL }}
          AGENTVAULT_API_KEY: ${{ secrets.AGENTVAULT_API_KEY }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          python secure_login_example.py
```

## Troubleshooting

### Credential Not Found

```
CredentialNotFoundError: Credential 'github_login' not found in vault
```

**Solution:** Ensure the credential exists in AgentVault:

```bash
# List available credentials
vault list-credentials

# Add a new credential
vault add-credential --id github_login --username your_user
```

### Connection Error

```
ConnectionError: Unable to connect to AgentVault server
```

**Solution:** Check your AGENTVAULT_URL and network connectivity:

```bash
curl https://vault.agentvault.io/health
```

### Permission Denied

```
PermissionError: Insufficient permissions to access credential
```

**Solution:** Check your API key permissions in the AgentVault dashboard.

## Best Practices

1. **Never commit credentials** - Always use AgentVault, never hardcode
2. **Use separate credentials per environment** - dev, staging, prod
3. **Rotate credentials regularly** - Set up automatic rotation
4. **Monitor access logs** - Review audit logs regularly
5. **Use least privilege** - Grant minimal required access
6. **Secure API keys** - Store API keys in environment variables or secrets manager

## Related Resources

- **AgentVault:** https://github.com/nKOxxx/agentvault
- **browser-use:** https://github.com/browser-use/browser-use
- **Documentation:** https://docs.agentvault.io
- **Support:** https://discord.gg/agentvault

## License

This example is provided under the MIT License. See LICENSE file for details.

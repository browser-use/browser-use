# Deployment Instructions - Browser-use API  

This document contains instructions for deploying the Browser-use API on a VPS using Easypanel and Nixpacks 1.30.  

## Prerequisites  

- A VPS with Easypanel installed  
- Basic knowledge of Git and Docker  
- API keys for the language models you intend to use  

## Environment Setup  

1. Clone this repository on your local machine or directly on the VPS  
2. Copy the `.env.example` file to `.env` and fill in the required environment variables  

## Deployment using Easypanel  

### 1. Access the Easypanel Dashboard  

Access the Easypanel panel installed on your VPS through your browser.  

### 2. Create a New Project  

1. Click on "Create project"  
2. Choose the "Website" or "Custom" option  
3. Fill in the project name (e.g., "browser-use-api")  
4. Configure the domain or subdomain to access the API  

### 3. Project Configuration  

On the project configuration screen:  

1. Select **Build from source**  
2. Enter your Git repository URL (GitHub, GitLab, etc.)  
3. Under "Build settings," select **Dockerfile** as the builder (recommended)  
   - Alternatively, you can use **Nixpacks** with version 1.30 or higher  
4. Leave the "Start command" blank (the command is defined in Dockerfile/nixpacks.toml)  

### 4. Resource Configuration  

Configure resources according to the application's needs:  

- CPU: At least 1 vCPU recommended  
- RAM: Minimum of 2GB for proper operation  
- Storage: 10GB or more  

### 5. Environment Variables  

Configure the required environment variables:  

1. Go to the "Environment Variables" section  
2. Add all variables from your `.env` file  
3. Ensure you add at least:  
   - `OPENAI_API_KEY` or another required API key for the language model  
   - `GOOGLE_API_KEY` - **Required** for Google Generative AI  
   - `PORT` (set to 8000)  
   - `BROWSER_USE_HEADLESS=true` - Recommended for greater stability in production  

### 6. Project Deployment  

1. Click "Deploy" to start the build and deployment process  
2. Monitor the logs to verify the build is running correctly  
3. Once completed, the API will be available at the configured domain  

## Testing the API  

After deployment, test the API by sending an HTTP request to the `/health` endpoint:  

```bash  
curl https://your-domain.com/health  
```  

If the response is `{"status": "healthy"}`, the API is working correctly.  

To test full functionality, send a request to the `/run` endpoint:  

```bash  
curl -X POST https://your-domain.com/run \  
  -H "Content-Type: application/json" \  
  -d '{  
    "task": "Get the title of Google's homepage",  
    "llm_config": {  
      "provider": "openai",  
      "model_name": "gpt-4o",  
      "temperature": 0.0  
    },  
    "browser_config": {  
      "headless": true,  
      "disable_security": true  
    },  
    "max_steps": 5,  
    "use_vision": true  
  }'  
```  

## Troubleshooting  

### Startup Freezing Issues  

If the server gets stuck on messages like "Checking Playwright browser installation..." or "Starting server with xvfb-run..." for more than 10 minutes:  

1. **Check full logs:** Use `docker logs -f container-name` to view all application logs and identify where it's stuck.  

2. **Check system resources:** Ensure the VPS has enough memory (minimum 2GB recommended). Playwright installation may fail silently if there isn't enough memory.  

3. **Enable pure headless mode:**  
   - Add the environment variable `BROWSER_USE_HEADLESS=true` in the project settings.  
   - This will make the browser run in pure headless mode, without relying on Xvfb.  

4. **Access the container and check status:**  
   ```bash  
   docker exec -it container-name bash  
   ps aux  # To view running processes  
   kill -9 PID  # To kill stuck processes if necessary  
   ```  

5. **Restart the container:** From the Easypanel dashboard, restart the application container.  

6. **Verify Playwright execution:**  
   ```bash  
   docker exec -it container-name bash  
   python3 -c "from playwright.sync_api import sync_playwright; print('OK!' if sync_playwright().__enter__() else 'Failed')"  
   ```  

7. **Last-resort solution:** If nothing works, modify the `start.sh` file directly in the container to skip Playwright verification and force pure headless mode:  
   ```bash  
   docker exec -it container-name bash  
   echo '#!/bin/bash  
   export BROWSER_USE_HEADLESS=true  
   exec python3 server.py' > /app/start.sh  
   chmod +x /app/start.sh  
   ```  
   Then restart the container.  

### Docker Build Issues  

If the Docker build fails or takes too long:  

1. **Build locally:** Build the image locally and upload it to a registry like Docker Hub.  
   ```bash  
   docker build -t your-username/browser-use:latest .  
   docker push your-username/browser-use:latest  
   ```  

2. **Use a pre-built image:** In Easypanel, choose "Use existing image" and specify `your-username/browser-use:latest`.  

3. **Disable Playwright installation during build:** Edit the Dockerfile and comment out the line installing Playwright, allowing it to be installed only during startup.  

### Dockerfile Issues  

If you encounter errors like `Unable to locate package xvfb-run` or `Unable to locate package gnumake` during the build:  

1. **Correct package names:** Ensure you're using the correct Debian package names. For example, use `make` instead of `gnumake` and verify that `xvfb` is being installed.  

2. **Custom xvfb-run script:** The Dockerfile includes a custom script to create the `xvfb-run` utility if it's not available in the system.  

3. **X11 dependencies:** Ensure the `x11-utils` package is installed for tools like `xdpyinfo`.  

### Python Issues  

If you encounter errors like `python: command not found` or `ModuleNotFoundError: No module named 'X'`:  

1. **Use the provided Dockerfile:** We strongly recommend using the provided Dockerfile, which is pre-configured with all necessary dependencies, including the correct Python version.  

2. **Langchain dependencies:** The server requires several Langchain dependencies, including:  
   - `langchain-google-genai` - For Google Generative AI integration  
   - Other dependencies listed in `requirements.txt` or `pyproject.toml`  

3. **Manually install dependencies:** If using an existing container, install missing dependencies:  
   ```bash  
   pip install langchain-google-genai  
   ```  

4. **Check startup errors:** If the server doesn't show logs after startup, check import errors by running the script manually:  
   ```bash  
   python3 server.py  
   ```  

### Nixpacks and Missing Packages  

If you encounter errors like `undefined variable 'package-name'` during Nixpacks build:  

1. Verify the package name is correct and exists in the Nix repository.  
2. For `xvfb` issues, use `xvfb-run`, which already includes the required functionality.  
3. If needed, edit `nixpacks.toml` and remove problematic packages.  
4. **Alternative nixpacks.toml:** If issues persist, rename `nixpacks.toml.alternative` to `nixpacks.toml` and try again. This version uses a more direct approach to install required packages.  

### Chromium Issues  

If there are issues with Chrome/Chromium:  

1. Check application logs for specific errors.  
2. Ensure Easypanel is using `nixpacks.toml` or the Dockerfile.  
3. If needed, add the environment variable `PLAYWRIGHT_BROWSERS_PATH=/tmp/playwright-browsers` to allow Playwright to download and install browsers automatically.  

### Browser Execution Errors  

If the browser fails to start correctly, try:  

1. Verifying all system dependencies are installed.  
2. Setting `headless` to `true` in the configuration.  
3. Allocating more memory to the service in Easypanel.  

## Using Docker Instead of Nixpacks  

Due to common issues with Nixpacks, we **strongly** recommend using Docker for deployment:  

1. In Easypanel, choose "Custom" as the project type.  
2. Under "Build settings," select **Dockerfile** as the builder.  
3. The system will use the provided Dockerfile, which includes all necessary dependencies.  

The Dockerfile is specially configured to resolve common dependency and Python setup issues.

# Browser Use - Browser Automation System  

A Playwright-based browser automation system with automatic session management and performance metrics.  

## Requirements  

- Python 3.8+  
- PostgreSQL 12+  
- Playwright  
- psutil  

## Installation  

1. Clone the repository:  
```bash  
git clone https://github.com/your-username/browser-use.git  
cd browser-use  
```  

2. Create and activate a virtual environment:  
```bash  
python -m venv venv  
source venv/bin/activate  # Linux/Mac  
venv\Scripts\activate     # Windows  
```  

3. Install dependencies:  
```bash  
pip install -r requirements.txt  
```  

4. Configure the `.env` file:  
```bash  
cp .env.example .env  
# Edit the .env file with your settings  
```  

5. Install Playwright browsers:  
```bash  
playwright install  
```  

6. Start the server:  
```bash  
./start.sh  
```  

## Usage  

### Available Endpoints  

1. **Task Execution**  
```bash  
curl -X POST http://localhost:8000/run \  
  -H "Content-Type: application/json" \  
  -d '{  
    "task": "navigate",  
    "config": {  
      "url": "https://google.com",  
      "timeout": 30000,  
      "viewport": {  
        "width": 1280,  
        "height": 720  
      }  
    }  
  }'  
```  

2. **System Metrics**  
```bash  
curl http://localhost:8000/metrics  
```  

3. **Task Management**  
```bash  
# List tasks  
curl http://localhost:8000/tasks  

# Get task details  
curl http://localhost:8000/tasks/{task_id}  

# Create new task  
curl -X POST http://localhost:8000/tasks \  
  -H "Content-Type: application/json" \  
  -d '{"task": "navigate", "config": {...}}'  

# Update task  
curl -X PUT http://localhost:8000/tasks/{task_id} \  
  -H "Content-Type: application/json" \  
  -d '{"status": "completed"}'  

# Delete task  
curl -X DELETE http://localhost:8000/tasks/{task_id}  
```  

## Configuration  

The system can be configured via the `.env` file. Key settings include:  

- **Database**: PostgreSQL configurations  
- **Server**: Host and port  
- **Playwright**: Browser paths and headless mode  
- **Logging**: Log level and output file  
- **Security**: Secret key and allowed origins  
- **Cache**: Time-to-live and activation  
- **Sessions**: Timeout and maximum number  

## Monitoring  

The system collects detailed metrics on:  

- Task execution time  
- Resource usage (CPU, memory, disk)  
- Session statistics  
- Errors and exceptions  
- API response time  

## Contributing  

1. Fork the project  
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)  
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)  
4. Push to the branch (`git push origin feature/AmazingFeature`)  
5. Open a Pull Request  

## License  

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

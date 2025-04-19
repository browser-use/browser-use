FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/root/.local/bin:$PATH"
ENV DISPLAY=:99
ENV DEBIAN_FRONTEND=noninteractive
# Create non-root user
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app && \
    chown appuser:appuser /app

# Configure apt to be more robust
RUN echo 'Acquire::Retries "3";' > /etc/apt/apt.conf.d/80retries && \
    echo 'Acquire::http::Timeout "120";' >> /etc/apt/apt.conf.d/80retries && \
    echo 'Acquire::ftp::Timeout "120";' >> /etc/apt/apt.conf.d/80retries

# Clear cache and install basic dependencies
RUN apt-get clean && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    ca-certificates \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*


# Install system dependencies in stages
RUN apt-get clean && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    xvfb \
    libgconf-2-4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libnspr4 \
    libnss3 \
    && rm -rf /var/lib/apt/lists/*

# Install only essential fonts
RUN apt-get clean && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    fonts-liberation \
    x11-utils \
    && rm -rf /var/lib/apt/lists/*

# Install development dependencies
RUN apt-get clean && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    make \
    gcc \
    g++ \
    git \
    procps \
    dbus \
    curl \
    python3-dev \
    libpq-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install Rust
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
RUN echo 'source /root/.cargo/env' >> $HOME/.bashrc

# Install additional Playwright dependencies
RUN apt-get clean && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \
    fastapi==0.104.0 \
    uvicorn==0.24.0 \
    playwright==1.51.0 \
    sqlalchemy[postgresql]==2.0.40 \
    asyncpg==0.29.0 \
    psycopg2-binary==2.9.10 \
    python-dotenv==1.0.0 \
    pydantic==2.10.4 \
    pydantic-settings>=2.1.0 \
    python-jose[cryptography]==3.3.0 \
    passlib[bcrypt]==1.7.4 \
    python-multipart==0.0.6 \
    aiohttp==3.9.3 \
    httpx==0.25.2 \
    psutil==5.9.6 \
    alembic==1.12.1 \
    greenlet==3.1.1 \
    posthog==3.7.0 \
    sentence-transformers>=4.0.2 \
    mem0ai==0.1.88 \
    screeninfo==0.8.1 \
    requests>=2.32.3

# Install required LangChain packages
RUN pip install --no-cache-dir langchain==0.3.21
RUN pip install --no-cache-dir langchain_core==0.3.49
RUN pip install --no-cache-dir langchain-openai==0.3.11
# Install Playwright browsers
ENV PLAYWRIGHT_BROWSERS_PATH=/usr/local/share/playwright
RUN playwright install --with-deps chromium firefox webkit
RUN playwright install-deps

# Create directory for logs
RUN mkdir -p /var/log/browser-use && \
    chown appuser:appuser /var/log/browser-use

# Set working directory
WORKDIR /app

# Copy application code
COPY . .

# Set permissions
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Command to start the application
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
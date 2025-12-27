# PowerShell script to build and run the dev Docker image with docker-compose
# Run this from repository root: .\examples\docker\dev-run.ps1

# Build and Run using BuildKit
docker compose -f docker-compose.yml up --build -d

Write-Host "Container started. To follow logs: docker compose logs -f"
Write-Host "To stop: docker compose down"

from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Configurações da API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_WORKERS: int = 1
    API_RELOAD: bool = False

    # Configurações do navegador
    BROWSER_USE_HEADLESS: bool = True
    BROWSER_TIMEOUT: int = 30000
    BROWSER_VIEWPORT_WIDTH: int = 1280
    BROWSER_VIEWPORT_HEIGHT: int = 720

    # Configurações do banco de dados
    DATABASE_URL: str = "sqlite:///./browser_use.db"

    # Configurações de autenticação
    API_KEY: Optional[str] = None

    model_config = {
        "protected_namespaces": (),
        "env_file": ".env",
        "case_sensitive": True
    }

settings = Settings() 
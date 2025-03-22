from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import uvicorn
import os

# 加载环境变量
load_dotenv()

app = FastAPI(title="API Service")

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 健康检查路由
@app.get("/api/health", include_in_schema=False)
async def health_check():
    return {"status": "ok"}

# 导入其他路由
from .routes import router
from .routes import public_router
app.include_router(router, prefix="/api/v1")
app.include_router(public_router, prefix="/api/v1")

def start():
    """启动服务器"""
    port = int(os.getenv("API_PORT", 18000))
    host = os.getenv("API_HOST", "0.0.0.0")
    
    uvicorn.run(
        "src.api.server:app",
        host=host,
        port=port,
        reload=True  # 开发模式下启用热重载
    )

if __name__ == "__main__":
    start() 
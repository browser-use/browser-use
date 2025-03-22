import os
import oss2
import logging
import base64
import uuid
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

class OSSUploader:
    def __init__(self):
        # 从环境变量获取 OSS 配置
        self.access_key_id = os.environ.get('OSS_ACCESS_KEY_ID')
        self.access_key_secret = os.environ.get('OSS_ACCESS_KEY_SECRET')
        self.endpoint = os.environ.get('OSS_ENDPOINT')
        self.bucket_name = os.environ.get('OSS_BUCKET_NAME')
        
        if not all([self.access_key_id, self.access_key_secret, self.endpoint, self.bucket_name]):
            raise ValueError("Missing required OSS configuration in environment variables")
        
        # 初始化 OSS 客户端
        self.auth = oss2.Auth(self.access_key_id, self.access_key_secret)
        self.bucket = oss2.Bucket(self.auth, self.endpoint, self.bucket_name)

    def _generate_file_path(self, file_name: str) -> str:
        """生成 OSS 存储路径"""
        return f"co-project/{file_name}"

    async def upload_file(self, file_path: str, custom_filename: Optional[str] = None) -> str:
        """
        上传文件到 OSS
        
        Args:
            file_path: 本地文件路径
            custom_filename: 自定义文件名（可选）
        
        Returns:
            str: 文件的 URL
        """
        try:
            # 获取原始文件名
            original_filename = os.path.basename(file_path)
            # 使用自定义文件名或原始文件名
            file_name = custom_filename or original_filename
            
            # 生成 OSS 存储路径
            oss_path = self._generate_file_path(file_name)
            
            # 上传文件
            with open(file_path, 'rb') as f:
                result = self.bucket.put_object(oss_path, f)
            
            if result.status == 200:
                # 构建并返回文件 URL
                url = f"https://{self.bucket_name}.{self.endpoint}/{oss_path}"
                logger.info(f"File uploaded successfully: {url}")
                return url
            else:
                raise Exception(f"Upload failed with status code: {result.status}")
                
        except Exception as e:
            logger.error(f"Error uploading file to OSS: {str(e)}")
            raise

    async def upload_bytes(self, file_content: bytes, file_name: str) -> str:
        """
        上传字节数据到 OSS
        
        Args:
            file_content: 文件内容（字节格式）
            file_name: 文件名
            
        Returns:
            str: 文件的 URL
        """
        try:
            # 生成 OSS 存储路径
            oss_path = self._generate_file_path(file_name)
            
            # 上传文件内容
            result = self.bucket.put_object(oss_path, file_content)
            
            if result.status == 200:
                # 构建并返回文件 URL
                url = f"https://{self.bucket_name}.{self.endpoint}/{oss_path}"
                logger.info(f"File uploaded successfully: {url}")
                return url
            else:
                raise Exception(f"Upload failed with status code: {result.status}")
                
        except Exception as e:
            logger.error(f"Error uploading bytes to OSS: {str(e)}")
            raise

    async def delete_file(self, file_url: str) -> bool:
        """
        从 OSS 删除文件
        
        Args:
            file_url: 文件的完整 URL
            
        Returns:
            bool: 删除是否成功
        """
        try:
            # 从 URL 提取 OSS 路径
            oss_path = file_url.split(f"{self.bucket_name}.{self.endpoint}/")[-1]
            
            # 删除文件
            result = self.bucket.delete_object(oss_path)
            
            if result.status == 204:  # OSS 删除成功返回 204
                logger.info(f"File deleted successfully: {file_url}")
                return True
            else:
                raise Exception(f"Delete failed with status code: {result.status}")
                
        except Exception as e:
            logger.error(f"Error deleting file from OSS: {str(e)}")
            raise

    async def upload_base64(self, base64_data: str, file_extension: str = ".png") -> str:
        """
        上传 base64 编码的文件到 OSS
        
        Args:
            base64_data: base64 编码的文件内容（可以包含或不包含 data:image/xxx;base64, 前缀）
            file_extension: 文件扩展名（默认为.png）
            
        Returns:
            str: 文件的 URL
        """
        try:
            # 移除可能存在的 base64 前缀
            if ';base64,' in base64_data:
                base64_data = base64_data.split(';base64,')[1]
            
            # 解码 base64 数据
            file_content = base64.b64decode(base64_data)
            
            # 生成随机文件名
            file_name = f"{uuid.uuid4()}{file_extension}"
            
            # 使用 upload_bytes 方法上传
            await self.upload_bytes(file_content, file_name)
            image_url = self.get_file_url(file_name)
            return image_url
                
        except Exception as e:
            logger.error(f"Error uploading base64 to OSS: {str(e)}")
            raise 

    def get_file_url(self, file_name: str) -> str:
        """
        根据文件名获取 OSS 文件的完整 URL
        
        Args:
            file_name: 文件名
            
        Returns:
            str: 文件的完整 URL
        """
        try:
            # 生成 OSS 存储路径
            oss_path = self._generate_file_path(file_name)
            
            # 检查文件是否存在
            exists = self.bucket.object_exists(oss_path)
            if not exists:
                raise FileNotFoundError(f"File {file_name} does not exist in OSS")
            
            # 构建并返回文件 URL
            url = f"https://{self.bucket_name}.{self.endpoint}/{oss_path}"
            return url
                
        except Exception as e:
            logger.error(f"Error getting file URL from OSS: {str(e)}")
            raise

    def get_file_url_without_check(self, file_name: str) -> str:
        """
        根据文件名获取 OSS 文件的完整 URL（不检查文件是否存在）
        
        Args:
            file_name: 文件名
            
        Returns:
            str: 文件的完整 URL
        """
        # 生成 OSS 存储路径
        oss_path = self._generate_file_path(file_name)
        
        # 构建并返回文件 URL
        return f"https://{self.bucket_name}.{self.endpoint}/{oss_path}" 
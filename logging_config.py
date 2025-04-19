import logging
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime
import json
import traceback
from typing import Any, Dict

class CustomFormatter(logging.Formatter):
    """Formatação personalizada para logs"""
    
    def format(self, record):
        # Adiciona timestamp em ISO format
        record.iso_timestamp = datetime.utcnow().isoformat()
        
        # Adiciona traceback se houver
        if record.exc_info:
            record.traceback = traceback.format_exc()
        else:
            record.traceback = None
            
        # Formata a mensagem como JSON
        log_data = {
            "timestamp": record.iso_timestamp,
            "level": record.levelname,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "message": record.getMessage(),
            "traceback": record.traceback
        }
        
        # Adiciona contexto extra se existir
        if hasattr(record, 'context'):
            log_data['context'] = record.context
            
        return json.dumps(log_data, ensure_ascii=False)

def setup_logging():
    """Configura o sistema de logging"""
    
    # Cria diretório de logs se não existir
    log_dir = os.getenv('LOG_DIR', '/var/log/browser-use')
    os.makedirs(log_dir, exist_ok=True)
    
    # Configura o logger principal
    logger = logging.getLogger('browser-use')
    logger.setLevel(logging.DEBUG)
    
    # Remove handlers existentes
    logger.handlers = []
    
    # Configura handler para arquivo
    log_file = os.path.join(log_dir, 'app.log')
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(CustomFormatter())
    
    # Configura handler para console
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(CustomFormatter())
    
    # Adiciona handlers ao logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    # Configura loggers específicos
    setup_module_logger('database', log_dir)
    setup_module_logger('browser', log_dir)
    setup_module_logger('api', log_dir)
    setup_module_logger('server', log_dir)
    
    return logger

def setup_module_logger(module_name: str, log_dir: str):
    """Configura logger específico para um módulo"""
    logger = logging.getLogger(f'browser-use.{module_name}')
    logger.setLevel(logging.DEBUG)
    
    # Handler específico para o módulo
    log_file = os.path.join(log_dir, f'{module_name}.log')
    handler = RotatingFileHandler(
        log_file,
        maxBytes=5*1024*1024,  # 5MB
        backupCount=3,
        encoding='utf-8'
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(CustomFormatter())
    
    logger.addHandler(handler)

def log_with_context(logger: logging.Logger, level: int, msg: str, context: Dict[str, Any] = None, exc_info=None):
    """Função auxiliar para log com contexto"""
    extra = {'context': context} if context else {}
    logger.log(level, msg, exc_info=exc_info, extra=extra)

# Funções de conveniência para diferentes níveis de log
def log_debug(logger: logging.Logger, msg: str, context: Dict[str, Any] = None):
    log_with_context(logger, logging.DEBUG, msg, context)

def log_info(logger: logging.Logger, msg: str, context: Dict[str, Any] = None):
    log_with_context(logger, logging.INFO, msg, context)

def log_warning(logger: logging.Logger, msg: str, context: Dict[str, Any] = None):
    log_with_context(logger, logging.WARNING, msg, context)

def log_error(logger: logging.Logger, msg: str, context: Dict[str, Any] = None, exc_info=None):
    log_with_context(logger, logging.ERROR, msg, context, exc_info)

def log_critical(logger: logging.Logger, msg: str, context: Dict[str, Any] = None, exc_info=None):
    log_with_context(logger, logging.CRITICAL, msg, context, exc_info) 
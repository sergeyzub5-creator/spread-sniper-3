import logging
import sys
from datetime import datetime

def setup_logger(level=logging.INFO):
    logger = logging.getLogger()
    logger.setLevel(level)
    logger.handlers.clear()
    
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    console.setStream(open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1))
    logger.addHandler(console)
    
    try:
        file_handler = logging.FileHandler(
            f'debug_{datetime.now().strftime("%Y%m%d")}.log', 
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except:
        pass
    
    return logger

def get_logger(name):
    return logging.getLogger(name)

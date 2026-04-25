import logging

def get_logger(name="orchestrator"):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    return logger

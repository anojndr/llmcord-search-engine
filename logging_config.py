"""
Logging Configuration Module

This module configures the application's logging system, setting up formatters
and handlers to ensure consistent logging across the application.
It should be imported and initialized at application startup.
"""

import logging
import os
import sys
from typing import Optional
from datetime import datetime


def setup_logging(
    log_level: str = "INFO", 
    log_file: Optional[str] = None
) -> None:
    """
    Set up logging configuration for the application.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to log file. If None, logs only to console.
    """
    # Create logs directory if it doesn't exist
    logs_dir = "logs"
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
    
    # If log_file is specified, ensure its directory exists
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
    
    # Set the numeric logging level
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"Invalid log level: {log_level}")
    
    # Base configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    
    # Clear existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Define formatter
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(log_format, date_format)
    
    # Console handler always enabled
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handler if log_file is specified
    if log_file:
        # Add timestamp to log filename if not present
        if '{timestamp}' in log_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_file = log_file.replace('{timestamp}', timestamp)
        
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    # Add separate handler for warning, error, and critical logs
    warnings_errors_file = os.path.join(logs_dir, "warnings_errors_criticals.txt")
    warnings_errors_handler = logging.FileHandler(warnings_errors_file)
    warnings_errors_handler.setLevel(logging.WARNING)
    warnings_errors_handler.setFormatter(formatter)
    root_logger.addHandler(warnings_errors_handler)
    
    # Log startup message
    logging.info(
        f"Logging initialized: level={log_level}, log_file={log_file or 'None'}, "
        f"warnings_errors_file={warnings_errors_file}"
    )
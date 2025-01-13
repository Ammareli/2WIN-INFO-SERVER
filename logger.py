# This is the globel logger for the whole project.

import logging
import os

# Create a directory for logs if it doesn't exist
log_dir = "logs"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# Define the log file path
log_file = os.path.join(log_dir, "info_server.log")

# Custom formatter to handle missing 'pid' field
class CustomFormatter(logging.Formatter):
    def format(self, record):
        
        if not hasattr(record, 'pid'):
            record.pid = os.getpid()  
        return super().format(record)


# Create a logging filter to dynamically include the process PID
class PIDFilter(logging.Filter):
    def __init__(self):
        super().__init__()
        self.pid = os.getpid()  

    def set_pid(self, pid):
        self.pid = pid

    def filter(self, record):
        
        record.pid = self.pid
        return True
    
# Initialize the PID filter
pid_filter = PIDFilter()

# Create a custom formatter that includes the PID
log_format = "%(asctime)s - [PID %(pid)s] - %(name)s - %(levelname)s - %(message)s"
formatter = CustomFormatter(log_format)

# Configure handlers
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)

file_handler = logging.FileHandler(log_file)
file_handler.setFormatter(formatter)

# Configure the logger
logger = logging.getLogger("2WinAlerts-INFO-SERVER")
logger.setLevel(logging.DEBUG)
logger.addHandler(stream_handler)
logger.addHandler(file_handler)
logger.addFilter(pid_filter)

# Helper function to set the PID for the current worker
def set_worker_pid(pid):
    pid_filter.set_pid(pid)
    logger.info(f"Logger initialized for PID {pid}")
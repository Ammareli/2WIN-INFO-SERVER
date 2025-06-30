from logger import logger

def execute_comp(alert_type: str) :
    logger.info(f"Executing Splash The Cash with alert type: {alert_type}")
    comp_name= "Splash The Cash"
    return comp_name, alert_type
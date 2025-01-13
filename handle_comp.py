from comps.show_me_the_money import comp_send_me_money_data
from comps.january_jackpot import run_jan_jackpot
from constants import COMPS
from utilites import return_data_to_message_server
from logger  import logger

def run_comp(comp_name, alert_type):
    
    if not comp_name in COMPS:
        raise Exception(f"Invalid comp name: {comp_name}")
    
    if comp_name == 'Show Me The Money':
        logger.info(f"Running comp: {comp_name, alert_type}")
        data = comp_send_me_money_data()
        if data:
            result = return_data_to_message_server(data)  
        else:
            return
        if result:
            logger.info(f"Successfully sent data to message server for comp: {comp_name, alert_type}")
    if comp_name == 'January Jackpot':
        logger.info(f"Running comp: {comp_name, alert_type}")
        data = run_jan_jackpot(alert_type)
        if data:
            result = return_data_to_message_server(data)  
        else:
            return
        if result:
            logger.info(f"Successfully sent data to message server for comp: {comp_name, alert_type}")


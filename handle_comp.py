# from comps.show_me_the_money import comp_send_me_money_data
# from comps.make_me_a_Millionaire import comp_make_me_a_millionaire
# from comps.january_jackpot import run_jan_jackpot
from comps._35k_payday import run_35k_payday
from comps.splash import execute_comp
from constants import COMPS
from utilites import return_data_to_message_server
from logger  import logger

def run_comp(comp_name, alert_type):
    logger.info(f"Running comp: {comp_name, alert_type}")
    
    if not comp_name in COMPS:
        raise Exception(f"Invalid comp name: {comp_name}")
    
    # if comp_name == 'Show Me The Money':
    #     logger.info(f"Running comp: {comp_name, alert_type}")
    #     data = comp_send_me_money_data()
    #     if data:
    #         result = return_data_to_message_server(data)  
    #     else:
    #         return
    #     if result:
    #         logger.info(f"Successfully sent data to message server for comp: {comp_name, alert_type}")

    # if comp_name == 'January Jackpot':
    #     logger.info(f"Running comp: {comp_name, alert_type}")
    #     data = run_jan_jackpot(alert_type)
    #     if data is None:
    #         logger.info(f"No data received for comp: {comp_name}")
    #         return
    #     if data:
    #         result = return_data_to_message_server(data)  
    #     else:
    #         return
    #     if result:
    #         logger.info(f"Successfully sent data to message server for comp: {comp_name, alert_type}")

    # if comp_name == 'Make me a millionaire':
    #     logger.info(f"Running comp: {comp_name, alert_type}")
        
    #     data = comp_make_me_a_millionaire(alert_type)
        
    #     if data is None:
    #         logger.info(f"No data received for comp: {comp_name}")
    #         return
    #     if data:
    #         result = return_data_to_message_server(data)  
    #     else:
    #         return
    #     if result:
    #         logger.info(f"Successfully sent data to message server for comp: {comp_name, alert_type}")
    # if comp_name == '35k Payday':
    #     logger.info(f"Running comp: {comp_name, alert_type}")
    #     data = run_35k_payday(alert_type)
    #     if data is None:
    #         logger.info(f"No data received for comp: {comp_name}")
    #         return
    #     if data:
    #         result = return_data_to_message_server(data)  
    #     else:
    #         return
    #     if result:
    #         logger.info(f"Successfully sent data to message server for comp: {comp_name, alert_type}")

    if comp_name == 'Splash The Cash':
        logger.info(f"Running comp: {comp_name, alert_type}")
        
        data = execute_comp(alert_type)
        if data is None:
            logger.info(f"No data received for comp: {comp_name}")
            return
        if data:
            logger.info(f"Data to send: {data}")
            result = return_data_to_message_server(data)  
        else:
            return
        if result:
            logger.info(f"Successfully sent data to message server for comp: {comp_name, alert_type}")
    
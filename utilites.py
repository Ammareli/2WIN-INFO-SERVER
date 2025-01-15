# ALL THE REQUIRED UNTILITY FUNCTIONS WILL BE ADDED HERE.
import requests
from constants import AUTH, URL
from logger import logger
import json
import time

            
def get_compname_alerts(data):
    """
    Recursively search for alarms in the given data and retrieve comp_name, comp_id, and alarm_id.
    
    Args:
        data (dict or list): The data to search through.

    Returns:
        dict: A dictionary with 'comp_name', 'comp_id', and 'alarm_id' if found, otherwise None.
    """
    if isinstance(data, dict):
        # Check if the required keys are present in the current level
        if "COMP_NAME" in data and "COMP_ID" in data and "ALARM_ID" in data:
            return {
                "comp_name": data["COMP_NAME"],
                "comp_id": data["COMP_ID"],
                "alarm_id": data["ALARM_ID"]
            }
        # Recursively search deeper in the dictionary
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                result = get_compname_alerts(value)
                if result:
                    return result
    elif isinstance(data, list):
        # Iterate through the list and search for the required keys in each element
        for item in data:
            result = get_compname_alerts(item)
            if result:
                return result
    return None


def return_data_to_message_server(data):
    time.sleep(180)  # delay for 3 minutes only for beta testing
    comp_name = data[0]
    message_data = data[1]
    headers = {
    'Content-Type': 'application/json',
    'Authorization': AUTH
    }
    data = {
    'comp_name': comp_name,
    'message_data': message_data
    }
    response = requests.post(URL, headers=headers, json=data)
    logger.info(f"Message server response: {response}")
    if response.status_code == 200:
        logger.info(f"Successfully sent data to message server for comp DATA: {data}")
        return True
    else:
        return False

    
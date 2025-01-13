# ALL THE REQUIRED UNTILITY FUNCTIONS WILL BE ADDED HERE.
import requests
from constants import AUTH, URL
from logger import logger

            
def get_compname_alerts(data):
    """Check for any alarm ID in the data recursively"""
    if isinstance(data, dict):
        # First check for ALARM_ID in custom_files structure
        if 'data' in data and 'metadata' in data['data'] and 'custom_files' in data['data']['metadata']:
            for file in data['data']['metadata']['custom_files']:
                if 'ALARM_ID' in file and file['ALARM_ID'] and 'COMP_NAME' in file and file['COMP_NAME'] and 'COMP_ID' in file and file['COMP_ID']:
                    return [file['ALARM_ID'], file['COMP_NAME'], file['COMP_ID']]
        


def return_data_to_message_server(data):
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
        return True
    else:
        return False

    
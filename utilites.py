# ALL THE REQUIRED UNTILITY FUNCTIONS WILL BE ADDED HERE.
import requests
from constants import AUTH, URL
from logger import logger
import json

            
def get_compname_alerts(data):
    """Check for any alarm ID in the data recursively"""
    if isinstance(data, dict):
        # First check for ALARM_ID in custom_files structure
        if 'data' in data and 'metadata' in data['data'] and 'custom_files' in data['data']['metadata']:
            for file in data['data']['metadata']['custom_files']:
                if 'user_defined' in file:
                    user_defined_data = json.loads(file['user_defined'])
                    if 'ALARM_ID' in user_defined_data and 'COMP_NAME' in user_defined_data and 'COMP_ID' in user_defined_data:
                        return [
                             user_defined_data['COMP_NAME'],
                             user_defined_data['ALARM_ID'],
                             user_defined_data['COMP_ID']
                        ]
    return None        


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

    
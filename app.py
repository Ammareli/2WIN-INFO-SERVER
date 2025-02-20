# This is the main server for the app.
# PROJECT NAME: 2WIN - info server
# DEVELOPER : AMMAR ALI 
# COPYRIGHT RESERVED: GLOBEL 

from flask import Flask, request, jsonify
from logger import logger
from constants import LOG_FILE_PATH,NOTES_FILE_PATH
from flask import render_template, request
from redis_cache import RedisContactManager
import markdown
from utilites import get_compname_alerts
from handle_comp import run_comp
from threading import Thread


# Initialize the RedisContactManager
contact_manager = RedisContactManager()

# Set up Flask app and ThreadPoolExecutor
app = Flask(__name__)


def process_alarm(data):
    logger.info(f"Started COMP PROCESSING")
    logger.info(f"Received callback data: {data}")
    alert_data = get_compname_alerts(data)
    if not alert_data:
        logger.error("No alert data found in the callback")
        return
    comp_alert = (alert_data["comp_name"], alert_data["alarm_id"])
    logger.info(f"Received callback data for comp: {comp_alert[0]}")
    logger.info(f"Alert type: {comp_alert[1]}")
    # SAVE THE COMP NAME SO THE ALARMS WONT PROCESSED AGAIN.
    if contact_manager.redis_client.exists(comp_alert[0]):
        logger.info("This comp has already been processed cannot process process the comp after 120s")
        return
    else:
        contact_manager.redis_client.set(comp_alert[0],"processing",ex=180)
    if comp_alert[0] and comp_alert[1]:
        run_comp(comp_name=comp_alert[0], alert_type=comp_alert[1],data = data)
    else:
        run_comp(comp_name=None, alert_type=None, data =data)

    logger.info(f"COMP PROCESSING COMPLETED")

@app.route('/info-server')
def test_route():
    # Read the notes.txt file
    with open(NOTES_FILE_PATH, 'r') as file:
        notes_content = file.read()
    
    # Convert Markdown content to HTML
    notes_html = markdown.markdown(notes_content)
    
    # Read the log file
    with open(LOG_FILE_PATH, 'r') as file:
        log_content = file.read()
    
    return render_template('test.html', notes_html=notes_html, log_content=log_content)


@app.route('/callback', methods=['POST'])
def handle_callback():
    data = request.json
    logger.info(f"Received callback data: {data}")

    Thread(target=process_alarm, args=(data,)).start()
    return jsonify({'status': 'success'}), 200  

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=8000)
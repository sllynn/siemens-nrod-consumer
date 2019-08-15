import json
import stomp
import boto3
import socket
import os
import time


MSG_BROKER_HOST = "datafeeds.networkrail.co.uk"
MSG_BROKER_PORT = 61618
MSG_BROKER_USERNAME = os.getenv("MSG_BROKER_USERNAME")
MSG_BROKER_PASSWORD = os.getenv("MSG_BROKER_PASSWORD")
TOPIC = "/topic/TRAIN_MVT_HY_TOC"
CLIENT_ID = socket.getfqdn()
HEARTBEAT_INTERVAL_MS = 15000
RECONNECT_DELAY_SECS = 15
POLL_INTERVAL_SECS = 1
POLL_ATTEMPTS = 90
KINESIS_STREAM = "nrod-siemens"


class StompClient(stomp.ConnectionListener):
    def __init__(self):
        self.kinesis_client = boto3.client("kinesis")

    def on_heartbeat(self):
        print('Received a heartbeat')

    def on_heartbeat_timeout(self):
        print('ERROR: Heartbeat timeout')

    def on_error(self, headers, message):
        print('ERROR: %s' % message)

    def on_disconnected(self):
        print('Disconnected waiting %s seconds before exiting' % RECONNECT_DELAY_SECS)
        time.sleep(RECONNECT_DELAY_SECS)
        exit(-1)

    def on_connecting(self, host_and_port):
        print('Connecting to {h}'.format(h=host_and_port[0]))

    def on_message(self, headers, message):
        try:
            print('\n---\nGot message %s' % message)
        except Exception as e:
            print("\n\tError: %s\n--------\n" % str(e))
        msgs = json.loads(message)
        self.kinesis_client.put_records(
            Records=[dict(Data=json.dumps(msg), PartitionKey=msg["body"]["train_id"]) for msg in msgs],
            StreamName="nrod-siemens")


def connect_and_subscribe(connection):
    connection.start()

    connect_header = {'client-id': MSG_BROKER_USERNAME + '-' + CLIENT_ID}
    subscribe_header = {
        'activemq.subscriptionName': CLIENT_ID,
        'activemq.prefetchSize': 1
    }
    connection.connect(username=MSG_BROKER_USERNAME,
                       passcode=MSG_BROKER_PASSWORD,
                       wait=True,
                       headers=connect_header)

    connection.subscribe(destination=TOPIC,
                         id='1',
                         ack='auto',
                         headers=subscribe_header)

def lambda_handler(event, context):
    """Sample pure Lambda function

    Parameters
    ----------
    event: dict, required
        API Gateway Lambda Proxy Input Format

        Event doc: https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html#api-gateway-simple-proxy-for-lambda-input-format

    context: object, required
        Lambda Context runtime methods and attributes

        Context doc: https://docs.aws.amazon.com/lambda/latest/dg/python-context-object.html

    Returns
    ------
    API Gateway Lambda Proxy Output Format: dict

        Return doc: https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html
    """

    if not MSG_BROKER_PASSWORD:
        return dict(
            statusCode=401,
            body=json.dumps(dict(message="no password supplied"))
        )

    conn = stomp.Connection12([(MSG_BROKER_HOST, MSG_BROKER_PORT)],
                              auto_decode=False,
                              heartbeats=(HEARTBEAT_INTERVAL_MS, HEARTBEAT_INTERVAL_MS))

    conn.set_listener('', StompClient())
    connect_and_subscribe(conn)

    for _ in range(POLL_ATTEMPTS):
        time.sleep(POLL_INTERVAL_SECS)

    conn.disconnect()

    return dict(
        statusCode=200,
        body=json.dumps(dict(message="polling complete, terminating"))
    )

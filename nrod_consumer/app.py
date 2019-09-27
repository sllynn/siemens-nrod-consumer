import json
import stomp
import boto3
import base64
import socket
import os
import time

from botocore.exceptions import ClientError

CLIENT_ID = socket.getfqdn()
HEARTBEAT_INTERVAL_MS = 15000
RECONNECT_DELAY_SECS = 15
POLL_INTERVAL_SECS = 1
POLL_ATTEMPTS = 90


class StompClient(stomp.ConnectionListener):

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
        print("Received message")
        try:
            kinessis_put_records(message)
        except Exception as e:
            print("\n\tError: %s\n--------\n" % str(e))


def kinessis_put_records(message):
    msgs = json.loads(message)
    kinesis_client = boto3.client("kinesis")
    kinesis_client.put_records(
        Records=[dict(Data=json.dumps(msg), PartitionKey=msg["body"]["train_id"]) for msg in msgs],
        StreamName=os.getenv("KINESIS_STREAM"))


def get_secret(secret_name):
    region_name = "us-west-2"

    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    # In this sample we only handle the specific exceptions for the 'GetSecretValue' API.
    # See https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
    # We rethrow the exception by default.

    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as e:
        if e.response['Error']['Code'] == 'DecryptionFailureException':
            # Secrets Manager can't decrypt the protected secret text using the provided KMS key.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
        elif e.response['Error']['Code'] == 'InternalServiceErrorException':
            # An error occurred on the server side.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
        elif e.response['Error']['Code'] == 'InvalidParameterException':
            # You provided an invalid value for a parameter.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
        elif e.response['Error']['Code'] == 'InvalidRequestException':
            # You provided a parameter value that is not valid for the current state of the resource.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
        elif e.response['Error']['Code'] == 'ResourceNotFoundException':
            # We can't find the resource that you asked for.
            # Deal with the exception here, and/or rethrow at your discretion.
            raise e
    else:
        # Decrypts secret using the associated KMS CMK.
        # Depending on whether the secret is a string or binary, one of these fields will be populated.
        if 'SecretString' in get_secret_value_response:
            return get_secret_value_response['SecretString']
        else:
            return base64.b64decode(get_secret_value_response['SecretBinary'])


def connect_and_subscribe(connection, credentials, topic):
    connection.start()

    connect_header = {'client-id': credentials["MSG_BROKER_USERNAME"] + '-' + CLIENT_ID}
    subscribe_header = {
        'activemq.subscriptionName': CLIENT_ID,
        'activemq.prefetchSize': 1
    }
    connection.connect(username=credentials["MSG_BROKER_USERNAME"],
                       passcode=credentials["MSG_BROKER_PASSWORD"],
                       wait=True,
                       headers=connect_header)

    connection.subscribe(destination=topic,
                         id='1',
                         ack='auto',
                         headers=subscribe_header)


def lambda_handler(event, context):
    """Sample pure Lambda function

    Parameters
    ----------
    event: dict, required
    context: object, required
    Returns
    ------
    API Gateway Lambda Proxy Output Format: dict
    """

    conn = stomp.Connection12([(os.getenv("MSG_BROKER_HOST"), os.getenv("MSG_BROKER_PORT"))],
                              auto_decode=False,
                              heartbeats=(HEARTBEAT_INTERVAL_MS, HEARTBEAT_INTERVAL_MS))

    conn.set_listener('', StompClient())
    connect_and_subscribe(
        connection=conn,
        credentials=json.loads(get_secret(os.getenv("SECRET_NAME"))),
        topic=os.getenv("MSG_BROKER_TOPIC"))

    for _ in range(POLL_ATTEMPTS):
        time.sleep(POLL_INTERVAL_SECS)

    conn.disconnect()

    return dict(
        statusCode=200,
        body=json.dumps(dict(message="polling complete, terminating"))
    )

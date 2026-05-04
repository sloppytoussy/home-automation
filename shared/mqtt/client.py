import os
import paho.mqtt.client as mqtt


def get_client(client_id: str, on_message=None) -> mqtt.Client:
    client = mqtt.Client(client_id=client_id)
    if os.environ.get("MQTT_USERNAME"):
        client.username_pw_set(os.environ["MQTT_USERNAME"], os.environ["MQTT_PASSWORD"])
    if on_message:
        client.on_message = on_message
    client.connect(os.environ["MQTT_HOST"], int(os.environ.get("MQTT_PORT", 1883)))
    return client

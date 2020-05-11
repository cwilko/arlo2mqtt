from arlo import Arlo
import paho.mqtt.client as mqtt
import threading
import time
import queue
import json
import os

USERNAME = os.environ.get('ARLO_USERNAME')
PASSWORD = os.environ.get('ARLO_PASSWORD')
MQTT_HOST = os.environ.get('MQTT_HOST')
MQTT_PORT = int(os.environ.get('MQTT_PORT'))
INTERVAL = int(os.environ.get('INTERVAL'))

id_map = {
    "52M1837KA799C":"Front Door",
    "59U18177AF155":"Driveway",
    "A021927FA04D2":"Back Door"
    }

class ArloHandler:
    def __init__(self, mqttClient):
        self.mqttClient = mqttClient

    def __call__(self, arlo, event):
        print(event)

        if ("cameras/" in event['resource']) and (event.get('properties', {}).get('motionDetected')):
            # Motion detected - notify to MQTT

            cam_id = event['resource'].split("/",1)[1]
            cam_name = id_map[cam_id]

            self.mqttClient.publish("events/home/sensor/arlo/"+cam_name+"/motion/priority/OK", "Motion detected on camera: " + cam_name)
               
            basestations = arlo.GetDevices('basestation')

            # Here you will have access to self, the basestation JSON object, and the event schema.
            print("motion event detected!")

            # Get the list of devices and filter on device type to only get the cameras.
            # This will return an array of cameras, including all of the cameras' associated metadata.
            cameras = arlo.GetDevices('camera')
            camera = next((x for x in cameras if x["deviceId"] == cam_id), None)

            if (camera is not None):

                url = camera["presignedLastImageUrl"]
                ts =  camera["lastModified"]
                print(url)
                #print(datetime.datetime.fromtimestamp(ts/1000.0))

                # Wait for cam to start recording
                time.sleep(4)

                try:
                    arlo.request.post('https://my.arlo.com/hmsweb/users/devices/takeSnapshot', {'xcloudId':camera.get('xCloudId'),'parentId':camera.get('parentId'),'deviceId':camera.get('deviceId'),'olsonTimeZone':camera.get('properties', {}).get('olsonTimeZone')}, headers={"xcloudId":camera.get('xCloudId')})
                except Exception as e:
                    print("Failed to request snapshot")
                    print(e)

        elif ("cameras" in event["resource"]) and (isinstance(event["properties"],list)):

            # Get Camera state and send to MQTT
            for x in event["properties"]:
                cam_name = id_map[x["serialNumber"]]

                data = {
                    "device": cam_name,
                    "id": x["serialNumber"],
                    "batteryLevel": x["batteryLevel"],
                    "signalStrength": x["signalStrength"],
                    "connectionState": x["connectionState"]
                }   

                self.mqttClient.publish("sensors/arlo/" + cam_name, str(data))   

        elif "mediaUploadNotification" in event['resource'] :
            # Snapshot generated - notify to MQTT
            if "snapshot" in event["presignedContentUrl"]:
                #arlo.DownloadSnapshot(event["presignedContentUrl"], 'snapshot.jpg')  
                cam_name = id_map[event["deviceId"]]
                self.mqttClient.publish("events-json/home/sensor/arlo/"+cam_name+"/snapshot/priority/OK", json.dumps({ "msg": "Snapshot captured on camera: " + cam_name, "url": event["presignedContentUrl"]}))

def stateEventGenerator(arlo, basestation):
    while True:
        try:
            time.sleep(INTERVAL)

            arlo.Notify(basestation, {"action":"get","resource":"cameras","publishResponse":False})

        except Exception as e:
            print("Failed to request state information from Basestation")
            print(e)
            # Wait before retrying
            time.sleep(INTERVAL)


## Initiate MQTT client
client = mqtt.Client()
client.connect(MQTT_HOST, MQTT_PORT, 60)

# Instantiating the Arlo object automatically calls Login(), which returns an oAuth token 
# that gets cached. Subsequent successful calls to login will update the oAuth token.
arlo = Arlo(USERNAME, PASSWORD)
# At this point you're logged into Arlo.

# Get the list of devices and filter on device type to only get the basestation.
# This will return an array which includes all of the basestation's associated metadata.
basestations = arlo.GetDevices('basestation')

x = threading.Thread(target=stateEventGenerator, args=(arlo, basestations[0]))
x.start()

while True:
    try:
        print('Listen for ARLO events...')
        arlo.HandleEvents(basestations[0], ArloHandler(client))
    except queue.Empty as e:
        continue
    except Exception as e:
        print("Error during event loop")
        print(e)
        break


#!/usr/bin/env python
import rospy

from signal import signal, SIGINT, SIG_DFL

import websocket

from rosbridge_library.rosbridge_protocol import RosbridgeProtocol
from rosbridge_library.util import json

# Globals for now (should be class properties)
protocol = None
ws = None

def on_message(ws, message):
    print "Msg received: [%s]" % message
    protocol.incoming(message)

def send_message(message):
    ws.send(message)
    print "Msg sent: [%s]" % message

def on_error(ws, error):
    print "Error! %s" % error

def on_close(ws):
    pass

def on_open(ws):
    ws.send('{"op":"proxy"}')

if __name__ == "__main__":
    rospy.init_node("rosbridge_websocket_client")
    signal(SIGINT, SIG_DFL)

    protocol = RosbridgeProtocol(0)
    protocol.outgoing = send_message

    # Manually subscribe to chatter message
    # on_message(ws, '{"op":"subscribe","id":"subscribe:/chatter:1","type":"std_msgs/String","topic":"/chatter","compression":"none","throttle_rate":0}')

    ws = websocket.WebSocketApp("ws://10.34.0.13:9090/",
                              on_message = on_message,
                              on_error = on_error,
                              on_open = on_open,
                              on_close = on_close)

    ws.run_forever()

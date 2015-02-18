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
    pass

def on_close(ws):
    pass

def on_open(ws):
    pass

if __name__ == "__main__":
    rospy.init_node("rosbridge_websocket_client")
    signal(SIGINT, SIG_DFL)

    protocol = RosbridgeProtocol(0)
    protocol.outgoing = send_message

    ws = websocket.WebSocketApp("ws://localhost:9090/",
                              on_message = on_message,
                              on_error = on_error,
                              on_close = on_close)

    ws.on_open = on_open
    ws.run_forever()

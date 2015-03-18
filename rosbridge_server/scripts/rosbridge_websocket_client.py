#!/usr/bin/env python
import rospy
import signal
import tornado.httpclient
import base64


from tornado.websocket import websocket_connect
from tornado.ioloop import IOLoop

from datetime import timedelta

from rosbridge_library.rosbridge_protocol import RosbridgeProtocol
from rosbridge_library.util import json

PING_TIMEOUT = 15

ws = None
protocol = None

webserver_port = 8080

# WebsocketClientTornado
#
# Class that handles the connection using websocket from Tornado Project.
# More info:
# http://www.tornadoweb.org/en/stable/websocket.html#client-side-support
# Example code: http://www.seismicportal.eu/realtime.html


class WebsocketClientTornado():
    conn = None
    keepalive = None

    def __init__(self, uri):
        self.uri = uri
        self.doconn()

    def doconn(self):
        rospy.loginfo("trying connection to %s" % (self.uri,))
        w = websocket_connect(self.uri)
        rospy.loginfo("connected, waiting for messages")
        w.add_done_callback(self.wsconnection_cb)

    def dokeepalive(self):
        stream = self.conn.protocol.stream
        if not stream.closed():
            self.keepalive = stream.io_loop.add_timeout(
                timedelta(seconds=PING_TIMEOUT), self.dokeepalive)
            self.conn.protocol.write_ping("")
        else:
            self.keepalive = None  # should never happen

    def wsconnection_cb(self, conn):
        self.conn = conn.result()
        # TODO check result
        self.conn.on_message = self.message
        self.send_message('{"op":"proxy"}')
        self.keepalive = IOLoop.instance().add_timeout(
            timedelta(seconds=PING_TIMEOUT), self.dokeepalive)

    def message(self, _message):
        #print "Msg received: [%s]" % _message
        msg = json.loads(_message)
        if msg['op'] == 'video':
            rospy.loginfo("RECEIVED VIDEO MSG")
            try:
                c = VideoTransfer("http://localhost:8080/stream?topic=/usb_cam_node/image_raw",self)
            except e:
                print "Could not connect to WebCam"
                print e
                rospy.loginfo("Could not connect to WebCam")
                self.send_message('{"op":"endVideo"}')
        elif msg['op'] == "endVideo":
            #TODO Resolve stop from client
            pass
        else:
            protocol.incoming(_message)

    def close(self):
        rospy.loginfo('connection closed')
        if self.keepalive is not None:
            keepalive = self.keepalive
            self.keepalive = None
            IOLoop.instance().remove_timeout(keepalive)
        self.doconn()

    def send_message(self, _message):
        self.conn.write_message(_message)
        #print "Msg sent: [%s]" % _message

class VideoTransfer():
    def __init__(self, url, connection):
        self.conn = connection
        req = tornado.httpclient.HTTPRequest(
            url = url,
            streaming_callback = self.streaming_callback)
        http_client = tornado.httpclient.AsyncHTTPClient()
        http_client.fetch(req, self.async_callback)
        print "fetch finished"

    def streaming_callback(self, data):
        "Sends video in chunks"
        try:
            #print "Sending Video chunks"
            encoded = base64.b64encode(data)   # Encode in Base64 & make json
            chunk = json.dumps({"op": "video", "data": encoded})
            self.conn.send_message(chunk)
        except Exception as e:
            print e

    def async_callback(self, response):
        self.conn.finish()


if __name__ == "__main__":
    try:
        rospy.init_node("rosbridge_websocket_client")

        io_loop = IOLoop.instance()
        signal.signal(signal.SIGTERM, io_loop.stop)
        protocol = RosbridgeProtocol(0)

        # Connect with server
        server_uri = rospy.get_param("~webserver_uri")
        # In the future we are going need to use everithing on the same port
        # given throught the argument
        ws = WebsocketClientTornado(server_uri)
        protocol.outgoing = ws.send_message

        # Loop
        IOLoop.instance().start()

    except rospy.ROSInterruptException:
        IOLoop.instance().stop()

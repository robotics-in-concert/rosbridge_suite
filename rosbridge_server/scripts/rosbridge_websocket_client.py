#!/usr/bin/env python
import rospy
import signal
import base64
import urllib
import time

from rosauth.srv import UserAuthentication

from tornado.httpclient import HTTPRequest, AsyncHTTPClient
from tornado.websocket import websocket_connect
from tornado.ioloop import IOLoop

from datetime import timedelta

from rosbridge_library.rosbridge_protocol import RosbridgeProtocol
from rosbridge_library.util import json

PING_TIMEOUT = 15

ws = None
protocol = None
user_auth = False
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
        self.authenticated = False
        self.uri = uri
        self.doconn()

    def doconn(self):
        global user_auth
        try:
            rospy.loginfo("trying connection to %s" % (self.uri,))
            w = websocket_connect(self.uri)
            rospy.loginfo("connected, waiting for messages")
            w.add_done_callback(self.wsconnection_cb)
        except Exception as e:
            rospy.logerror(e)
            rospy.logerror("There was an exception")

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
        global user_auth
        #print "Msg received: [%s]" % _message
        msg = json.loads(_message)
        if msg['op'] == 'video':
            try:
                args = msg['args']
                self.transfer = VideoTransfer("http://localhost:8080/stream",
                                              args, self)
            except Exception as e:
                rospy.logerror("Could not connect to WebCam")
                rospy.logerror(e)
                self.send_message('{"op":"endVideo"}')
        elif msg['op'] == "endVideo":
            #TODO Resolve stop from client
            self.transfer.endVideo()
            pass
        elif msg['op'] == 'auth':
            try:
                # check the authorization information
                if user_auth and not self.authenticated:
                    auth_srv = rospy.ServiceProxy('/authenticate_user',
                                                  UserAuthentication)
                    resp = auth_srv(msg['user'], msg['pass'])
                    self.authenticated = resp.authenticated
                    if self.authenticated:
                        rospy.loginfo("Client has authenticated")
                        return
                    # if we are here, no valid authentication was given
                    rospy.logwarn("Client did not authenticate. Closing "
                                  "connection.")
                    # TODO: INSTRUCT TO THE SERVER TO DISCONNECT
            except Exception as e:
                rospy.logerr("Exception during authentication %s", e)
                # proper error will be handled in the protocol class
                self.protocol.incoming(_message)
        else:
            # no authentication required
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
    def __init__(self, url, args, connection):
        AsyncHTTPClient.configure("tornado.curl_httpclient."
                                  "CurlAsyncHTTPClient")
        self.conn = connection
        url = url + "?" + urllib.urlencode(args)
        url = url.replace("%2F", "/")
        req = HTTPRequest(url=url, streaming_callback=self.streaming_callback,
                          connect_timeout=0.0, request_timeout=0.0)
        http_client = AsyncHTTPClient()
        http_client.fetch(req, self.async_callback)
        self.start = time.time()

    def streaming_callback(self, data):
        "Sends video in chunks"
        try:
            encoded = base64.b64encode(data)   # Encode in Base64 & make json
            chunk = json.dumps({"op": "video", "data": encoded})
            self.conn.send_message(chunk)
        except Exception as e:
            print e

    def async_callback(self, response):
        print "Finished connection"

    def end_video(self):
        #TODO Manage end of video transfer
        pass

if __name__ == "__main__":
    try:
        rospy.init_node("rosbridge_websocket_client")

        io_loop = IOLoop.instance()
        signal.signal(signal.SIGTERM, io_loop.stop)
        protocol = RosbridgeProtocol(0)

        # Connect with server
        server_uri = rospy.get_param("~webserver_uri")
        user_auth = rospy.get_param('~user_auth', False)
        # In the future we are going need to use everithing on the same port
        # given throught the argument
        ws = WebsocketClientTornado(server_uri)
        protocol.outgoing = ws.send_message

        # Loop
        IOLoop.instance().start()

    except rospy.ROSInterruptException:
        IOLoop.instance().stop()

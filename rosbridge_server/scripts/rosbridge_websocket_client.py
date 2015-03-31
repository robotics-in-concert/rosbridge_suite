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
        self.transfers = {}

    def doconn(self):
        global user_auth
        try:
            rospy.loginfo("trying connection to %s" % (self.uri,))
            w = websocket_connect(self.uri)
            rospy.loginfo("connected, waiting for messages")
            w.add_done_callback(self.wsconnection_cb)
        except Exception as e:
            rospy.logerr(e)
            rospy.logerr("There was an exception")

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
        self.conn.write_message('{"op":"proxy","user_auth":"True"}')
        self.keepalive = IOLoop.instance().add_timeout(
            timedelta(seconds=PING_TIMEOUT), self.dokeepalive)

    def message(self, _message):
        global user_auth
        msg = json.loads(_message)
        session_id = msg['session_id']
        protocol = None
        if session_id != None:
            protocol = protocols.get(session_id)
        if protocol == None:
            rospy.loginfo("New Protocol session %s" % session_id)
            protocol = MyRosbridgeProtocol(session_id,self.conn,session_id)
            protocols[session_id] = protocol
            protocol.outgoing = protocol.send_message
        if msg['op'] == 'auth':
            try:
                # check the authorization information
                if user_auth:
                    auth_srv = rospy.ServiceProxy('/authenticate_user',
                                                  UserAuthentication)
                    resp = auth_srv(msg['user'], msg['pass'])
                    self.conn.write_message(json.dumps({"op":"auth_client","session_id":msg['session_id'],"authentication":resp.authenticated }))
                    if resp.authenticated:
                        rospy.loginfo("Client has authenticated")
                    else: 
                        # if we are here, no valid authentication was given
                        rospy.logwarn("Client did not authenticate. Closing "
                                  "connection.")
            except Exception as e:
                rospy.logerr("Exception during authentication %s", e)
                # proper error will be handled in the protocol class
                self.protocol.incoming(_message)
        elif msg['op'] == 'videoStart':
            try:    
                args = msg['url_params']
                self.transfers[session_id] = VideoTransfer("http://localhost:8080/stream", args, self,session_id)
            except Exception as e:
                rospy.logerr("Could not connect to WebCam")
                rospy.logerr(e)
                self.write_message(json.dumps({"op":"endVideo","session_id":session_id}))
        elif msg['op'] == "endVideo":
            self.transfers[session_id].end_video()
            del self.transfers[session_id]
        elif msg['op'] == "endConn":
            if protocol != None:
                rospy.loginfo("Finishing protocol for session %s" % session_id)
                protocol.finish()
                del protocols[session_id]
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


class MyRosbridgeProtocol(RosbridgeProtocol):
    def __init__(self, session_id, conn, seed):
        self.session_id = session_id
        self.conn = conn
        self.mess = 0
        RosbridgeProtocol.__init__(self,seed)
        
    def send_message(self, _message):
        try:
            self.mess += 1
            if self.session_id != None:
                msg = json.loads(_message)
                msg["session_id"] = self.session_id
                _message = json.dumps(msg)
            self.conn.write_message(_message)
        except Exception as e:
            rospy.logerr(e)



class VideoTransfer():
    def __init__(self, url, args, connection,session_id):
        tornado.httpclient.AsyncHTTPClient.configure(
                "tornado.curl_httpclient.CurlAsyncHTTPClient")
        self.conn = connection
        self.session_id = session_id
        url = url + "?" + urllib.urlencode(args)
        url = url.replace("%2F","/")
        req = tornado.httpclient.HTTPRequest(
            url = url,
            streaming_callback = self.streaming_callback,
            connect_timeout = 0.0,
            request_timeout = 0.0)
        self.http_client = tornado.httpclient.AsyncHTTPClient()
        self.http_client.fetch(req, self.async_callback)
        self.chunk = 0

    def streaming_callback(self, data):
        "Sends video in chunks"
        try:
            self.chunk += 1
            encoded = base64.b64encode(data)   # Encode in Base64 & make json
            chunk = json.dumps({"op": "videoData", "data": encoded,"session_id":self.session_id})
            self.conn.conn.write_message(chunk)
        except Exception as e:
            rospy.logerr(e)

    def async_callback(self, response):
        rospy.loginfo("Finished connection")

    def end_video(self):
        rospy.loginfo("Finished Video")
        self.http_client.close()

if __name__ == "__main__":
    try:
        rospy.init_node("rosbridge_websocket_client")

        io_loop = IOLoop.instance()
        signal.signal(signal.SIGTERM, io_loop.stop)
        protocols = {}

        # Connect with server
        server_uri = rospy.get_param("~webserver_uri")
        user_auth = rospy.get_param('~user_auth', False)
        # In the future we are going need to use everithing on the same port
        # given throught the argument
        ws = WebsocketClientTornado(server_uri)

        # Loop
        IOLoop.instance().start()

    except rospy.ROSInterruptException:
        IOLoop.instance().stop()

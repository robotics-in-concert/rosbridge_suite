#!/usr/bin/env python
"""
   node: rosbridge websocket client

   brief: Handle websocket connection through a proxy

"""
###############################################################################
# Imports
###############################################################################

import rospy
import base64
import urllib
import signal
import tornado
import tornado.ioloop
import tornado.websocket
from datetime import timedelta
from rosbridge_library.rosbridge_protocol import RosbridgeProtocol
from rosbridge_library.util import json
from rosauth.srv import UserIdPasswordAuthentication, Authentication

###############################################################################
# Configuration
###############################################################################

AUTHENTICATION_ARG_MAC = "mac"
AUTHENTICATION_ARG_USER_ID_PASSWORD = "userid_password"

WEBSOCKET_SUFFIX = "/ws"
VIDEO_SUFFIX = "/stream"

PING_TIMEOUT = 15

###############################################################################
# Global variables
###############################################################################

ws = None
proxy_name = ""
protocol = None
authenticate_mac = False
authenticate_userid_password = False
web_video_server_uri = ""

###############################################################################
# Classes
###############################################################################


class WebsocketClientTornado():
    conn = None
    keepalive = None

    def __init__(self, uri):
        self.uri = uri
        self.doconn()
        self.transfers = {}
        self.authenticated = False

    def doconn(self):
        global authenticate_mac, authenticate_userid_password
        try:
            rospy.loginfo("trying connection to %s" % (self.uri,))
            w = tornado.websocket.websocket_connect(self.uri)
            rospy.loginfo("connected, waiting for messages")
            w.add_done_callback(self.wsconnection_cb)
        except Exception as e:
            rospy.logerr("Exception: could not create a websocket connection")
            rospy.logerr(e)

    def dokeepalive(self):
        stream = self.conn.protocol.stream
        if not stream.closed():
            self.keepalive = stream.io_loop.add_timeout(
                timedelta(seconds=PING_TIMEOUT), self.dokeepalive)
            self.conn.protocol.write_ping("")
        else:
            self.keepalive = None  # should never happen

    def wsconnection_cb(self, conn):
        """Connection callback
          Defines receiving message function and
          define authentication property from connection given the the
          current start up arguments.

          @param connection being stablished
        """
        global authenticate_mac, authenticate_userid_password, proxy_name
        self.conn = conn.result()
        # TODO check result
        self.conn.on_message = self.message
        if authenticate_mac or authenticate_userid_password:
            enable_authentication = True
        else:
            enable_authentication = False
        self.conn.write_message(json.dumps({"op": "proxy",
                                "enable_authentication": enable_authentication,
                                           "name": proxy_name
                                            }))
        self.keepalive = tornado.ioloop. IOLoop.instance().add_timeout(
            timedelta(seconds=PING_TIMEOUT), self.dokeepalive)

    def message(self, _message):
        """Receive message.
          It also parse the information using the message
          parameters.
          The parameters taken into condideration in this function are:
            op : auth Authentication message for user authentication.
            op : videoStart Video connection start request for an especific
                            user session.
            op : endVideo Video connection end request for an specific user
                          session.
            op : endConn Close connection with the client.

          @param message to be sent
        """
        global authenticate_mac, authenticate_userid_password,\
            web_video_server_uri
        msg = json.loads(_message)
        session_id = msg['session_id']
        protocol = None
        if session_id is not None:
            protocol = protocols.get(session_id)
        if protocol is None:
            rospy.loginfo("New Protocol session %s" % session_id)
            protocol = MyRosbridgeProtocol(session_id, self.conn, session_id)
            protocols[session_id] = protocol
            protocol.outgoing = protocol.send_message
        if authenticate_mac or authenticate_userid_password \
                and not self.authenticated:
            try:
                msg = json.loads(_message)
                if msg['op'] == 'auth':
                    # check what type of authorithation is required and
                    # and if it is enabled
                    if msg['method'] == 'mac' or msg['method'] is None \
                            and authenticate_mac:
                        # check the MAC authorization information
                        auth_srv = rospy.ServiceProxy('authenticate',
                                                      Authentication)
                        resp = auth_srv(msg['mac'], msg['client'], msg['dest'],
                                        msg['rand'], rospy.Time(msg['t']),
                                        msg['level'], rospy.Time(msg['end']))
                    elif msg['method'] == 'userid_password' \
                            and authenticate_userid_password:
                        # check the user and ID authorization information
                        auth_srv = rospy. \
                            ServiceProxy('/authenticate_userid_password',
                                         UserIdPasswordAuthentication)
                        resp = auth_srv(msg['user'], msg['pass'])
                        self.conn.write_message(
                            json.dumps({"op": "auth_client",
                                        "session_id": msg['session_id'],
                                        "authentication": resp.authenticated
                                        }))
                    if resp.authenticated:
                        rospy.loginfo("Client has authenticated.")
                        return
                    # if we are here, no valid authentication was given
                    rospy.logerr("No valid authentication was given. Closing "
                                 "connection.")
                    self.close()
            except Exception as e:
                rospy.logwarn("Exception: error in authentication")
                rospy.logwarn(e)
                # proper error will be handled in the protocol class
                self.protocol.incoming(_message)
        if msg['op'] == 'videoStart':
            try:
                args = msg['url_params']
                self.transfers[session_id] = VideoTransfer(
                    web_video_server_uri,
                    args, self, session_id)
            except Exception as e:
                rospy.logerr("Exception: could not connect to WebCam")
                rospy.logerr(e)
                self.write_message(json.dumps({"op": "endVideo",
                                              "session_id": session_id}))
        elif msg['op'] == "endVideo":
            self.transfers[session_id].end_video()
            del self.transfers[session_id]
        elif msg['op'] == "endConn":
            if protocol is not None:
                rospy.loginfo("Finishing protocol for session %s" % session_id)
                protocol.finish()
                del protocols[session_id]
        else:
            # no authentication required
            protocol.incoming(_message)

    def close(self):
        rospy.loginfo('Connection closed')
        if self.keepalive is not None:
            keepalive = self.keepalive
            self.keepalive = None
            tornado.ioloop.IOLoop.instance().remove_timeout(keepalive)
        self.doconn()


class MyRosbridgeProtocol(RosbridgeProtocol):
    def __init__(self, session_id, conn, seed):
        self.session_id = session_id
        self.conn = conn
        self.mess = 0
        RosbridgeProtocol.__init__(self, seed)

    def send_message(self, _message):
        """Send message
          It includes session id information

          @param message to be sent
        """
        try:
            self.mess += 1
            if self.session_id is not None:
                msg = json.loads(_message)
                msg["session_id"] = self.session_id
                _message = json.dumps(msg)
            self.conn.write_message(_message)
        except Exception as e:
            rospy.logerr("Exception: message could not be sent")
            rospy.logerr(e)


class VideoTransfer():
    def __init__(self, url, args, connection, session_id):
        tornado.httpclient.AsyncHTTPClient.configure(
            "tornado.curl_httpclient.CurlAsyncHTTPClient")
        self.conn = connection
        self.session_id = session_id
        url = url + "?" + urllib.urlencode(args)
        url = url.replace("%2F", "/")
        req = tornado.httpclient.HTTPRequest(
            url=url,
            streaming_callback=self.streaming_callback,
            connect_timeout=0.0,
            request_timeout=0.0)
        self.http_client = tornado.httpclient.AsyncHTTPClient()
        self.http_client.fetch(req, self.async_callback)
        self.chunk = 0

    def streaming_callback(self, data):
        """Send video in chunks
          the video chunks are encoded in base64 for json messages

          @param video data to be sent
        """
        try:
            self.chunk += 1
            encoded = base64.b64encode(data)
            chunk = json.dumps({"op": "videoData",
                               "data": encoded,
                                "session_id": self.session_id})
            self.conn.conn.write_message(chunk)
        except Exception as e:
            rospy.logerr("Exception: video chunk could not be delivered")
            rospy.logerr(e)

    def async_callback(self, response):
        rospy.loginfo("Finished connection")

    def end_video(self):
        rospy.loginfo("Finished Video")
        self.http_client.close()

###############################################################################
# Main
###############################################################################

if __name__ == "__main__":
    try:
        rospy.init_node("rosbridge_websocket_connection")

        io_loop = tornado.ioloop.IOLoop.instance()
        signal.signal(signal.SIGTERM, io_loop.stop)
        protocols = {}

        # Connect with server
        proxy_name = rospy.get_param('~proxy_name', "default_name")
        server_uri = rospy.get_param("~proxy_uri")
        ws = WebsocketClientTornado(server_uri)

        # Get web video server address and port
        web_video_server_address = rospy.get_param("~web_video_server_address",
                                                   "localhost")
        web_video_server_port = rospy.get_param("~web_video_server_port",
                                                8080)
        web_video_server_uri = "http://" + web_video_server_address + ":" +\
            str(web_video_server_port) + VIDEO_SUFFIX
        rospy.loginfo("Using %s as websocket uri and %s as web video "
                      "server uri", server_uri, web_video_server_uri)

        # Get authentication options and configure global variables
        # TODO: use list type for possible arguments
        authentication_methods = rospy.get_param('~authentication_methods',
                                                 None)
        if authentication_methods.find(AUTHENTICATION_ARG_MAC) != -1:
            authenticate_mac = True
            rospy.loginfo("Authentication method using MAC")
        if authentication_methods\
                .find(AUTHENTICATION_ARG_USER_ID_PASSWORD) != -1:
            authenticate_userid_password = True
            rospy.loginfo("Authentication method using user id and password")
        if not authenticate_mac and not authenticate_userid_password:
            rospy.logwarn("No authentication method selected")

        # Loop
        tornado.ioloop.IOLoop.instance().start()

    except rospy.ROSInterruptException:
        tornado.ioloop.IOLoop.instance().stop()

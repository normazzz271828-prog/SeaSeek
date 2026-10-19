"""Certificate client with IPv4 transport for hosts with unusable IPv6 routes."""
import socket
import urllib3.util.connection
from certbot.main import main

urllib3.util.connection.allowed_gai_family=lambda:socket.AF_INET
if __name__=='__main__':
    raise SystemExit(main())

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer
from tgfuse.config import logging_config
log = logging_config.setup_logging(__name__)

def ftp_server(mount_path):
    authorizer = DummyAuthorizer()
    user = "tgfuse"
    passwd = "1234"
    authorizer.add_user(user, passwd, mount_path, perm='elradfmwMT')
    
    handler = FTPHandler
    handler.authorizer = authorizer

    address = ('0.0.0.0', 2121)
    server = FTPServer(address, handler)
    log.warning(f"FTP server is running on {address[0]}:{address[1]}, login: {user}; pass: {passwd}")
    server.serve_forever()

if __name__ == "__main__":
    raise RuntimeError("This module should be run only via main.py")

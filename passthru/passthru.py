from twisted.internet import reactor
from zope.interface import directlyProvides
from twisted.internet.interfaces import IHalfCloseableProtocol
from twisted.web import server, proxy
from urllib import quote as urlquote

import resources

class DockerProxyClient(proxy.ProxyClient):
    """
    An HTTP proxy which knows how to break HTTP just right so that Docker
    stream (attach/events) API calls work.
    """

    http = True

    def handleHeader(self, key, value):
        if key.lower() == "content-type" and value == "application/vnd.docker.raw-stream":
            self.father.transport.readConnectionLost = self.transport.loseWriteConnection
            directlyProvides(self.father.transport, IHalfCloseableProtocol)
            self.http = False
            self.father.transport.write(
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/vnd.docker.raw-stream\r\n"
                "\r\n")
        return proxy.ProxyClient.handleHeader(self, key, value)


    def handleResponseEnd(self):
        if self.http:
            return proxy.ProxyClient.handleResponseEnd(self)
        self.father.transport.loseConnection()


    def rawDataReceived(self, data):
        if self.http:
            return proxy.ProxyClient.rawDataReceived(self, data)
        self.father.transport.write(data)



class DockerProxyClientFactory(proxy.ProxyClientFactory):
    protocol = DockerProxyClient


class DockerProxy(proxy.ReverseProxyResource):
    proxyClientFactoryClass = DockerProxyClientFactory

    def __init__(self, dockerAddr, dockerPort, path='', reactor=reactor):
        # XXX requires Docker to be run with -H 0.0.0.0:2375, shortcut to avoid
        # making ReverseProxyResource cope with UNIX sockets.
        proxy.ReverseProxyResource.__init__(self, dockerAddr, dockerPort, path, reactor)


    def getChild(self, path, request):
        fragments = path.split("/")
        print "got fragments:", fragments
        if fragments[1:2] == ["containers", "create"] and request.method == "POST":
            return resources.CreateContainerResource()
        elif fragments[1] == "containers" and request.method == "DELETE":
            return resources.DeleteContainerResource()
        resource = DockerProxy(
            self.host, self.port, self.path + '/' + urlquote(path, safe=""),
            self.reactor)
        return resource


class ServerProtocolFactory(server.Site):
    def __init__(self, dockerAddr, dockerPort):
        self.root = DockerProxy(dockerAddr, dockerPort)
        server.Site.__init__(self, self.root)

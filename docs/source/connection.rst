Connection discovery and Communication
======================================

Network is what connects the nodes, or individual computers, in a supercomputing
cluster. To talk over the network, head and worker processes need to find each
others through a connection protocol: either some form of an "address" or a
discovery service. After a connection is established, they talk with a
communication protocol, a standardized language for efficient exchange of
informaiton. The connection protocol used by head and workers are controlled by
``head.listen`` and ``worker.dial`` in the Grain config. Most of this document
would be specifications / technical details, but the introductory part of each
section is generally useful information.

Available connection protocols:

-  `TCP <https://en.wikipedia.org/wiki/Transmission_Control_Protocol>`__/IP
   address (``tcp:\\\\``), the vanilla network protocol
-  `Unix domain socket <https://en.wikipedia.org/wiki/Unix_domain_socket>`__
   (``unix:\\\\``), like TCP, but for same-host connection
-  Bridge (``bridge:\\\\``), connection discovery through a coordinator server
-  Edge (``edge:\\\\``), connection discovery through network filesystem

Bridge and Edge protocols are private connection discovery methods of Grain.
Connection discovery is useful in a supercomputing cluster because the allocated
machines are different from time to time, and we need a fixed information source
to keep tracks of these transient addresses. Connections established by these
methods are eventually TCP sockets. The following contents assume a basic
knowledge of TCP sockets.


Bridge protocol
---------------

Bridge protocol enables connection discovery through a Bridge server, a
third-party, always-on service with a fixed public address. Before establishing
a connection, the dialers and listener contact the Bridge server to arrange a
rendezvous: they get the other's address from the Bridge server, then try to
establish a connection through TCP hole punching. Since the Bridge server
notifies both parties once both of them are ready, a dialer can "initiate" the
connection before the listener starts listening, allowing a more flexible
connection process compared to the original TCP connection.

.. code:: none

   bridge://{key}@{bridge_addr}:{bridge_port}[?iface={interface}]

where ``key`` is a pre-shared string for dialers and the listener to identify
each others; only those with the same key are allowed to conncect to each
others. ``bridge_addr`` and ``bridge_port`` are the TCP/IP address of the Bridge
server. ``interface`` optionally specifies the network interface for local
address.

Setup a bridge server
~~~~~~~~~~~~~~~~~~~~~

On a host whose network is accessible to your head and workers' hosts, run the
following install script:

.. code:: bash

   curl -sSfL https://github.com/Contextualist/grain/raw/master/bridge/install.sh | bash

The installation comes with setup and usage instructions.

Caveat
~~~~~~

Even though TCP hole punching is able to establish a connection in most of the
network environment, it might not work for certain types of NAT, or in situations
where firewalls prohibit connections between the network interfaces of the two
parties in both directions. Sometimes an alternative network interface might work
if the default one fails.

Rendezvous specification
~~~~~~~~~~~~~~~~~~~~~~~~

TODO


Edge protocol
-------------

TODO

..
   caveat: well-behaved NFS; firewall;

..
   edge file specification


Msgpack schema for head-worker communication
--------------------------------------------

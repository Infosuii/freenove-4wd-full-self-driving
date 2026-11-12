import socket
import select
import threading
import fcntl
import struct
import queue
import time
import logging

log = logging.getLogger(__name__)

class TCPServer:
    def __init__(self, newline_framing=False, on_disconnect=None):
        self.newline_framing = newline_framing
        self.on_disconnect = on_disconnect
        self.receive_buffers = {}
        self.send_lock = threading.Lock()
        self.clients_lock = threading.RLock()
        # Initialize server and client sockets
        self.server_socket = None
        self.client_sockets = {}
        # Message queue for incoming messages
        self.message_queue = queue.Queue(maxsize=256)
        # Maximum number of clients allowed
        self.max_clients = 1
        # Current number of active connections
        self.active_connections = 0
        # Thread for accepting new connections
        self.accept_thread = None
        # Event to signal the server to stop
        self.stop_event = threading.Event()
        # Pipe for stopping the server
        self.stop_pipe_r, self.stop_pipe_w = socket.socketpair()
        self.stop_pipe_r.setblocking(0)
        self.stop_pipe_w.setblocking(0)

    def start(self, ip, port, max_clients=1, listen_count=1):
        # Set the maximum number of clients
        self.max_clients = max_clients
        # Create the server socket
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((ip, port))
        self.server_socket.listen(listen_count)
        self.server_socket.setblocking(0)
        print(f"Server started, listening on {ip}:{port}")

        # Start the thread for accepting connections
        self.accept_thread = threading.Thread(target=self.accept_connections, daemon=True)
        self.accept_thread.start()

    def accept_connections(self):
        # Accept new connections until the server is stopped
        while not self.stop_event.is_set():
            # Use select to monitor the server socket and the stop pipe
            try:
                readable, writable, exceptional = select.select([self.server_socket, self.stop_pipe_r] + list(self.client_sockets.keys()), [], [])
            except (OSError, ValueError):
                # A send/disconnect worker can close a socket after this snapshot.
                time.sleep(0.005)
                continue
            for s in readable:
                if s == self.server_socket and self.active_connections < self.max_clients:
                    # Accept a new connection if the maximum number of clients is not reached
                    client_socket, client_address = s.accept()
                    client_socket.settimeout(0.2)
                    self.client_sockets[client_socket] = client_address
                    self.active_connections += 1
                    print(f"New connection from {client_address}, {self.active_connections} active connections.")
                elif s == self.server_socket and self.active_connections >= self.max_clients:
                    # Reject new connections if the maximum number of clients is reached
                    client_socket, client_address = s.accept()
                    client_socket.close()
                    print(f"Rejected connection from {client_address}, max connections ({self.max_clients}) reached.")
                elif s == self.stop_pipe_r:
                    # Stop the server if the stop pipe is read
                    self.stop_event.set()
                    break
                else:
                    client_address = self.client_sockets.get(s)
                    if client_address is None:
                        continue
                    try:
                        # Receive data from the client
                        data = s.recv(1024)
                        if data:
                            if self.newline_framing:
                                buf = self.receive_buffers.get(s, b'') + data
                                while b'\n' in buf:
                                    line, buf = buf.split(b'\n', 1)
                                    if len(line) > 1024:
                                        raise ValueError('Command too long')
                                    self.message_queue.put_nowait((client_address, line.decode('ascii') + '\n'))
                                if len(buf) > 1024:
                                    raise ValueError('Command too long')
                                self.receive_buffers[s] = buf
                            else:
                                self.message_queue.put_nowait((client_address, data.decode('utf-8')))
                        else:
                            # Remove the client if no data is received
                            print(client_address, "disconnected")
                            self.remove_client(s)
                    except (OSError, ValueError, queue.Full) as e:
                        print(f"Client receive failure: {e}")
                        self.remove_client(s)
            for s in exceptional:
                # Handle exceptional conditions
                client_address = self.client_sockets[s]
                print(client_address, "disconnected")
                self.remove_client(s)
        print("Closing accept_connections...")

    def stop_pipe(self):
        # Send a byte to the stop pipe to signal the server to stop
        self.stop_pipe_w.send(b'\x00')

    def send_to_all_client(self, message):
        # Send a message to all connected clients
        for client_socket in list(self.client_sockets.keys()):
            try:
                if isinstance(message, str):
                    encoded_message = message.encode('utf-8')
                else:
                    encoded_message = message
                with self.send_lock:
                    client_socket.sendall(encoded_message)
            except socket.error as e:
                log.warning("Error sending data: %s", e)
                self.remove_client(client_socket)

    def send_to_client(self, client_address, message):
        # Send a message to a specific client
        for client_socket, addr in list(self.client_sockets.items()):
            if addr == client_address:
                try:
                    if isinstance(message, str):
                        encoded_message = message.encode('utf-8')
                    else:
                        encoded_message = message
                    with self.send_lock:
                        client_socket.sendall(encoded_message)
                except socket.error as e:
                    log.warning("Error sending data to %s: %s", client_address, e)
                    self.remove_client(client_socket)
                return
        log.warning("Client at %s not found", client_address)

    def remove_client(self, client_socket):
        # Remove a client from the server
        with self.clients_lock:
            address = self.client_sockets.pop(client_socket, None)
            if address is None:
                return
            self.receive_buffers.pop(client_socket, None)
            client_socket.close()
            self.active_connections -= 1
        if self.on_disconnect:
            self.on_disconnect(address)

    def close(self):
        # Close the server and all client connections
        self.stop_pipe()
        if self.accept_thread is not None:
            self.accept_thread.join()
        if self.server_socket is not None:
            self.server_socket.close()
        for s in list(self.client_sockets):
            self.remove_client(s)
        self.stop_pipe_r.close()
        self.stop_pipe_w.close()
        print("Server stopped.")

    def get_client_ips(self):
        # Get a list of IP addresses of connected clients
        return [addr[0] for addr in self.client_sockets.values()]

def get_interface_ip():
    # Get the IP address of the specified network interface
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return socket.inet_ntoa(fcntl.ioctl(s.fileno(), 0x8915, struct.pack('256s', b'wlan0'[:15]))[20:24])

if __name__ == "__main__":
    server = TCPServer()
    ip = get_interface_ip()
    port = 12345
    server.start(ip, port)

    try:
        while True:
            # Process incoming messages
            while not server.message_queue.empty():
                client_address, message = server.message_queue.get()
                print(f"Received message from {client_address}: {message}")
                server.send_to_client(client_address, message)
    except KeyboardInterrupt:
        print("Server interrupted by user.")
    finally:
        server.close()

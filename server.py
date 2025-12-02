import socket
import threading

S_PORT = 7734

def peer_conn(conn, addr):
    print(f"[SERVER] Connection with {addr}")
    conn_file = conn.makefile('rwb')

    host_cleanup = None
    port_cleanup = None
    connection_logged = False 

    try:
        while True:
            request_line = conn_file.readline().decode()
            if not request_line:
                break

            request_line = request_line.strip()
            if request_line == "":
                continue

            print(f"[SERVER] Received request: {request_line}")
            parts = request_line.split()


            if len(parts) < 3:
                send_err(conn_file, 400, "Bad Request")
                continue

            method = parts[0]
            
            #LIST ALL
            if method == "LIST":
                if len(parts) != 3 or parts[1] != "ALL":
                    send_err(conn_file, 400, "Bad Request")
                    continue
                
                version = parts[2]
                if not version.startswith("P2P-CI/"):
                    send_err(conn_file, 400, "Bad Request")
                    continue
                if version != "P2P-CI/1.0":
                    send_err(conn_file, 505, "P2P-CI Version Not Supported")
                    continue

                headers = read_headers(conn_file)
                host = headers.get("Host")
                port = headers.get("Port")

                if not host or not port:
                    send_err(conn_file, 400, "Bad Request")
                    continue
                
                port = int(port)
                host_cleanup = host
                port_cleanup = port
                
                if not connection_logged:
                    print(f"[Server] Connection from host {host} at {addr[0]}:{port}")
                    connection_logged = True

                # Check if port is already used by another peer
                if not peer_add(host, port):
                    send_err(conn_file, 400, "Bad Request - Port already in use by another peer")
                    conn_file.flush()
                    break
                handle_list_all(conn_file) # Helper function to handle LIST ALL
                conn_file.flush()
                continue

            else:
                #ADD/LOOKUP
                if len(parts) != 4:
                    send_err(conn_file, 400, "Bad Request")
                    continue

                _, obj, rfc_full, version = parts

                #RFC_keyword validation
                if obj != "RFC":
                    send_err(conn_file, 400, "Bad Request")
                    continue

                #Version validation    
                if not version.startswith("P2P-CI/"):
                    send_err(conn_file, 400, "Bad Request")
                    continue
                if version != "P2P-CI/1.0":
                    send_err(conn_file, 505, "P2P-CI Version Not Supported")
                    continue
                

                
                #RFC_number validation
                try:
                    rfc_number = int(rfc_full)
                except ValueError:
                    send_err(conn_file, 400, "Bad Request")
                    continue

                headers = read_headers(conn_file)
                host = headers.get("Host")
                port = headers.get("Port")
                title = headers.get("Title")

                if not host or not port:
                    send_err(conn_file, 400, "Bad Request")
                    continue
                
                port = int(port)
                host_cleanup = host
                port_cleanup = port

                if not connection_logged:
                    print(f"[Server] Connection from host {host} at {addr[0]}:{port}")
                    connection_logged = True
                
                # Check if port is already used by another peer
                if not peer_add(host, port):
                    send_err(conn_file, 400, "Bad Request - Port already in use by another peer")
                    conn_file.flush()
                    break

                #dispatch
                if method == "ADD":
                    if not title:
                        send_err(conn_file, 400, "Bad Request")
                        continue
                    handle_add(conn_file, rfc_number, title, host, port)
                    conn_file.flush()

                elif method == "LOOKUP":
                    handle_lookup(conn_file, rfc_number)
                    conn_file.flush()
                
                else:
                    send_err(conn_file, 400, "Bad Request")
                    conn_file.flush()

    finally:
        print(f"[SERVER] Closing connection with {addr}")
        if host_cleanup and port_cleanup:
            print(f"[Server] Peer {host_cleanup}:{port_cleanup} disconnected")
            peer_delete(host_cleanup, port_cleanup)
            print(f"[Server] Removed all records for {host_cleanup}:{port_cleanup}")

        conn_file.close()
        conn.close()

def read_headers(conn_file):
    headers = {}
    while True:
        line = conn_file.readline().decode()
        if not line:
            break
        line = line.strip()
        if line == "":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()
    return headers

def handle_add(conn_file, rfc_number, title, host, port):
    rfc_add(rfc_number, title, host, port)
    response = (
        "P2P-CI/1.0 200 OK\r\n"
        "\r\n"
        f"RFC {rfc_number} {title} {host} {port}\r\n"
        "\r\n" 
    )
    conn_file.write(response.encode())
    conn_file.flush()

def handle_lookup(conn_file, rfc_number):
    entries = rfc_lookup(rfc_number)

    if not entries:
        response = "P2P-CI/1.0 404 Not Found\r\n\r\n"
        conn_file.write(response.encode())
        conn_file.flush()
        return

    response = "P2P-CI/1.0 200 OK\r\n\r\n"
    conn_file.write(response.encode())

    for entry in entries:
        line = f"RFC {entry['rfc']} {entry['title']} {entry['host']} {entry['port']}\r\n"
        conn_file.write(line.encode())

    conn_file.write(b"\r\n")
    conn_file.flush()

def handle_list_all(conn_file):
    entries = rfc_list()

    if not entries:
        response = "P2P-CI/1.0 404 Not Found\r\n\r\n"
        conn_file.write(response.encode())
        conn_file.flush()
        return
    
    response = "P2P-CI/1.0 200 OK\r\n\r\n"
    conn_file.write(response.encode())

    for entry in entries:
        line = f"RFC {entry['rfc']} {entry['title']} {entry['host']} {entry['port']}\r\n"
        conn_file.write(line.encode())

    conn_file.write(b"\r\n")
    conn_file.flush()

def send_err(conn_file, code, message):
    response = f"P2P-CI/1.0 {code} {message}\r\n\r\n"
    conn_file.write(response.encode())
    conn_file.flush()

peers = []
rfc_index = []

data_lock = threading.Lock()

def peer_add(host, port):
    with data_lock:
        # Check if this port is already used by a different peer
        for peer in peers:
            if peer['port'] == port and peer['host'] != host:
                print(f"[Server] Rejected: Port {port} already in use by {peer['host']}")
                return False
            if peer['host'] == host and peer['port'] == port:
                return True
        peers.append({'host': host, 'port': port})
        print(f"[Server] Added {host}:{port}")
        return True

def rfc_add(rfc_number, title, host, port):
    with data_lock:
        for rfc in rfc_index:
            if rfc['rfc'] == rfc_number and rfc['host'] == host and rfc['port'] == port:
                return
        rfc_index.append({'rfc': rfc_number, 'title': title, 'host': host, 'port': port})
        print(f"[Server] Added RFC {rfc_number} from {host}")


def rfc_lookup(rfc_number):
    with data_lock:
        return [rfc for rfc in rfc_index if rfc['rfc'] == rfc_number]

def rfc_list():
    with data_lock:
        return list(rfc_index)

def peer_delete(host, port):
    global peers
    global rfc_index
    with data_lock:
        peers = [peer for peer in peers if not (peer['host'] == host and peer['port'] == port)]
        rfc_index = [rfc for rfc in rfc_index if not (rfc['host'] == host and rfc['port'] == port)]


def main():
    try:
        s_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s_socket.bind(('', S_PORT))
        s_socket.listen(5)
        print(f"[SERVER] Listening on port {S_PORT}...")
    except OSError as e:
        if e.errno == 10048 or e.errno == 48:  # Windows/Unix port in use
            print(f"[SERVER] Error: Port {S_PORT} is already in use")
            print("[SERVER] Please close the other application using this port or choose a different port")
        else:
            print(f"[SERVER] Error: Cannot bind to port {S_PORT} - {e}")
        return
    except Exception as e:
        print(f"[SERVER] Error: Failed to start server - {e}")
        return

    try:
        while True:
            conn, addr = s_socket.accept()
            print(f"[SERVER] New connection from {addr}")

            thread = threading.Thread(target=peer_conn, args=(conn, addr), daemon=True)
            thread.start()
    except KeyboardInterrupt:
        print("\n[SERVER] Shutting down...")
        s_socket.close()
    except Exception as e:
        print(f"[SERVER] Error: {e}")
        s_socket.close()


if __name__ == "__main__":
    main()
from urllib.parse import unquote, urlparse
import socket
import threading
import ssl
import logging
from typing import Optional, Dict, Tuple

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class RedirectionError(Exception):
    pass

class UnexpectedStatusError(Exception):
    pass

# Load HTML templates
def load_html_templates() -> Tuple[str, str, str, str]:
    with open("html/Search.html", "r", encoding="utf-8") as f:
        search = f.read()
    with open("html/BadRequestHeader.html", "r", encoding="utf-8") as f:
        BRH = f.read()
    with open("html/BadRequestGeneral.html", "r", encoding="utf-8") as f:
        BRG = f.read()
    with open("html/NotSupported.html", "r", encoding="utf-8") as f:
        NS = f.read()
    return search, BRH, BRG, NS

search, BRH, BRG, NS = load_html_templates()

def fetch_html(url: str, timeout: int = 10) -> Optional[str]:
    """Fetch HTML content from the given URL with support for HTTPS."""
    try:
        parsed_url = urlparse(url)
        host = parsed_url.netloc
        path = parsed_url.path or "/"
        port = 443 if parsed_url.scheme == "https" else 80

        with socket.create_connection((host, port), timeout=timeout) as sock:
            if parsed_url.scheme == "https":
                context = ssl.create_default_context()
                with context.wrap_socket(sock, server_hostname=host) as ssock:
                    return gather_html_content(ssock, host, path)
            return gather_html_content(sock, host, path)
    except socket.timeout:
        logger.error("Socket connection timed out.")
        return None
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        return None

def gather_html_content(sock: socket.socket, host: str, path: str) -> str:
    request = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\nUser-Agent: QuantumHTTP/1.0\r\n\r\n"
    sock.sendall(request.encode())

    response = bytearray()
    while True:
        if data := sock.recv(4096):
            response.extend(data)

        else:
            break
    response_str = response.decode("utf-8", errors="replace")
    headers_end = response_str.find("\r\n\r\n")
    return response_str[headers_end + 4:] if headers_end != -1 else ""

class QuantumHTTP:
    def __init__(self, host: str = "127.0.0.1", port: int = 8000):
        self.host = host
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind((self.host, self.port))
        self.socket.listen(10)
        self.routes: Dict[str, callable] = {
            "GET": self.GET,
            "POST": self.POST
        }

    def GET(self, request: str) -> str:
        parsed_request = request.split(" ")
        if len(parsed_request) > 1:
            return self.findURL(parsed_request)
        return "HTTP/1.1 400 Bad Request\r\nContent-Type: text/html\r\n\r\n" + BRH

    def POST(self, body: str) -> str:
        try:
            params = dict(param.split('=', 1) for param in body.split('&'))
            params = {k: unquote(v.replace("+", " ")) for k, v in params.items()}

            response_content = f"<html><body><h1>POST Data Received</h1><ul>{''.join(f'<li>{key}: {value}</li>' for key, value in params.items())}</ul></body></html>"
            return "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n" + response_content
        except Exception as e:
            return "HTTP/1.1 400 Bad Request\r\nContent-Type: text/html\r\n\r\n" + BRG.replace("{{error}}", str(e))

    def findURL(self, parsed_request: list) -> str:
        try:
            query_params = dict(param.split('=', 1) for param in parsed_request[1].split('?', 1)[1].split('&'))
            url = unquote(query_params.get('url', '').replace("+", " "))
            website = fetch_html(url) if url else None
            html_content = website if website is not None else search
            return "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n" + html_content
        except Exception as e:
            return "HTTP/1.1 400 Bad Request\r\nContent-Type: text/html\r\n\r\n" + BRG.replace("{{error}}", str(e))

    def send_response(self, conn: socket.socket, response: str) -> None:
        try:
            conn.sendall(response.encode())
        except Exception as e:
            logger.error(f"Error sending response: {e}")

    def handle_request(self, conn: socket.socket, addr: Tuple[str, int]) -> None:
        try:
            with conn:
                logger.info(f"Connection from {addr}")
                request_data = conn.recv(4096).decode()
                if not request_data:
                    response = "HTTP/1.1 400 Bad Request\r\nContent-Type: text/html\r\n\r\n" + BRH.replace("{{request_method}}", "Empty")
                    self.send_response(conn, response)
                    return

                request_lines = request_data.split('\r\n')
                request_line = request_lines[0]
                request_method = request_line.split()[0].upper()

                if request_method not in self.routes:
                    response = (
                        "HTTP/1.1 501 Not Implemented\r\nContent-Type: text/html\r\n\r\n"
                        + NS
                        if request_method in ["DELETE", "HEAD", "OPTIONS", "PATCH"]
                        else "HTTP/1.1 400 Bad Request\r\nContent-Type: text/html\r\n\r\n"
                        + BRH.replace("{{request_method}}", request_method)
                    )
                elif request_method == "POST":
                    content_length = int(next((line.split(': ')[1] for line in request_lines if 'Content-Length' in line), 0))
                    body = conn.recv(content_length).decode()
                    response = self.routes[request_method](body)
                else:
                    response = self.routes[request_method](request_data)

                self.send_response(conn, response)
        except Exception as e:
            error_response = "HTTP/1.1 500 Internal Server Error\r\nContent-Type: text/html\r\n\r\n" + BRG.replace("{{error}}", str(e))
            self.send_response(conn, error_response)

    def handle_client(self, conn: socket.socket, addr: Tuple[str, int]) -> None:
        try:
            self.handle_request(conn, addr)
        except Exception as e:
            logger.error(f"Error handling client: {e}")
        finally:
            conn.close()

    def start(self) -> None:
        logger.info(f"QuantumHTTP server started on http://{self.host}:{self.port}")
        try:
            while True:
                conn, addr = self.socket.accept()
                client_thread = threading.Thread(target=self.handle_client, args=(conn, addr))
                client_thread.daemon = True
                client_thread.start()
        except KeyboardInterrupt:
            logger.info("\nShutting down server...")
        finally:
            self.socket.close()

if __name__ == "__main__":
    quantum_http = QuantumHTTP()
    quantum_http.start()
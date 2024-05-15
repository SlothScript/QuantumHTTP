import contextlib
from urllib.parse import unquote
import socket
import os

class RedirectionError(Exception):
    pass

class UnexpectedStatusError(Exception):
    pass

# Load HTML templates
def load_html_templates():
    with open("html/Search.html", "r") as f:
        search = f.read()
    with open("html/BadRequestHeader.html", "r") as f:
        BRH = f.read()
    with open("html/BadRequestGeneral.html", "r") as f:
        BRG = f.read()
    with open("html/NotSupported.html", "r") as f:
        NS = f.read()
    return search, BRH, BRG, NS

search, BRH, BRG, NS = load_html_templates()

def fetch_html(url, timeout=10):
    """Fetch HTML content from the given URL."""
    try:
        # Parse the URL to extract the host and path
        print("Getting HTML...")
        parts = url.split("/")
        if len(parts) < 3:
            raise ValueError("Invalid URL format")
        host = parts[2]
        path = "/" + "/".join(parts[3:])

        # Establish a TCP connection to the web server
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((host, 80))

            # Send an HTTP GET request for the specified path
            request = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n"
            s.sendall(request.encode())

            # Receive and process the response
            response = b""
            while True:
                data = s.recv(1024)
                if not data:
                    break
                response += data

            # Decode the response and return the HTML content
            response_str = response.decode("utf-8")
            html_start = response_str.find("\r\n\r\n") + 4  # Find the start of the HTML content
            return response_str[html_start:]

    except socket.timeout:
        print("Socket connection timed out.")
        return None

    except Exception as e:
        print(f"An error occurred: {e}")
        return None

class QuantumHTTP:
    def __init__(self):
        self.host = ""  # Listen on all available interfaces
        self.port = 8000  # Use port 80 for HTTP
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # Set SO_REUSEADDR option
        self.socket.bind((self.host, self.port))
        self.socket.listen(5)  # Allow up to 5 connections in the queue

    def GET(self, request):
        """Handle GET requests."""
        parsed_request = request.split(" ")
        if len(parsed_request) > 1:
            return self.findURL(parsed_request)
        else:
            return "HTTP/1.1 400 Bad Request\r\nContent-Type: text/html\r\n\r\n" + BRH

    def POST(self, body):
        """Handle POST requests."""
        try:
            # Here, we simply parse the POST body as form data (key=value&key=value)
            params = {}
            for param in body.split("&"):
                key_value = param.split("=")
                if len(key_value) == 2:
                    key, value = key_value
                    params[key] = unquote(value.replace("+", " "))

            # Create a response HTML content confirming the received data
            response_content = "<html><body><h1>POST Data Received</h1><ul>"
            for key, value in params.items():
                response_content += f"<li>{key}: {value}</li>"
            response_content += "</ul></body></html>"

            return "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n" + response_content

        except Exception as e:
            print(f"Error processing POST data: {e}")
            return "HTTP/1.1 400 Bad Request\r\nContent-Type: text/html\r\n\r\n" + BRG.replace("{{error}}", str(e))

    def findURL(self, parsed_request):
        """Extract URL from the request and fetch its HTML content."""
        url = None
        with contextlib.suppress(Exception):
            query_string = parsed_request[1].split("?")[1] if "?" in parsed_request[1] else ""
            params = query_string.split("&")
            for param in params:
                key_value = param.split("=")
                if len(key_value) == 2:
                    key, value = key_value
                    if key == "url":
                        url = unquote(value.replace("+", " "))
                        print(url)
                        break

        website = fetch_html(url) if url else None
        html_content = website if website is not None else search

        try:
            return "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n" + html_content
        except TypeError:
            return "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n" + BRG.replace("{{error}}", "URL empty")

    def send_response(self, conn, response):
        """Send HTTP response to the client."""
        try:
            conn.sendall(response.encode())
        except Exception as e:
            print(f"Error sending response: {e}")

    def handle_request(self, conn, addr):
        """Handle incoming HTTP request."""
        print(f"Connection from {addr}")
        request = conn.recv(1024).decode()
        print("Received request:")
        print(request)

        if not request:
            print("Received an empty request")
            response = "HTTP/1.1 400 Bad Request\r\nContent-Type: text/html\r\n\r\n" + BRH.replace("{{request_method}}", "Empty")
            self.send_response(conn, response)
            conn.close()
            return

        request_method, path, _ = request.split(" ", 2)
        if request_method.upper() not in ["GET", "POST", "DELETE", "HEAD", "OPTIONS", "PATCH"]:
            response = "HTTP/1.1 400 Bad Request\r\nContent-Type: text/html\r\n\r\n" + BRH.replace("{{request_method}}", request_method)
        elif request_method.upper() == "GET":
            response = self.GET(request)
        elif request_method.upper() == "POST":
            content_length = int(next((line for line in request.split("\r\n") if "Content-Length" in line), "Content-Length: 0").split(": ")[1])
            body = conn.recv(content_length).decode()
            response = self.POST(body)
        else:
            response = "HTTP/1.1 501 Not Implemented\r\nContent-Type: text/html\r\n\r\n" + NS

        self.send_response(conn, response)
        conn.close()

    def start(self):
        """Start the QuantumHTTP server."""
        print("QuantumHTTP server started.")
        print(f"Listening on {self.host}:{self.port}")
        while True:
            conn, addr = self.socket.accept()
            try:
                self.handle_request(conn, addr)
            except Exception as e:
                print(f"Error handling request: {e}")
                self.send_response(conn, "HTTP/1.1 501 Not Implemented\r\nContent-Type: text/html\r\n\r\n" + BRG.replace("{{error}}", str(e)))
            finally:
                conn.close()

if __name__ == "__main__":
    quantum_http = QuantumHTTP()
    quantum_http.start()

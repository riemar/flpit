"""Demonstrate a named client and a delegating handler."""
from flpit.http import DelegatingHandler, HttpClientFactory, HttpRequestMessage


class ClientNameHandler(DelegatingHandler):
    def send_async(self, request: HttpRequestMessage, token=None):
        request.headers["X-Client-Name"] = "catalog"
        return super().send_async(request, token)


factory = HttpClientFactory()
factory.configure_client(
    "catalog",
    lambda client: setattr(client, "base_address", "https://example.com/api/"),
)
factory.add_http_message_handler(
    "catalog",
    lambda inner: ClientNameHandler(inner),
)

try:
    with factory.create_client("catalog") as client:
        response = client.get_async("products").result()
        try:
            response.ensure_success_status_code()
            print(response.content.read_as_string_async().result())
        finally:
            response.close()
finally:
    factory.close()

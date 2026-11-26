"""Provisional .NET-inspired HTTP client for FlpIt, backed by urllib3."""

from .client import HttpClient, HttpClientFactory, HttpMessageInvoker, IHttpClient, IHttpClientFactory
from .content import (
    ByteArrayContent,
    CancellationAwareResponseStream,
    FormUrlEncodedContent,
    HttpContent,
    JsonContent,
    StreamContent,
    StringContent,
)
from .errors import HttpRequestException, HttpRequestTimeoutError
from .handlers import DelegatingHandler, HttpClientHandler, HttpMessageHandler
from .headers import HttpHeaders
from .messages import (
    HttpCompletionOption,
    HttpMethod,
    HttpRequestMessage,
    HttpResponseMessage,
    HttpStatusCode,
)
from .transport import Urllib3Transport

__all__ = [
    "ByteArrayContent", "CancellationAwareResponseStream", "DelegatingHandler",
    "FormUrlEncodedContent", "HttpClient", "HttpClientFactory", "HttpClientHandler",
    "HttpCompletionOption", "HttpContent", "HttpHeaders", "HttpMessageHandler",
    "HttpMessageInvoker", "HttpMethod", "HttpRequestException", "HttpRequestMessage",
    "HttpRequestTimeoutError", "HttpResponseMessage", "HttpStatusCode",
    "IHttpClient", "IHttpClientFactory", "JsonContent", "StreamContent",
    "StringContent", "Urllib3Transport",
]

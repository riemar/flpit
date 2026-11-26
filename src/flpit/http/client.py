"""HttpClient, IHttpClient and factory abstractions."""
from __future__ import annotations

import threading
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urljoin, urlsplit

from flpit.task import CancellationToken, Task

from .content import HttpContent, JsonContent
from .handlers import HttpClientHandler, HttpMessageHandler
from .headers import HttpHeaders
from .messages import HttpCompletionOption, HttpMethod, HttpRequestMessage, HttpResponseMessage


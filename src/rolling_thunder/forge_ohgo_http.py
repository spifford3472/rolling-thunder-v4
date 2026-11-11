"""HTTPS-only OHGO transport with bounded payload and header-only credentials."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from rolling_thunder.forge_ohgo_incidents import OhgoResponse

_MAX_CONTENT_BYTES = 2_000_000


def fetch_ohgo_https(url: str, headers: Mapping[str, str], timeout_s: float) -> OhgoResponse:
    """Retrieve only the constant official OHGO incident endpoint.

    Do not place a key in a URL, log the request/headers or follow redirects
    to other hosts. Never expose raw upstream error text containing secrets.
    """

    if not url.startswith("https://publicapi.ohgo.com/api/v1/incidents?"):
        raise ValueError("Unexpected OHGO host or endpoint")
    if "api-key" in url.lower() or "Authorization" not in headers:
        raise ValueError("OHGO credentials must use the request header")

    class NoExternalRedirect(HTTPRedirectHandler):
        """Never re-send a private OHGO key to a redirected host."""

        def redirect_request(
            self,
            req: Request,
            fp: object,
            code: int,
            msg: str,
            headers: object,
            newurl: str,
        ) -> None:
            return None

    opener = build_opener(NoExternalRedirect())
    request = Request(
        url,
        headers=dict(headers),
        method="GET",
    )
    try:
        with opener.open(request, timeout=timeout_s) as result:
            if result.geturl() != url:
                raise ValueError("OHGO redirect refused")
            body = result.read(_MAX_CONTENT_BYTES + 1)
            if len(body) > _MAX_CONTENT_BYTES:
                raise ValueError("Oversized OHGO response")
            return OhgoResponse(
                result.status,
                body,
                {key.lower(): value for key, value in result.headers.items()},
            )
    except HTTPError as error:
        if error.code == 304:
            return OhgoResponse(304, b"", {})
        return OhgoResponse(error.code, b"", {})

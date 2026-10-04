"""Small private-network administrative frontend for the Forge directory."""

from collections.abc import Mapping
from hashlib import sha256
from hmac import compare_digest, digest
from html import escape
from http.cookies import CookieError, SimpleCookie
from secrets import token_hex
from urllib.parse import parse_qs, urlencode, urlsplit

from rolling_thunder.forge_known_callsigns import ForgeKnownCallsignRepository
from rolling_thunder.known_callsigns import KnownCallsignInput

ADMIN_ROUTE = "/admin/known-callsigns"
MAX_ADMIN_BODY = 32_768
AdminResponse = tuple[int, tuple[tuple[str, str], ...], bytes]


class ForgeKnownCallsignAdmin:
    """No provider calls or client-facing comment serialization."""

    def __init__(self, repository: ForgeKnownCallsignRepository) -> None:
        self._repository = repository
        self._csrf_key = token_hex(32).encode()

    def handle(
        self, method: str, target: str, headers: Mapping[str, str], body: bytes
    ) -> AdminResponse:
        parsed = urlsplit(target)
        if parsed.path not in (ADMIN_ROUTE, ADMIN_ROUTE + "/delete"):
            return self._page(404, "Not found", "", "")
        if method not in ("GET", "POST"):
            return self._page(405, "Method not allowed", "", "")
        token = self._cookie_token(headers)
        if method == "POST":
            if len(body) > MAX_ADMIN_BODY:
                return self._page(413, "Request too large", "", token)
            try:
                fields = parse_qs(body.decode("utf-8"), keep_blank_values=True, max_num_fields=12)
                if any(len(values) != 1 for values in fields.values()):
                    raise ValueError("Duplicate form field")
                form = {name: values[0] for name, values in fields.items()}
                if set(form) - {
                    "csrf",
                    "original",
                    "callsign",
                    "display_name",
                    "comment",
                    "active",
                    "confirm",
                }:
                    raise ValueError("Unknown form field")
                if not token or not compare_digest(form.get("csrf", "").encode(), token.encode()):
                    return self._page(403, "Invalid form token; reload the page", "", "")
                origin = self._header(headers, "origin")
                if origin and urlsplit(origin).netloc != self._header(headers, "host"):
                    return self._page(403, "Cross-origin request rejected", "", "")
                if parsed.path.endswith("/delete"):
                    if form.get("confirm") != "delete":
                        raise ValueError("Deletion must be confirmed")
                    self._repository.delete(form.get("callsign", ""))
                else:
                    if form.get("active", "") not in ("", "true"):
                        raise ValueError("Invalid active value")
                    data = KnownCallsignInput(
                        callsign=form.get("callsign", ""),
                        display_name=form.get("display_name", ""),
                        comment=form.get("comment", ""),
                        active=form.get("active") == "true",
                    )
                    self._repository.save(data, original=form.get("original") or None)
            except (ValueError, UnicodeError) as error:
                return self._page(400, "Invalid record", f"<p>{escape(str(error))}</p>", token)
            return (303, (("Location", ADMIN_ROUTE), ("Content-Length", "0")), b"")
        if not token:
            nonce = token_hex(32)
            token = nonce + "." + digest(self._csrf_key, nonce.encode(), sha256).hex()
        try:
            query = parse_qs(parsed.query, max_num_fields=4)
        except ValueError:
            return self._page(400, "Invalid query", "", token)
        callsign = query.get("callsign", [""])[0].strip().upper()
        records = self._repository.list_records()
        if parsed.path.endswith("/delete"):
            record = next((r for r in records if r.data.callsign == callsign), None)
            if record is None:
                return self._page(404, "Callsign not found", "", token)
            content = (
                f"<p>Delete {escape(callsign)} permanently?</p>"
                f'<form method="post">{self._hidden("csrf", token)}'
                f"{self._hidden('callsign', callsign)}"
                '<button name="confirm" value="delete">Confirm deletion</button></form>'
            )
            return self._page(200, "Confirm deletion", content, token)
        editing = next((r.data for r in records if r.data.callsign == callsign), None)
        data = editing or KnownCallsignInput(callsign="W1ABC")
        search = query.get("search", [""])[0].strip().upper()
        rows = []
        for record in records:
            entry = record.data
            if search and search not in entry.callsign:
                continue
            link = urlencode({"callsign": entry.callsign})
            rows.append(
                f"<tr><td>{escape(entry.callsign)}</td><td>{escape(entry.display_name)}</td>"
                f"<td>{'Active' if entry.active else 'Inactive'}</td>"
                f'<td class="comment">{escape(entry.comment)}</td><td>'
                f'<a href="{ADMIN_ROUTE}?{link}">Edit</a> '
                f'<a href="{ADMIN_ROUTE}/delete?{link}">Delete…</a></td></tr>'
            )
        content = (
            f'<form method="get"><label>Search callsign <input name="search" '
            f'value="{escape(search, quote=True)}"></label><button>Search</button></form>'
            '<div class="table"><table><tr><th>Callsign</th><th>Name</th><th>Status</th>'
            "<th>Private comment</th><th>Actions</th></tr>" + "".join(rows) + "</table></div>"
            f"<h2>{'Edit' if editing else 'Add'} friend</h2>"
            f'<form method="post" action="{ADMIN_ROUTE}">{self._hidden("csrf", token)}'
            f"{self._hidden('original', editing.callsign if editing else '')}"
            f'<label>Callsign <input name="callsign" required maxlength="12" '
            f'value="{escape(editing.callsign if editing else "", quote=True)}"></label>'
            f'<label>Display name <input name="display_name" maxlength="160" '
            f'value="{escape(data.display_name, quote=True)}"></label>'
            f'<label>Private comment <textarea name="comment" maxlength="4000">'
            f"{escape(data.comment)}</textarea></label>"
            f'<label><input type="checkbox" name="active" value="true" '
            f"{'checked' if data.active else ''}> Active friend</label>"
            "<button>Save</button></form>"
        )
        return self._page(200, "Known callsigns", content, token)

    @staticmethod
    def _header(headers: Mapping[str, str], name: str) -> str:
        return next((v for k, v in headers.items() if k.lower() == name), "")

    def _cookie_token(self, headers: Mapping[str, str]) -> str:
        cookie: SimpleCookie = SimpleCookie()
        try:
            cookie.load(self._header(headers, "cookie"))
            value = cookie["known_csrf"].value if "known_csrf" in cookie else ""
            nonce, signature = value.split(".")
            if len(nonce) == 64 and compare_digest(
                signature.encode(), digest(self._csrf_key, nonce.encode(), sha256).hex().encode()
            ):
                return value
        except (ValueError, UnicodeError, CookieError):
            pass
        return ""

    @staticmethod
    def _hidden(name: str, value: str) -> str:
        return f'<input type="hidden" name="{name}" value="{escape(value, quote=True)}">'

    @staticmethod
    def _page(status: int, title: str, content: str, token: str) -> AdminResponse:
        body = (
            f'<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{escape(title)}</title><style>"
            "body{font:18px system-ui;max-width:1100px;margin:2em auto;padding:0 1em}"
            "label{display:block;margin:1em 0}input,textarea,button{font:inherit}"
            "textarea{display:block;width:95%;min-height:6em}.table{overflow:auto}"
            "td,th{padding:.5em;text-align:left;border-bottom:1px solid #ccc}"
            ".comment{white-space:pre-wrap}a{margin-right:1em}"
            f"</style><h1>{escape(title)}</h1><p>Private Forge administration. "
            "Comments stay on Forge.</p>"
            + content
            + f'<p><a href="{ADMIN_ROUTE}">Directory / new entry</a></p></html>'
        ).encode()
        headers: tuple[tuple[str, str], ...] = (
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            ("X-Frame-Options", "DENY"),
            ("X-Content-Type-Options", "nosniff"),
            (
                "Content-Security-Policy",
                (
                    "default-src 'none'; style-src 'unsafe-inline'; "
                    "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
                ),
            ),
        )
        if token:
            headers += (
                (
                    "Set-Cookie",
                    f"known_csrf={token}; Path={ADMIN_ROUTE}; HttpOnly; SameSite=Strict",
                ),
            )
        return status, headers, body

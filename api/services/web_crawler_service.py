"""Safe, single-page website extraction using Crawl4AI and Playwright Chromium.

The crawler is imported lazily so normal RAG routes and application startup do
not require Chromium to launch. Only public HTTP(S) destinations are allowed.
Every browser HTTP request (including redirects and subresources) is checked
before it is continued.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from config.settings import settings
from exception.exceptions import BadRequestError, UpstreamServiceError
from logger.logger import get_logger
from utils.text import normalize_extracted_text

logger = get_logger(__name__)

MAX_URL_LENGTH = 2048
MAX_WEBSITE_TEXT_CHARS = 120_000
ALLOWED_SCHEMES = {"http", "https"}
BLOCKED_HOST_SUFFIXES = (
    ".localhost", ".local", ".internal", ".home.arpa", ".test",
    ".invalid", ".example",
)
HOST_LABEL_RE = re.compile(r"^[A-Za-z0-9-]+$")


@dataclass(frozen=True)
class CrawledWebsite:
    title: str
    url: str
    markdown: str
    truncated: bool = False


def normalize_website_url_syntax(url: str) -> str:
    """Validate URL syntax and reject obvious local/private destinations."""
    if not isinstance(url, str):
        raise BadRequestError("Enter a valid website URL beginning with http:// or https://.")
    url = url.strip()
    if not url or len(url) > MAX_URL_LENGTH or any(ch.isspace() or ord(ch) < 32 for ch in url):
        raise BadRequestError("Website URL is empty, too long, or contains whitespace/control characters.")
    if "\\" in url:
        raise BadRequestError("Website URL must be a normal HTTP(S) URL.")

    try:
        parsed = urlsplit(url)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise BadRequestError("Website URL is malformed.") from exc

    if scheme not in ALLOWED_SCHEMES:
        raise BadRequestError("Only http:// and https:// website URLs are supported.")
    if not parsed.netloc or not hostname:
        raise BadRequestError("Website URL must include a hostname.")
    if parsed.username is not None or parsed.password is not None:
        raise BadRequestError("Website URLs must not contain usernames or passwords.")

    hostname = hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(BLOCKED_HOST_SUFFIXES):
        raise BadRequestError("Local and internal hostnames cannot be crawled.")
    if len(hostname) > 253:
        raise BadRequestError("Website hostname is too long.")

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None

    if address is not None:
        if not address.is_global:
            raise BadRequestError("Private, loopback, link-local, and reserved IP addresses cannot be crawled.")
    else:
        try:
            hostname = hostname.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise BadRequestError("Website hostname is not valid.") from exc
        labels = hostname.split(".")
        if len(labels) < 2 or any(
            not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
            or not HOST_LABEL_RE.fullmatch(label)
            for label in labels
        ):
            raise BadRequestError("Website hostname is not valid.")
    if port is not None:
        expected_port = 80 if scheme == "http" else 443
        if port != expected_port:
            raise BadRequestError("Only the standard HTTP (80) and HTTPS (443) ports are supported.")

    display_host = f"[{hostname}]" if ":" in hostname else hostname
    netloc = display_host
    if port is not None and port != (80 if scheme == "http" else 443):
        netloc = f"{display_host}:{port}"
    path = parsed.path or "/"
    # Fragments never reach the web server and can make identical pages look different.
    return urlunsplit((scheme, netloc, path, parsed.query, ""))


def _require_public_ip(value: str) -> None:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise BadRequestError("Website hostname resolved to an invalid IP address.") from exc
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        if not address.ipv4_mapped.is_global:
            raise BadRequestError("Website hostname resolved to a private or reserved IP address.")
        return
    if not address.is_global:
        raise BadRequestError("Website hostname resolved to a private or reserved IP address.")


async def validate_public_website_url(url: str, dns_cache: dict[str, bool] | None = None) -> str:
    """Resolve and reject a host if any answer is not globally routable."""
    normalized = normalize_website_url_syntax(url)
    parsed = urlsplit(normalized)
    hostname = parsed.hostname
    if hostname is None:
        raise BadRequestError("Website URL must include a hostname.")

    try:
        ipaddress.ip_address(hostname)
        return normalized
    except ValueError:
        pass

    cache = dns_cache if dns_cache is not None else {}
    cache_key = hostname.lower()
    if cache.get(cache_key) is False:
        raise BadRequestError("Website host is not allowed.")
    if cache.get(cache_key) is not True:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            loop = asyncio.get_running_loop()
            results = await asyncio.wait_for(
                loop.getaddrinfo(hostname, port, type=socket.SOCK_STREAM),
                timeout=3.0,
            )
        except (OSError, asyncio.TimeoutError) as exc:
            cache[cache_key] = False
            raise BadRequestError("Website hostname could not be resolved.") from exc

        addresses = {item[4][0] for item in results}
        if not addresses:
            cache[cache_key] = False
            raise BadRequestError("Website hostname has no DNS addresses.")
        try:
            for address in addresses:
                _require_public_ip(address)
        except BadRequestError:
            cache[cache_key] = False
            raise
        cache[cache_key] = True

    return normalized


def _extract_markdown(result: object) -> str:
    markdown = getattr(result, "markdown", None)
    if isinstance(markdown, str):
        return markdown
    if markdown is None:
        return ""
    # Crawl4AI exposes raw_markdown and fit_markdown when a generator/filter is used.
    raw = getattr(markdown, "raw_markdown", None)
    fit = getattr(markdown, "fit_markdown", None)
    return raw or fit or ""


def _extract_title(result: object, requested_url: str) -> str:
    direct = getattr(result, "title", None)
    metadata = getattr(result, "metadata", None)
    if isinstance(metadata, dict):
        direct = direct or metadata.get("title") or metadata.get("og:title")
    if isinstance(direct, str) and direct.strip():
        return re.sub(r"\s+", " ", direct).strip()[:200]
    return urlsplit(requested_url).hostname or requested_url


async def crawl_website(url: str) -> CrawledWebsite:
    """Crawl one user-supplied URL into normalized Markdown for RAG."""
    dns_cache: dict[str, bool] = {}
    normalized_url = await validate_public_website_url(url, dns_cache)
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
    except ImportError as exc:
        raise UpstreamServiceError(
            "Website crawling requires Crawl4AI. Install the requirements and run crawl4ai-setup, "
            "or configure CRAWL4AI_CDP_URL for a remote Chromium browser."
        ) from exc

    async def configure_page_routes(page, context, **kwargs):
        async def safe_route(route):
            request_url = route.request.url
            parsed_request = urlsplit(request_url)
            if parsed_request.scheme in {"data", "blob", "about"} and not route.request.is_navigation_request():
                await route.continue_()
                return
            try:
                await validate_public_website_url(request_url, dns_cache)
            except BadRequestError:
                # Block unsafe redirects and subresource requests, not the whole browser context.
                await route.abort("blockedbyclient")
                return
            except Exception:
                await route.abort()
                return
            await route.continue_()

        await context.route("**/*", safe_route)
        return page

    cdp_url = settings.crawl4ai_cdp_url.strip() or None
    browser_config = BrowserConfig(
        browser_type="chromium",
        browser_mode="custom" if cdp_url else "dedicated",
        headless=True,
        cdp_url=cdp_url,
        ignore_https_errors=False,
        java_script_enabled=True,
        accept_downloads=False,
        verbose=False,
    )
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        excluded_tags=["script", "style", "noscript", "svg", "canvas", "nav", "footer", "form", "aside"],
        word_count_threshold=3,
        wait_until="domcontentloaded",
        page_timeout=max(5, min(int(settings.crawl4ai_timeout_seconds), 45)) * 1000,
        delay_before_return_html=0.2,
        check_robots_txt=False,
    )

    try:
        async with AsyncWebCrawler(config=browser_config, verbose=False) as crawler:
            crawler.crawler_strategy.set_hook("on_page_context_created", configure_page_routes)
            result = await asyncio.wait_for(
                crawler.arun(url=normalized_url, config=run_config),
                timeout=max(8, min(int(settings.crawl4ai_timeout_seconds), 45)) + 5,
            )
    except asyncio.TimeoutError as exc:
        raise UpstreamServiceError("Website extraction timed out. Try a faster page or retry later.") from exc
    except BadRequestError:
        raise
    except Exception as exc:
        logger.error(f"Crawl4AI failed for {normalized_url}: {exc}")
        detail = str(exc).lower()
        if "executable doesn't exist" in detail or "browser has not been installed" in detail or "chromium" in detail:
            raise UpstreamServiceError(
                "Chromium is not installed or unavailable on this deployment. Run crawl4ai-setup "
                "and python -m playwright install chromium, or configure CRAWL4AI_CDP_URL."
            ) from exc
        raise UpstreamServiceError("The website could not be extracted. Check that it is public and accessible, then retry.") from exc

    if not getattr(result, "success", False):
        message = str(getattr(result, "error_message", "") or "The crawler returned no result.")
        logger.warning(f"Crawl4AI returned an unsuccessful result for {normalized_url}: {message}")
        raise UpstreamServiceError("The website could not be extracted. It may block automated browsers or require authentication.")

    final_url = getattr(result, "url", None) or normalized_url
    # Validate the final URL again before storing it as the durable source reference.
    final_url = await validate_public_website_url(final_url, dns_cache)
    markdown = normalize_extracted_text(_extract_markdown(result), extraction_source="website")
    if not markdown:
        raise BadRequestError("No readable page content was found. Try a public article or documentation page.")
    truncated = len(markdown) > MAX_WEBSITE_TEXT_CHARS
    if truncated:
        candidate = markdown[:MAX_WEBSITE_TEXT_CHARS]
        boundary = candidate.rfind("\n")
        markdown = candidate[:boundary].rstrip() if boundary > MAX_WEBSITE_TEXT_CHARS * 0.75 else candidate.rstrip()
    return CrawledWebsite(
        title=_extract_title(result, final_url),
        url=final_url,
        markdown=markdown,
        truncated=truncated,
    )

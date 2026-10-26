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

import httpx

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


def _parse_cloud_payload(payload: object, fallback_url: str) -> tuple[str, str, str]:
    """Extract title, final URL and Markdown from Crawl4AI Cloud's JSON response."""
    if not isinstance(payload, dict):
        raise UpstreamServiceError("Crawl4AI Cloud returned an invalid response.")

    markdown = payload.get("markdown")
    metadata = payload.get("metadata")
    if not isinstance(markdown, str) or not markdown.strip():
        result = payload.get("result")
        if isinstance(result, dict):
            markdown = result.get("markdown")
            metadata = result.get("metadata")
    if not isinstance(markdown, str) or not markdown.strip():
        raise UpstreamServiceError(
            "Crawl4AI Cloud returned no readable page content. The page may be blocked or require authentication."
        )

    if not isinstance(metadata, dict):
        metadata = {}
    title = payload.get("title") or metadata.get("title") or metadata.get("og:title")
    final_url = payload.get("url") or payload.get("final_url") or fallback_url
    if not isinstance(final_url, str) or not final_url.strip():
        final_url = fallback_url
    if not isinstance(title, str) or not title.strip():
        title = urlsplit(final_url).hostname or final_url
    title = re.sub(r"\s+", " ", title).strip()[:200]
    return title, final_url, markdown


async def _crawl_with_cloud_api(url: str) -> tuple[str, str, str]:
    """Crawl using Crawl4AI's hosted API, avoiding a local browser binary."""
    timeout_seconds = max(10, min(int(settings.crawl4ai_api_timeout_seconds), 120))
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
        ) as client:
            response = await client.post(
                "https://api.crawl4ai.com/scrape",
                headers={"Authorization": f"Bearer {settings.crawl4ai_api_key.strip()}"},
                json={
                    "url": url,
                    "format": "md",
                    "parse": {"metadata": True},
                },
            )
    except httpx.TimeoutException as exc:
        raise UpstreamServiceError(
            "Website extraction timed out while waiting for Crawl4AI Cloud. Retry the page or increase CRAWL4AI_API_TIMEOUT_SECONDS."
        ) from exc
    except httpx.RequestError as exc:
        logger.error(f"Crawl4AI Cloud request failed: {type(exc).__name__}")
        raise UpstreamServiceError(
            "The website crawler service could not be reached. Retry in a moment."
        ) from exc

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if response.status_code == 401:
        raise UpstreamServiceError(
            "Crawl4AI Cloud rejected the API key. Check CRAWL4AI_API_KEY in the Vercel environment variables."
        )
    if response.status_code == 402:
        raise UpstreamServiceError(
            "Crawl4AI Cloud has no credits available. Check the Crawl4AI account usage or billing page."
        )
    if response.status_code == 403:
        detail = ""
        if isinstance(payload, dict):
            detail = str(payload.get("error") or payload.get("detail") or "").lower()
        if "blocked" in detail or "login-wall" in detail:
            raise UpstreamServiceError(
                "The website blocked automated crawling or requires authentication."
            )
        raise UpstreamServiceError(
            "Crawl4AI Cloud denied this crawl. Check the API key and account access."
        )
    if response.status_code in {429, 503}:
        raise UpstreamServiceError(
            "Crawl4AI Cloud is temporarily rate-limited or busy. Please retry in a few seconds."
        )
    if response.status_code >= 400:
        detail = ""
        if isinstance(payload, dict):
            detail = str(payload.get("error") or payload.get("detail") or "")
        logger.warning(
            f"Crawl4AI Cloud returned HTTP {response.status_code} for {url}: {detail[:180]}"
        )
        if response.status_code in {502, 504}:
            raise UpstreamServiceError(
                "The target website did not return usable content to Crawl4AI. It may be unavailable or blocking crawlers."
            )
        raise UpstreamServiceError(
            "Crawl4AI Cloud could not extract this page. Check the URL and try again."
        )

    return _parse_cloud_payload(payload, url)


async def crawl_website(url: str) -> CrawledWebsite:
    """Crawl one user-supplied URL into normalized Markdown for RAG."""
    dns_cache: dict[str, bool] = {}
    normalized_url = await validate_public_website_url(url, dns_cache)

    if settings.crawl4ai_api_key.strip():
        # Serverless mode: the hosted crawler owns the browser; Chromium is not
        # downloaded into or launched from the Vercel function.
        title, final_url, extracted_markdown = await _crawl_with_cloud_api(normalized_url)
    else:
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
        except ImportError as exc:
            raise UpstreamServiceError(
                "Website crawling needs either CRAWL4AI_API_KEY for Crawl4AI Cloud, "
                "or the optional local package installed with 'pip install crawl4ai==0.9.5' "
                "followed by 'crawl4ai-setup'."
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
            excluded_tags=["script", "style", "noscript", "svg", "canvas", "nav", "footer", "form"],
            word_count_threshold=3,
            wait_until="domcontentloaded",
            page_timeout=max(5, min(int(settings.crawl4ai_timeout_seconds), 45)) * 1000,
            delay_before_return_html=0.2,
            check_robots_txt=False,
        )

        try:
            crawler = AsyncWebCrawler(config=browser_config, verbose=False)
            # Register the egress guard before browser startup creates page contexts.
            crawler.crawler_strategy.set_hook("on_page_context_created", configure_page_routes)
            async with crawler:
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
                    "Local Chromium is unavailable. Configure CRAWL4AI_API_KEY to use Crawl4AI Cloud "
                    "(no local browser required), install Chromium with crawl4ai-setup, or configure CRAWL4AI_CDP_URL."
                ) from exc
            raise UpstreamServiceError("The website could not be extracted. Check that it is public and accessible, then retry.") from exc

        if not getattr(result, "success", False):
            message = str(getattr(result, "error_message", "") or "The crawler returned no result.")
            logger.warning(f"Crawl4AI returned an unsuccessful result for {normalized_url}: {message}")
            raise UpstreamServiceError("The website could not be extracted. It may block automated browsers or require authentication.")

        final_url = getattr(result, "url", None) or normalized_url
        title = _extract_title(result, final_url)
        extracted_markdown = _extract_markdown(result)

    # Validate the final URL before storing it as the durable source reference.
    final_url = await validate_public_website_url(final_url, dns_cache)
    markdown = normalize_extracted_text(extracted_markdown, extraction_source="website")
    if not markdown:
        raise BadRequestError("No readable page content was found. Try a public article or documentation page.")
    truncated = len(markdown) > MAX_WEBSITE_TEXT_CHARS
    if truncated:
        candidate = markdown[:MAX_WEBSITE_TEXT_CHARS]
        boundary = candidate.rfind("\n")
        markdown = candidate[:boundary].rstrip() if boundary > MAX_WEBSITE_TEXT_CHARS * 0.75 else candidate.rstrip()
    return CrawledWebsite(
        title=title,
        url=final_url,
        markdown=markdown,
        truncated=truncated,
    )

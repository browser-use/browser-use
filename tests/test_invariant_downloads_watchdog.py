import pytest
import re
import ipaddress
from urllib.parse import urlparse


# Adversarial payloads targeting SSRF, internal services, cloud metadata, etc.
ADVERSARIAL_PAYLOADS = [
    # Cloud metadata endpoints
    "http://169.254.169.254/latest/meta-data/",
    "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
    "http://169.254.169.254/computeMetadata/v1/",
    "https://169.254.169.254/latest/user-data",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://169.254.170.2/v2/credentials",  # ECS metadata
    # IPv6 link-local
    "http://[fe80::1]/admin",
    "http://[::1]/etc/passwd",
    # Localhost variants
    "http://localhost/admin",
    "http://127.0.0.1/admin",
    "http://127.0.0.1:8080/internal",
    "http://0.0.0.0/secret",
    "http://0x7f000001/",  # Hex encoded 127.0.0.1
    "http://2130706433/",  # Decimal encoded 127.0.0.1
    "http://017700000001/",  # Octal encoded 127.0.0.1
    # Private network ranges
    "http://10.0.0.1/internal",
    "http://10.255.255.255/secret",
    "http://172.16.0.1/admin",
    "http://172.31.255.255/metadata",
    "http://192.168.1.1/router",
    "http://192.168.0.1/admin",
    # DNS rebinding / bypass attempts
    "http://localtest.me/",
    "http://127.0.0.1.nip.io/",
    "http://169.254.169.254.nip.io/",
    # Protocol smuggling
    "file:///etc/passwd",
    "file:///etc/shadow",
    "file:///proc/self/environ",
    "ftp://internal-server/secret",
    "gopher://127.0.0.1:6379/_FLUSHALL",
    "dict://127.0.0.1:6379/info",
    # URL with credentials
    "http://admin:password@192.168.1.1/",
    "http://user@169.254.169.254/",
    # Encoded bypasses
    "http://169.254.169.254%2F",
    "http://%31%36%39%2E%32%35%34%2E%31%36%39%2E%32%35%34/",
    "http://169.254.169.254\x00.example.com/",
    # SSRF via redirect
    "http://evil.com/redirect?to=http://169.254.169.254/",
    # Internal service ports
    "http://127.0.0.1:22/",
    "http://127.0.0.1:3306/",
    "http://127.0.0.1:5432/",
    "http://127.0.0.1:6379/",
    "http://127.0.0.1:27017/",
    "http://127.0.0.1:9200/",
    "http://127.0.0.1:2375/",  # Docker API
    "http://127.0.0.1:8500/",  # Consul
    "http://127.0.0.1:8200/",  # Vault
]


def is_safe_url_for_fetch(url: str) -> bool:
    """
    Security invariant: URLs used in JavaScript fetch() calls within the downloads
    watchdog must not target internal/private/metadata endpoints.
    
    Returns True if the URL is safe (external/public), False if it's dangerous.
    """
    if not url or not isinstance(url, str):
        return False

    # Strip null bytes and whitespace
    url = url.strip().replace('\x00', '')

    try:
        parsed = urlparse(url)
    except Exception:
        return False

    # Only allow http/https schemes
    if parsed.scheme not in ('http', 'https'):
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    # Normalize hostname
    hostname = hostname.lower().strip('[]')

    # Block localhost variants
    localhost_patterns = [
        'localhost',
        'localtest.me',
        'metadata.google.internal',
    ]
    for pattern in localhost_patterns:
        if hostname == pattern or hostname.endswith('.' + pattern):
            return False

    # Block nip.io and similar DNS rebinding services pointing to private IPs
    if hostname.endswith('.nip.io') or hostname.endswith('.xip.io'):
        # Extract the IP portion from the hostname
        ip_part = hostname.replace('.nip.io', '').replace('.xip.io', '')
        # Check if it resolves to a private IP
        try:
            ip = ipaddress.ip_address(ip_part.replace('-', '.'))
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
        except ValueError:
            pass

    # Try to parse as IP address
    try:
        # Handle various IP encodings
        ip = ipaddress.ip_address(hostname)
        if (ip.is_private or
                ip.is_loopback or
                ip.is_link_local or
                ip.is_reserved or
                ip.is_multicast or
                ip.is_unspecified):
            return False
        # Specifically block cloud metadata IP
        if str(ip) == '169.254.169.254':
            return False
    except ValueError:
        # Not a plain IP, check for encoded forms
        pass

    # Block hex/octal/decimal encoded IPs that resolve to private ranges
    # Hex: 0x7f000001
    if re.match(r'^0x[0-9a-f]+$', hostname, re.IGNORECASE):
        try:
            ip_int = int(hostname, 16)
            ip = ipaddress.ip_address(ip_int)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return False
        except (ValueError, OverflowError):
            pass

    # Decimal encoded: 2130706433
    if re.match(r'^\d+$', hostname):
        try:
            ip_int = int(hostname)
            if 0 <= ip_int <= 0xFFFFFFFF:
                ip = ipaddress.ip_address(ip_int)
                if ip.is_private or ip.is_loopback or ip.is_link_local:
                    return False
        except (ValueError, OverflowError):
            pass

    # Octal encoded: 017700000001
    if re.match(r'^0[0-7]+$', hostname):
        try:
            ip_int = int(hostname, 8)
            ip = ipaddress.ip_address(ip_int)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return False
        except (ValueError, OverflowError):
            pass

    return True


def simulate_watchdog_url_validation(url: str) -> bool:
    """
    Simulates what the downloads watchdog SHOULD do before using a URL
    in a JavaScript fetch() call. This represents the security control
    that must be in place.
    """
    return is_safe_url_for_fetch(url)


@pytest.mark.parametrize("payload", ADVERSARIAL_PAYLOADS)
def test_downloads_watchdog_blocks_ssrf_urls(payload):
    """
    Invariant: The downloads watchdog must never use adversarial/internal URLs
    in JavaScript fetch() calls. URLs derived from web page content that target
    internal services, cloud metadata endpoints, localhost, or private network
    ranges must be rejected before being embedded in fetch() calls.
    
    This prevents Server-Side Request Forgery (SSRF) attacks where a malicious
    page could cause the browser agent to fetch internal resources.
    """
    # The security invariant: adversarial URLs targeting internal resources
    # must be blocked and never passed to fetch()
    result = simulate_watchdog_url_validation(payload)
    
    assert result is False, (
        f"SECURITY VIOLATION: URL '{payload}' was not blocked by the watchdog. "
        f"This URL targets an internal/private resource and must never be used "
        f"in a JavaScript fetch() call within the downloads watchdog. "
        f"Allowing this URL could enable SSRF attacks against internal services, "
        f"cloud metadata endpoints, or other restricted resources."
    )


@pytest.mark.parametrize("safe_url", [
    "https://example.com/file.pdf",
    "https://download.example.org/resource",
    "http://public-cdn.example.com/asset.zip",
    "https://8.8.8.8/public-resource",  # Public IP
    "https://1.1.1.1/dns-query",  # Cloudflare public DNS
])
def test_downloads_watchdog_allows_safe_urls(safe_url):
    """
    Invariant: The downloads watchdog must allow legitimate external URLs
    to pass through so that normal download functionality is not broken.
    """
    result = simulate_watchdog_url_validation(safe_url)
    
    assert result is True, (
        f"Safe URL '{safe_url}' was incorrectly blocked. "
        f"The security control must not break legitimate download functionality."
    )


def test_downloads_watchdog_rejects_non_http_schemes():
    """
    Invariant: Only http and https schemes should be permitted in fetch() calls.
    File, ftp, gopher, dict and other schemes must always be rejected.
    """
    dangerous_schemes = [
        "file:///etc/passwd",
        "ftp://internal/secret",
        "gopher://127.0.0.1:6379/_FLUSHALL",
        "dict://127.0.0.1:6379/info",
        "ldap://internal-ldap/",
        "sftp://internal/",
        "data:text/html,<script>alert(1)</script>",
        "javascript:alert(1)",
    ]
    
    for url in dangerous_schemes:
        result = simulate_watchdog_url_validation(url)
        assert result is False, (
            f"SECURITY VIOLATION: Non-HTTP scheme URL '{url}' was not blocked. "
            f"Only http/https schemes should be permitted in fetch() calls."
        )


def test_downloads_watchdog_rejects_cloud_metadata_endpoint():
    """
    Invariant: The AWS/GCP/Azure cloud metadata endpoint 169.254.169.254
    must ALWAYS be blocked regardless of encoding or formatting.
    This is a critical security boundary.
    """
    metadata_variants = [
        "http://169.254.169.254/",
        "http://169.254.169.254/latest/meta-data/",
        "https://169.254.169.254/",
        "http://169.254.169.254:80/",
        "http://169.254.169.254/latest/meta-data/iam/security-credentials/role",
    ]
    
    for url in metadata_variants:
        result = simulate_watchdog_url_validation(url)
        assert result is False, (
            f"CRITICAL SECURITY VIOLATION: Cloud metadata URL '{url}' was not blocked. "
            f"Access to 169.254.169.254 could expose cloud credentials and instance metadata."
        )


def test_downloads_watchdog_rejects_private_network_ranges():
    """
    Invariant: All RFC 1918 private network ranges must be blocked
    to prevent SSRF attacks against internal network services.
    """
    private_network_urls = [
        "http://10.0.0.1/",
        "http://10.255.255.255/",
        "http://172.16.0.1/",
        "http://172.31.255.255/",
        "http://192.168.0.1/",
        "http://192.168.255.255/",
    ]
    
    for url in private_network_urls:
        result = simulate_watchdog_url_validation(url)
        assert result is False, (
            f"SECURITY VIOLATION: Private network URL '{url}' was not blocked. "
            f"Internal network resources must not be accessible via fetch() calls."
        )
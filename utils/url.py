from urllib.parse import urlsplit, urlunsplit


def canonical_url(url: str) -> str:
    """Return ``url`` without query parameters or fragments.

    Parameters
    ----------
    url: str
        The original URL.

    Returns
    -------
    str
        The canonicalized URL containing only scheme, netloc, and path.
    """
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

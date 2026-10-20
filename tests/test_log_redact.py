import logging

from vision.__main__ import Redact, redact


def test_secrets_in_urls_are_masked():
    url = "GET https://api.tomtom.com/search/2/geocode/Windsor.json?key=abc123&limit=1"
    assert redact(url) == "GET https://api.tomtom.com/search/2/geocode/Windsor.json?key=<hidden>&limit=1"
    assert "s3cr3t" not in redact("https://x.test/cb?client_secret=s3cr3t&access_token=tok9&api_key=k1")
    assert redact("https://api.telegram.org/bot123456:AAH-xyz_9/sendMessage") == "https://api.telegram.org/bot<hidden>/sendMessage"
    assert redact("Rio Grande keyboard monkey=1") == "Rio Grande keyboard monkey=1"           # only whole parameter names


def test_the_log_filter_masks_arguments_and_exception_text():
    rec = logging.LogRecord("x", logging.WARNING, __file__, 1, "failed %s", ("https://a.test/?key=abc123",), None)
    assert Redact().filter(rec) and "abc123" not in rec.getMessage()
    try:
        raise RuntimeError("Client error for url https://a.test/?token=zzz999")
    except RuntimeError:
        import sys
        rec = logging.LogRecord("x", logging.ERROR, __file__, 1, "boom", None, sys.exc_info())
    Redact().filter(rec)
    assert "zzz999" not in rec.exc_text and "token=<hidden>" in rec.exc_text

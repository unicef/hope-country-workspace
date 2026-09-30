# Content-Security-Policy (django-csp).
#
# django-csp >= 4.0 uses the CONTENT_SECURITY_POLICY dict format.
# The legacy CSP_* top-level settings are no longer honored and only emit
# a warning via the csp.E001 system check.
#
# `'unsafe-inline'` / `'unsafe-eval'` are still required by the bundled
# admin/editor/charting assets. Migrating away from them (nonces / hashes,
# strict CSP) must be done incrementally; start with CONTENT_SECURITY_POLICY
# in "report-only" mode and monitor before enforcing a stricter policy, see
# https://cheatsheetseries.owasp.org/cheatsheets/Content_Security_Policy_Cheat_Sheet.html

CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ["'none'"],
        "style-src": [
            "'self'",
            "'unsafe-inline'",
            "same-origin",
            "cdnjs.cloudflare.com",
            "fonts.googleapis.com",
            "fonts.gstatic.com",
            "saunihopedev.blob.core.windows.net",
            "saunihopestg.blob.core.windows.net",
            "saunihopetrn.blob.core.windows.net",
            "saunihopeprd.blob.core.windows.net",
        ],
        "script-src": [
            "'self'",
            "'unsafe-inline'",
            "same-origin",
            "blob:",
            "cdnjs.cloudflare.com",
            "saunihopedev.blob.core.windows.net",
            "saunihopestg.blob.core.windows.net",
            "saunihopetrn.blob.core.windows.net",
            "saunihopeprd.blob.core.windows.net",
        ],
        "img-src": [
            "'self'",
            "'unsafe-inline'",
            "same-origin",
            "blob:",
            "data:",
            "cdn.redoc.ly",
            "saunihopedev.blob.core.windows.net",
            "saunihopestg.blob.core.windows.net",
            "saunihopetrn.blob.core.windows.net",
            "saunihopeprd.blob.core.windows.net",
        ],
        "font-src": [
            "'self'",
            "same-origin",
            "fonts.googleapis.com",
            "fonts.gstatic.com",
            "blob:",
            "saunihopedev.blob.core.windows.net",
            "saunihopestg.blob.core.windows.net",
            "saunihopetrn.blob.core.windows.net",
            "saunihopeprd.blob.core.windows.net",
        ],
        "connect-src": ["'self'"],
        "frame-src": ["'self'"],
        "object-src": ["'none'"],
        "base-uri": ["'self'"],
    },
}

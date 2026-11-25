# -*- coding: utf-8 -*-
import base64
from typing import List, Union

KEY = 0x42

def deobfuscate(data: Union[List[int], str]) -> str:
    if not data or not isinstance(data, list):
        return ""
    return "".join(chr(b ^ KEY) for b in data)

def obfuscate(data: str) -> List[int]:
    if not data:
        return []
    return [ord(c) ^ KEY for c in data]

def _b(s):
    return base64.b64decode(s).decode("utf-8")

startup_snippet = _b("IyAtLS0tLSBBTSBMaXRlIFRyYWt0IHN0YXJ0dXAgc3luYyBwYXRjaCBCRUdJTiAtLS0tLQpkZWYgd2FpdF9mb3JfYW1fdHJha3QodGltZW91dD0xMjAsIG1heF9hZ2U9MTgwKToKICAgIGltcG9ydCB0aW1lCiAgICBpbXBvcnQgeGJtYwogICAgaW1wb3J0IHhibWNhZGRvbgoKICAgIHdhaXRlZCA9IDAKCiAgICB3aGlsZSB3YWl0ZWQgPCB0aW1lb3V0OgogICAgICAgIHRyeToKICAgICAgICAgICAgYW0gPSB4Ym1jYWRkb24uQWRkb24oJ3NjcmlwdC5tb2R1bGUuYWNjdG1ncicpCiAgICAgICAgICAgIHJlYWR5ID0gYW0uZ2V0U2V0dGluZygnYW1fdHJha3RfcmVhZHknKQogICAgICAgICAgICBsYXN0X3ByZXBhcmUgPSBhbS5nZXRTZXR0aW5nKCdhbV9sYXN0X3ByZXBhcmUnKQoKICAgICAgICAgICAgaWYgcmVhZHkgPT0gJ3RydWUnIGFuZCBsYXN0X3ByZXBhcmU6CiAgICAgICAgICAgICAgICBhZ2UgPSBpbnQodGltZS50aW1lKCkpIC0gaW50KGxhc3RfcHJlcGFyZSkKICAgICAgICAgICAgICAgIGlmIDAgPD0gYWdlIDw9IG1heF9hZ2U6CiAgICAgICAgICAgICAgICAgICAgcmV0dXJuIFRydWUKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgogICAgICAgIHhibWMuc2xlZXAoMTAwMCkKICAgICAgICB3YWl0ZWQgKz0gMQoKICAgIHJldHVybiBGYWxzZQoKd2FpdF9mb3JfYW1fdHJha3QoKQojIC0tLS0tIEFNIExpdGUgVHJha3Qgc3RhcnR1cCBzeW5jIHBhdGNoIEVORCAtLS0tLQoK")
startup_marker = "# ----- AM Lite Trakt startup sync patch BEGIN -----"

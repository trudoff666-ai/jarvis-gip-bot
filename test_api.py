import os

for line in open(".env"):
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ[k] = v

from anthropic import Anthropic

c = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
try:
    r = c.messages.create(
        model="claude-opus-4-7",
        max_tokens=100,
        messages=[{"role": "user", "content": "привет"}]
    )
    print("OK:", r.content[0].text[:100])
except Exception as e:
    print("ERROR:", type(e).__name__, str(e))

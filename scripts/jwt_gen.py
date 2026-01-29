import os, jwt, sys
from datetime import datetime, timedelta, timezone

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
ALG = "HS256"

def make(sub: str, roles: list[str], ttl_minutes: int = 120):
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "roles": roles,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl_minutes)).timestamp())
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=ALG)
    return token

if __name__ == "__main__":
    sub = sys.argv[1] if len(sys.argv) > 1 else "user:ops1"
    roles = sys.argv[2].split(",") if len(sys.argv) > 2 else ["ops.block:read","ops.block:create","ops.block:release"]
    print(make(sub, roles))

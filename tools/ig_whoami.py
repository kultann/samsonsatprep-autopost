"""Check an Instagram token and print the IG user id to save as IG_USER_ID.

IG_ACCESS_TOKEN=... python tools/ig_whoami.py
"""
import os
import sys

import requests

token = os.environ.get("IG_ACCESS_TOKEN")
if not token:
    sys.exit("Set IG_ACCESS_TOKEN first.")
r = requests.get(
    "https://graph.instagram.com/me",
    params={"fields": "user_id,username,account_type", "access_token": token},
    timeout=60,
)
data = r.json()
if "user_id" not in data:
    sys.exit(f"Failed: {data}")
print(f"username: @{data.get('username')}  account_type: {data.get('account_type')}")
print(f"IG_USER_ID = {data['user_id']}")

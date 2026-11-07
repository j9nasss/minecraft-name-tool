#!/usr/bin/env python3
"""
Prints a Minecraft access token for YOUR account using Microsoft's device-code login.

Needs an Azure app registration (public client flows enabled) whose client ID
has been approved by Mojang for the Minecraft API.

Usage
  pip install requests
  python mc_login.py YOUR-CLIENT-ID
  (or set MC_CLIENT_ID instead of passing it as an argument)

The token is printed to this terminal only. Treat it like a password and never share it.
It expires after about 24 hours.
"""
import os
import sys
import time

import requests

MS = "https://login.microsoftonline.com/consumers/oauth2/v2.0"
SCOPE = "XboxLive.signin offline_access"
JSON = {"Content-Type": "application/json", "Accept": "application/json"}

XSTS_ERRORS = {
    2148916233: "This Microsoft account has no Xbox profile. Sign in at xbox.com once to create one.",
    2148916235: "Xbox Live isn't available in your country/region.",
    2148916238: "This is a child account; it must be added to a Microsoft family first.",
}


def die(msg):
    sys.exit(f"\nError: {msg}")


def device_login(client_id):
    r = requests.post(f"{MS}/devicecode", data={"client_id": client_id, "scope": SCOPE}, timeout=15)
    if r.status_code != 200:
        die(f"Could not start login ({r.status_code}): {r.text[:300]}")
    d = r.json()
    print("\n" + d["message"] + "\n")

    interval = d.get("interval", 5)
    deadline = time.time() + d.get("expires_in", 900)
    while time.time() < deadline:
        time.sleep(interval)
        t = requests.post(
            f"{MS}/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": client_id,
                "device_code": d["device_code"],
            },
            timeout=15,
        )
        j = t.json()
        if t.status_code == 200:
            return j["access_token"]
        err = j.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        die(f"Login failed: {j.get('error_description', err)}")
    die("Login code expired. Run the script again.")


def xbox_chain(ms_token):
    r = requests.post(
        "https://user.auth.xboxlive.com/user/authenticate",
        json={
            "Properties": {"AuthMethod": "RPS", "SiteName": "user.auth.xboxlive.com", "RpsTicket": f"d={ms_token}"},
            "RelyingParty": "http://auth.xboxlive.com",
            "TokenType": "JWT",
        },
        headers=JSON,
        timeout=15,
    )
    if r.status_code != 200:
        die(f"Xbox Live sign-in failed ({r.status_code}): {r.text[:300]}")
    xbl = r.json()["Token"]

    r = requests.post(
        "https://xsts.auth.xboxlive.com/xsts/authorize",
        json={
            "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl]},
            "RelyingParty": "rp://api.minecraftservices.com/",
            "TokenType": "JWT",
        },
        headers=JSON,
        timeout=15,
    )
    if r.status_code != 200:
        code = r.json().get("XErr") if r.headers.get("content-type", "").startswith("application/json") else None
        die(XSTS_ERRORS.get(code, f"XSTS authorization failed ({r.status_code}): {r.text[:300]}"))
    x = r.json()
    return x["DisplayClaims"]["xui"][0]["uhs"], x["Token"]


def minecraft_token(uhs, xsts):
    r = requests.post(
        "https://api.minecraftservices.com/authentication/login_with_xbox",
        json={"identityToken": f"XBL3.0 x={uhs};{xsts}"},
        headers=JSON,
        timeout=15,
    )
    if r.status_code == 403:
        die(
            "Minecraft services refused this app (403). Your client ID probably hasn't been "
            "approved by Mojang yet."
        )
    if r.status_code != 200:
        die(f"Minecraft login failed ({r.status_code}): {r.text[:300]}")
    return r.json()["access_token"]


def main():
    client_id = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("MC_CLIENT_ID", "")).strip()
    if not client_id:
        die("Pass your Azure client ID: python mc_login.py YOUR-CLIENT-ID")

    token = minecraft_token(*xbox_chain(device_login(client_id)))

    p = requests.get(
        "https://api.minecraftservices.com/minecraft/profile",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    if p.status_code == 200:
        print(f"Signed in as: {p.json().get('name')}")
    else:
        print("Note: token works, but no Java Edition profile was found on this account.")

    print("\nYour token (valid ~24h). In PowerShell:\n")
    print(f'  $env:MC_TOKEN="{token}"\n')
    print("Mac/Linux:\n")
    print(f'  export MC_TOKEN="{token}"\n')


if __name__ == "__main__":
    main()

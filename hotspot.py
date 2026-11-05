"""
Laptop Wi-Fi helpers for phone pairing.

  current_wifi()   -> the Wi-Fi the laptop is on right now (name + security)
  is_isolated()    -> True for open / college / guest Wi-Fi, which blocks
                      devices from seeing each other (pairing can't work there)
  start()          -> turns ON Windows Mobile hotspot and returns its name and
                      password, so the phone can join the LAPTOP's own Wi-Fi
  client_count()   -> how many devices are connected to the hotspot

Uses Windows' built-in tethering API through Windows PowerShell - nothing to install.
"""

import re
import subprocess
import sys

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

_PS_HEAD = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
$p = [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime]::GetInternetConnectionProfile()
if ($p -eq $null) { 'ERR=no internet connection'; exit }
$tm = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime]::CreateFromConnectionProfile($p)
"""

_PS_START = _PS_HEAD + r"""
if ($tm.TetheringOperationalState -ne 'On') {
  $r = Await ($tm.StartTetheringAsync()) ([Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult])
  if ($r.Status -ne 'Success') { 'ERR=' + $r.Status + ' ' + $r.AdditionalErrorMessage }
}
$c = $tm.GetCurrentAccessPointConfiguration()
'STATE=' + $tm.TetheringOperationalState
'SSID=' + $c.Ssid
'PASS=' + $c.Passphrase
"""

_PS_CLIENTS = _PS_HEAD + r"""
'CLIENTS=' + $tm.ClientCount
"""


def _ps(script: str, timeout: float = 25) -> dict:
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                             capture_output=True, text=True, timeout=timeout,
                             creationflags=_NO_WINDOW)
    except Exception as e:
        return {"ERR": str(e)}
    res = {}
    for line in (out.stdout or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            res[k.strip()] = v.strip()
    if not res and out.stderr:
        res["ERR"] = out.stderr.strip().splitlines()[-1][:200]
    return res


def current_wifi() -> tuple[str, str]:
    """(SSID, authentication) of the Wi-Fi the laptop is using, or ("", "")."""
    try:
        out = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True,
                             text=True, timeout=5, creationflags=_NO_WINDOW).stdout or ""
    except Exception:
        return "", ""
    ssid = re.search(r"^\s*SSID\s*:\s*(.+)$", out, re.M)
    auth = re.search(r"^\s*Authentication\s*:\s*(.+)$", out, re.M)
    return (ssid.group(1).strip() if ssid else ""), (auth.group(1).strip() if auth else "")


def is_isolated(ssid: str, auth: str) -> bool:
    if not ssid:
        return False
    if "open" in (auth or "").lower():
        return True
    return bool(re.search(r"student|campus|guest|college|univ|hostel|public|free|staff|lab", ssid, re.I))


def start() -> dict:
    """Turns on Mobile hotspot. Returns {'ssid','password'} or {'error'}."""
    import time
    r = {}
    for _ in range(4):                       # it can take a few seconds to switch on ("InTransition")
        r = _ps(_PS_START)
        if r.get("SSID") and r.get("STATE", "").lower() == "on":
            return {"ssid": r["SSID"], "password": r.get("PASS", "")}
        if "transition" not in (r.get("STATE", "") + r.get("ERR", "")).lower():
            break
        time.sleep(3)
    return {"error": r.get("ERR") or f"hotspot state {r.get('STATE', 'unknown')}"}


_PS_CLIENT_IPS = _PS_HEAD + r"""
foreach ($c in $tm.GetTetheringClients()) { foreach ($h in $c.HostNames) { 'IP=' + $h.CanonicalName } }
"""


def client_ips() -> list[str]:
    """IPv4 addresses of devices connected to the laptop's hotspot."""
    ips = []
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", _PS_CLIENT_IPS],
                             capture_output=True, text=True, timeout=15, creationflags=_NO_WINDOW).stdout or ""
        ips = re.findall(r"IP=(\d+\.\d+\.\d+\.\d+)", out)
    except Exception:
        pass
    return ips or arp_neighbors("192.168.137.")


def arp_neighbors(prefix: str = "") -> list[str]:
    """Devices this laptop has recently talked to on the local network (from the ARP table)."""
    try:
        out = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=5,
                             creationflags=_NO_WINDOW).stdout or ""
    except Exception:
        return []
    ips = []
    for ip, kind in re.findall(r"(\d+\.\d+\.\d+\.\d+)\s+[0-9a-f-]{17}\s+(\w+)", out, re.I):
        last = int(ip.rsplit(".", 1)[1])
        first = int(ip.split(".", 1)[0])
        if kind.lower() == "dynamic" and ip.startswith(prefix) and 1 < last < 255 and first < 224:
            ips.append(ip)
    return list(dict.fromkeys(ips))


def client_count() -> int:
    try:
        return int(_ps(_PS_CLIENTS, timeout=15).get("CLIENTS", "0"))
    except ValueError:
        return 0


def wifi_qr_payload(ssid: str, password: str) -> str:
    """Standard Wi-Fi join QR - any phone camera can scan it."""
    esc = lambda s: re.sub(r'([\\;,":])', r"\\\1", s)
    return f"WIFI:T:WPA;S:{esc(ssid)};P:{esc(password)};;"

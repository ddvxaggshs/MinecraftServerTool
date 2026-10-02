"""GitHub Releases transport. Credentials stay in memory, never in output/files."""
import hashlib
import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request

REPO = "ddvxaggshs/MinecraftServerTool"
API = f"https://api.github.com/repos/{REPO}"


class GitHubRelease:
    def __init__(self, root):
        result = subprocess.run(["git", "credential", "fill"], cwd=root,
            input="protocol=https\nhost=github.com\n\n", text=True, capture_output=True)
        values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        if result.returncode or not values.get("password"):
            raise RuntimeError("GitHub authentication is unavailable. Sign in using Git Credential Manager and retry.")
        self._token = values["password"]
        repo = self.request("GET", API)
        if not repo.get("permissions", {}).get("push"):
            raise RuntimeError("The authenticated GitHub account cannot publish this repository.")

    def request(self, method, url, body=None, binary=False, missing_ok=False):
        data = body if binary else json.dumps(body).encode() if body is not None else None
        headers = {"Authorization": "Bearer " + self._token,
                   "User-Agent": "MinecraftRelay-Publisher", "Accept": "application/vnd.github+json"}
        if data is not None:
            headers["Content-Type"] = "application/octet-stream" if binary else "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if missing_ok and error.code == 404:
                return None
            raise RuntimeError(f"GitHub API returned HTTP {error.code}; publish stopped.") from None

    def exists(self, state):
        return self.request("GET", API + "/releases/tags/v" + state, missing_ok=True) is not None

    def publish(self, state, commit, folder):
        release = self.request("POST", API + "/releases", {
            "tag_name": "v" + state, "target_commitish": commit,
            "name": "Minecraft Relay " + state, "draft": True,
            "body": "Download updater.exe into an empty folder and run it to install. Full ZIP layout: launcher.exe, updater.exe, app/, data/, playit/. Existing 3.8.x users must run the standalone updater once to migrate; their data is preserved.",
        })
        upload = release["upload_url"].split("{")[0]
        for name in ("updater.exe", "launcher.exe", "MinecraftManager-app.zip", "MinecraftManager-windows.zip", "MinecraftManager-source.zip"):
            path = folder / name
            payload = path.read_bytes()
            asset = self.request("POST", upload + "?name=" + urllib.parse.quote(path.name), payload, binary=True)
            if asset.get("state") != "uploaded" or asset.get("size") != len(payload):
                raise RuntimeError("GitHub asset upload did not complete; release remains a draft.")
            if asset.get("digest") and asset["digest"] != "sha256:" + hashlib.sha256(payload).hexdigest():
                raise RuntimeError("Uploaded asset checksum mismatch; release remains a draft.")
        release = self.request("PATCH", API + "/releases/" + str(release["id"]), {"draft": False})
        return release["html_url"]

import http.server
import urllib.parse
import urllib.request
import webbrowser
import ssl
import tempfile
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

try:
    import requests
except ImportError:
    print("requestsライブラリが見つかりません。.venv/Scripts/python で実行してください。")
    sys.exit(1)

CLIENT_ID     = "4538236309835509"
CLIENT_SECRET = "d07be6c20bac937d59e8aa275962fa4a"
REDIRECT_URI  = "https://localhost:8443"

# 自己署名証明書を生成
key  = rsa.generate_private_key(public_exponent=65537, key_size=2048)
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
cert = (
    x509.CertificateBuilder()
    .subject_name(name)
    .issuer_name(name)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(datetime.now(timezone.utc))
    .not_valid_after(datetime.now(timezone.utc) + timedelta(hours=1))
    .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
    .sign(key, hashes.SHA256())
)

certfile = tempfile.mktemp(suffix=".pem")
keyfile  = tempfile.mktemp(suffix=".key")
open(certfile, "wb").write(cert.public_bytes(serialization.Encoding.PEM))
open(keyfile,  "wb").write(key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.TraditionalOpenSSL,
    serialization.NoEncryption()
))

code_box = []

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        self.send_response(200)
        self.end_headers()
        if "code" in params:
            code_box.append(params["code"][0])
            self.wfile.write("認証成功！このタブを閉じてターミナルを確認してください。".encode("utf-8"))
        else:
            self.wfile.write("waiting...".encode())
    def log_message(self, *args):
        pass

server = http.server.HTTPServer(("localhost", 8443), Handler)
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain(certfile, keyfile)
server.socket = ctx.wrap_socket(server.socket, server_side=True)

url = (
    f"https://threads.net/oauth/authorize"
    f"?client_id={CLIENT_ID}"
    f"&redirect_uri={urllib.parse.quote(REDIRECT_URI, safe='')}"
    f"&scope=threads_basic,threads_content_publish"
    f"&response_type=code"
)

print("=" * 50)
print("ブラウザが開きます。")
print("証明書の警告が出たら「詳細設定」→「続行」を選んでください。")
print("=" * 50)
webbrowser.open(url)
server.handle_request()

os.unlink(certfile)
os.unlink(keyfile)

if not code_box:
    print("コードが取得できませんでした")
    sys.exit(1)

code = code_box[0]
print("✅ 認証コード取得成功")

# 短期トークンを取得
print("短期トークンを取得中...")
r = requests.post("https://graph.threads.net/oauth/access_token", data={
    "client_id":     CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "redirect_uri":  REDIRECT_URI,
    "code":          code,
    "grant_type":    "authorization_code",
})
if r.status_code != 200:
    print(f"エラー: {r.text}")
    sys.exit(1)
data        = r.json()
short_token = data["access_token"]
user_id     = str(data["user_id"])
print(f"✅ 短期トークン取得成功（ユーザーID: {user_id}）")

# 長期トークン（60日）を取得
print("長期トークン（60日）を取得中...")
r = requests.get("https://graph.threads.net/access_token", params={
    "grant_type":    "th_exchange_token",
    "client_id":     CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "access_token":  short_token,
})
if r.status_code != 200:
    print(f"エラー: {r.text}")
    sys.exit(1)
data       = r.json()
long_token = data["access_token"]
expires    = data.get("expires_in", 0) // 86400
print(f"✅ 長期トークン取得成功（有効期限: {expires}日）")

# .env に保存
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
with open(env_path, "r", encoding="utf-8") as f:
    content = f.read()
content = re.sub(r"THREADS_ACCESS_TOKEN=.*", f"THREADS_ACCESS_TOKEN={long_token}", content)
content = re.sub(r"THREADS_USER_ID=.*",      f"THREADS_USER_ID={user_id}",         content)
with open(env_path, "w", encoding="utf-8") as f:
    f.write(content)

print()
print("=" * 50)
print("✅ 完了！.env に保存しました")
print(f"   THREADS_USER_ID        : {user_id}")
print(f"   THREADS_ACCESS_TOKEN   : {long_token[:20]}...（残りは非表示）")
print()
print("次のステップ：")
print("  GitHub Secrets に THREADS_ACCESS_TOKEN と THREADS_USER_ID を登録してください")
print("=" * 50)

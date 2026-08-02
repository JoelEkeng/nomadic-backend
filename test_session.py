import urllib.request

try:
    req = urllib.request.Request("http://localhost:3000/api/auth/get-session")
    with urllib.request.urlopen(req) as response:
        print("Status:", response.status)
        print("Data:", response.read().decode())
except Exception as e:
    print("Error:", e)

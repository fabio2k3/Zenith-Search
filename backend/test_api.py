import requests

url = "http://127.0.0.1:8000/search"

payload = {
    "query": "machine learning",
    "top_k": 5
}

response = requests.post(url, json=payload)
print(response.status_code)
print(response.json())
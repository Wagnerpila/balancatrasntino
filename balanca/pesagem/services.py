import requests

def fetch_intelbras_data(device_ip, username, password):
    url = f"http://{device_ip}/cgi-bin/recordFinder.cgi?action=doSeekFind&name=AccessControlCard"
    digest_auth = requests.auth.HTTPDigestAuth(username, password)
    try:
        response = requests.get(url, auth=digest_auth, stream=True, timeout=20, verify=False)
        response.raise_for_status()

        # Verifique se os dados estão no formato esperado
        data = response.text.strip()
        if not data:
            print("No data received from the API.")
            return None

        return data
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data: {e}")
        return None
None


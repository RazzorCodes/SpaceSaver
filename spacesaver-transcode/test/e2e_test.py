import time
import requests

API_URL = "http://localhost:8000"

def wait_for_api():
    print("Waiting for API...")
    for _ in range(30):
        try:
            res = requests.get(f"{API_URL}/version")
            if res.status_code == 200:
                print("API is up!")
                # Give it a couple of seconds to finish scanner
                time.sleep(2)
                return True
        except requests.ConnectionError:
            pass
        time.sleep(1)
    return False

def check_list():
    res = requests.get(f"{API_URL}/list")
    assert res.status_code == 200
    data = res.json()
    print("List response:", data)
    assert len(data) > 0, "No files found in list!"
    file = data[0]
    assert file["status"] == "pending", f"Expected pending, got {file['status']}"
    assert file["codec"] != "Unknown", "Classifier failed to parse codec"
    return file["uuid"]

def request_transcode():
    res = requests.post(f"{API_URL}/request/enqueue/best")
    assert res.status_code == 202, f"Failed enqueue best. status={res.status_code} body={res.text}"
    print("Enqueue response:", res.json())
    return res.json()["uuid"]

def wait_for_transcoding(uuid):
    print(f"Waiting for transcode of {uuid}...")
    for _ in range(60):
        try:
            res = requests.get(f"{API_URL}/list")
            assert res.status_code == 200
            data = res.json()
            target_file = next((f for f in data if f["uuid"] == uuid), None)
            if target_file is None:
                continue
            status = target_file.get("status", "unknown")
            print(f"Status: {status} progress={target_file.get('progress')}%")
            if status in ["done", "optimum"]:
                print(f"Finished with status {status}!")
                return True
        except requests.ConnectionError:
            print("Connection error while waiting...")
        time.sleep(2)
    print("Timed out waiting for transcode.")
    return False

if __name__ == "__main__":
    if not wait_for_api():
        print("API never came up.")
        exit(1)
    uuid = check_list()
    enqueued_uuid = request_transcode()
    assert uuid == enqueued_uuid, "Enqueued different file somehow"
    if wait_for_transcoding(uuid):
        print("E2E Test Passed successfully.")
        exit(0)
    else:
        exit(1)

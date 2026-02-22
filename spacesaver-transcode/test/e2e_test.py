import os
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
    assert file["status"] == "pending" or file["status"] == "done", f"Expected pending, got {file['status']}"
    assert file["codec"] != "Unknown", "Classifier failed to parse codec"
    return file["uuid"]

def request_transcode():
    res = requests.post(f"{API_URL}/request/enqueue/best")
    assert res.status_code == 202, f"Failed enqueue best. status={res.status_code} body={res.text}"
    print("Enqueue response:", res.json())
    return res.json()["uuid"]

def wait_for_transcoding(uuid):
    print(f"Waiting for transcode of {uuid}...")
    for _ in range(120):
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
            return status
        except requests.ConnectionError:
            print("Connection error while waiting...")
        time.sleep(2)
    print("Timed out waiting for transcode.")
    return None

def check_output_exists():
    """Verify that a transcoded output file was written to ./dest/."""
    dest_dir = os.path.join(os.path.dirname(__file__), "dest")
    if not os.path.isdir(dest_dir):
        print(f"WARN: dest dir does not exist: {dest_dir}")
        return False

    mkv_files = [f for f in os.listdir(dest_dir) if f.endswith(".mkv")]
    # Also check subdirectories
    for root, _dirs, files in os.walk(dest_dir):
        for f in files:
            if f.endswith(".mkv"):
                full = os.path.join(root, f)
                size = os.path.getsize(full)
                print(f"Found output: {full} ({size} bytes)")
                return True

    print("No .mkv output files found in dest/")
    return False

def check_source_consumed():
    """Verify the source file was consumed (deleted) by the transcoder."""
    source_dir = os.path.join(os.path.dirname(__file__), "source")
    if not os.path.exists(source_dir):
        print("Source dir does not exist (already cleaned up) — OK")
        return True

    # Resolve symlink
    real_source = os.path.realpath(source_dir)
    mkv_files = [f for f in os.listdir(real_source) if f.endswith(".mkv")]
    if len(mkv_files) == 0:
        print("Source file was consumed (deleted) by the transcoder — OK")
        return True
    else:
        print(f"Source file(s) still present: {mkv_files}")
        # Fatal error — source is mounted :rw so delete should succeed
        return False

if __name__ == "__main__":
    if not wait_for_api():
        print("API never came up.")
        exit(1)
    uuid = check_list()
    enqueued_uuid = request_transcode()
    assert uuid == enqueued_uuid, "Enqueued different file somehow"
    final_status = wait_for_transcoding(uuid)
    if final_status is None:
        print("E2E Test Failed: transcode timed out.")
        exit(1)

    if final_status == "done":
        # Verify output was written
        assert check_output_exists(), "Transcode reported done but no output file found!"
    elif final_status == "optimum":
        print("File was already optimal, skipped transcode (no output expected).")

    assert check_source_consumed()

    print("E2E Test Passed successfully.")
    exit(0)

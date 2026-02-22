#!/bin/bash
set -e

# Change to the directory of this script
cd "$(dirname "$0")"

ACTION=$1

if [ -z "$ACTION" ]; then
    echo "Usage: $0 [--up | --down | --test]"
    exit 1
fi

function generate_test_data() {
    TEST_DATA_DIR="../../test-data/spacesaver-transcode/source"
    mkdir -p "$TEST_DATA_DIR"
    
    if ! ls "$TEST_DATA_DIR"/*.mkv 1> /dev/null 2>&1; then
        echo "No test mkv found in test-data. Generating a dummy 5-second video..."
        ffmpeg -f lavfi -i testsrc=duration=5:size=640x360:rate=24 -c:v mpeg4 -q:v 5 "$TEST_DATA_DIR/test_video_h264.mkv" -y > /dev/null 2>&1
    fi
}

function do_up() {
    echo "=== Bringing up container ==="
    # Clean up first to ensure idempotent state
    podman compose down -v || true
    rm -rf source dest workdir
    mkdir -p source dest workdir
    
    generate_test_data
    
    echo "Copying test mkvs from test-data to local mount..."
    cp "$TEST_DATA_DIR"/*.mkv source/
    
    echo "Starting container..."
    podman compose up -d --build
}

function do_down() {
    echo "=== Tearing down container ==="
    podman compose down -v -t 1 || true
    rm -rf source dest workdir
}

function do_test() {
    echo "=== Running E2E Test ==="
    
    WAS_UP=1
    # Check if container is running
    if podman ps --format '{{.Names}}' | grep -q "spacesaver-e2e_"; then
        echo "Container is already up."
    else
        echo "Container is not up. Starting it temporarily for the test..."
        WAS_UP=0
        do_up
    fi
    
    echo "Running e2e_test.py..."
    if [ -f ../app/.venv/bin/python ]; then
        PYTHON_BIN="../app/.venv/bin/python"
    else
        PYTHON_BIN="python3"
    fi
    
    set +e
    $PYTHON_BIN -m pip install requests
    $PYTHON_BIN e2e_test.py
    TEST_EXIT_CODE=$?
    set -e
    
    if [ $WAS_UP -eq 0 ]; then
        if [ $TEST_EXIT_CODE -eq 0 ]; then
            echo "Tearing down container since it was started by the test..."
            do_down
        else
            echo "=== Test failed! Leaving container and files for inspection. ==="
        fi
    fi
    
    if [ $TEST_EXIT_CODE -eq 0 ]; then
        echo "=== Test suite passed successfully! ==="
    fi
    exit $TEST_EXIT_CODE
}

case "$ACTION" in
    --up)
        do_up
        ;;
    --down)
        do_down
        ;;
    --test)
        do_test
        ;;
    *)
        echo "Invalid action: $ACTION"
        echo "Usage: $0 [--up | --down | --test]"
        exit 1
        ;;
esac

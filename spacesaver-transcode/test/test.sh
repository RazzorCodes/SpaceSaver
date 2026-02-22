#!/bin/bash
set -e

# Change to the directory of this script
cd "$(dirname "$0")"

ACTION=$1
SUB_ACTION=$2

if [ -z "$ACTION" ]; then
    echo "Usage: $0 [--up | --down | --test [--all | -w | -e2e]]"
    exit 1
fi

TEST_DATA_DIR="../../test-data/spacesaver-transcode/source"
TEST_VIDEO_NAME="test_video_h264.mkv"

function generate_test_data() {
    mkdir -p "$TEST_DATA_DIR"

    if [ ! -f "$TEST_DATA_DIR/$TEST_VIDEO_NAME" ]; then
        echo "No test mkv found in test-data. Generating a dummy 5-second h264 video..."
        ffmpeg -f lavfi -i testsrc=duration=5:size=640x360:rate=24 \
            -c:v libopenh264 \
            "$TEST_DATA_DIR/$TEST_VIDEO_NAME" -y
    fi
}

function do_up() {
    echo "=== Bringing up container ==="
    # Clean up first to ensure idempotent state
    podman compose down -v || true
    rm -rf source dest workdir
    mkdir -p dest workdir

    generate_test_data

    # Create an ephemeral copy so the original test-data is never touched
    E2E_SOURCE=$(mktemp -d --tmpdir spacesaver-e2e-source.XXXXXX)
    echo "Ephemeral source dir: $E2E_SOURCE"
    cp "$TEST_DATA_DIR/$TEST_VIDEO_NAME" "$E2E_SOURCE/"

    # Symlink so ompose finds ./source
    ln -sfn "$E2E_SOURCE" source

    echo "Starting container..."
    podman compose up -d --build
}

function do_down() {
    echo "=== Tearing down container ==="
    podman compose down -v -t 1 || true
    # Clean up symlink and ephemeral source
    if [ -L source ]; then
        REAL_SOURCE=$(readlink -f source)
        rm -f source
        rm -rf "$REAL_SOURCE"
    else
        rm -rf source
    fi
    rm -rf dest workdir
}

function run_whitebox() {
    echo "=== Running Whitebox (Unit) Tests ==="

    if [ -f ../app/.venv/bin/python ]; then
        PYTHON_BIN="../app/.venv/bin/python"
    else
        PYTHON_BIN="python3"
    fi

    # Run pytest on the app/tests directory
    PYTHONPATH="../app/src:../app/tests" $PYTHON_BIN -m pytest ../app/tests/ -v
}

function dump_logs() {
    local LOG_DIR="$TEST_DATA_DIR/../logs"
    mkdir -p "$LOG_DIR"
    local TIMESTAMP
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    echo "Dumping container logs to $LOG_DIR/e2e_${TIMESTAMP}.log ..."
    podman logs spacesaver-e2e_spacesaver_1 > "$LOG_DIR/e2e_${TIMESTAMP}.log" 2>&1 || true
}

function run_e2e() {
    echo "=== Running E2E Tests ==="

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
    $PYTHON_BIN -m pip install requests > /dev/null 2>&1
    $PYTHON_BIN e2e_test.py
    TEST_EXIT_CODE=$?
    set -e

    # Always dump container logs
    dump_logs

    if [ $WAS_UP -eq 0 ]; then
        if [ $TEST_EXIT_CODE -eq 0 ]; then
            echo "Tearing down container since it was started by the test..."
            do_down
        else
            echo "=== Test failed! Leaving container and files for inspection. ==="
        fi
    fi

    return $TEST_EXIT_CODE
}

function do_test() {
    local mode="${1:---all}"

    case "$mode" in
        all|w)
            # Run whitebox first, then E2E (if --all)
            run_whitebox
            WB_EXIT=$?
            if [ $WB_EXIT -ne 0 ]; then
                echo "=== Whitebox tests failed! Skipping  ==="
                exit $WB_EXIT
            fi
                echo "=== Whitebox tests passed successfully! ==="
            ;;
        all|e2e)
            run_e2e
            E2E_EXIT=$?
            if [ $E2E_EXIT -ne 0 ]; then
                echo "=== E2E tests failed! ==="
                exit $E2E_EXIT
            fi
            echo "=== E2E tests passed successfully! ==="
            ;;
        *)
            echo "Invalid test mode: $mode"
            echo "Usage: $0 --test [all | w | e2e]"
            exit 1
            ;;
    esac
}

case "$ACTION" in
    --up)
        do_up
        ;;
    --down)
        do_down
        ;;
    --test)
        do_test "$SUB_ACTION"
        ;;
    *)
        echo "Invalid action: $ACTION"
        echo "Usage: $0 [--up | --down | --test [--all | -w | -e2e]]"
        exit 1
        ;;
esac

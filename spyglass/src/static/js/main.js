document.addEventListener('DOMContentLoaded', () => {
    // State
    let libraryItems = [];
    let queueTasks = [];
    let queueRefreshInterval = null;
    let libraryRefreshInterval = null;

    // Elements
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabPanes = document.querySelectorAll('.tab-pane');
    const btnScanLarge = document.getElementById('btn-scan-large');
    const btnRefreshLib = document.getElementById('btn-refresh-lib');
    const btnScanLib = document.getElementById('btn-scan-lib');
    const btnRefreshQueue = document.getElementById('btn-refresh-queue');
    const btnTranscodeSelected = document.getElementById('btn-transcode-selected');
    const checkAll = document.getElementById('check-all');
    const toggleAutoRefresh = document.getElementById('toggle-auto-refresh');
    const toggleAutoRefreshLib = document.getElementById('toggle-auto-refresh-lib');
    const queueSpinner = document.getElementById('queue-spinner');
    const appVersionSpan = document.getElementById('app-version');
    const qualityPresetSelect = document.getElementById('quality-preset');
    const qualityModal = document.getElementById('quality-modal');
    const btnSaveQuality = document.getElementById('btn-save-quality');
    const customQualityForm = document.getElementById('custom-quality-form');
    const modalCloseEls = document.querySelectorAll('.modal-close, .modal-close-btn');

    // Toast Container
    const toastContainer = document.getElementById('toast-container');

    // Init
    initTabs();
    setupEventListeners();
    fetchVersion();
    fetchLibrary();
    fetchQueue();
    fetchQuality();
    startQueuePolling();
    startLibraryPolling();

    // --- Tabs Logic ---
    function initTabs() {
        tabBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const targetId = btn.getAttribute('data-tab');

                // Update buttons
                tabBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');

                // Update panes
                tabPanes.forEach(pane => {
                    if (pane.id === targetId) {
                        pane.classList.add('active');
                    } else {
                        pane.classList.remove('active');
                    }
                });
            });
        });
    }

    // --- Event Listeners ---
    function setupEventListeners() {
        btnScanLib.addEventListener('click', triggerScan);
        btnRefreshLib.addEventListener('click', () => {
            fetchLibrary();
            showToast('Refreshing library...', 'info');
        });
        btnScanLarge.addEventListener('click', triggerScan);
        btnRefreshQueue.addEventListener('click', () => {
            // In queue tab, simply fetch queue
            fetchQueue();
        });

        toggleAutoRefresh.addEventListener('change', (e) => {
            if (e.target.checked) {
                startQueuePolling();
                queueSpinner.style.display = 'inline-block';
            } else {
                if (queueRefreshInterval) clearInterval(queueRefreshInterval);
                queueSpinner.style.display = 'none';
            }
        });

        toggleAutoRefreshLib.addEventListener('change', (e) => {
            if (e.target.checked) {
                startLibraryPolling();
            } else {
                if (libraryRefreshInterval) clearInterval(libraryRefreshInterval);
            }
        });

        checkAll.addEventListener('change', (e) => {
            const checkboxes = document.querySelectorAll('.row-checkbox');
            checkboxes.forEach(cb => {
                cb.checked = e.target.checked;
                updateRowSelection(cb);
            });
            updateTranscodeButton();
        });

        btnTranscodeSelected.addEventListener('click', async () => {
            const checked = document.querySelectorAll('.row-checkbox:checked');
            if (checked.length === 0) return;

            btnTranscodeSelected.disabled = true;
            btnTranscodeSelected.innerHTML = "<i class='bx bx-loader-alt bx-spin'></i> Queuing...";

            let successCount = 0;
            for (let cb of checked) {
                const hash = cb.value;
                try {
                    const res = await fetch(`/api/process/${hash}`, { method: 'PUT' });
                    if (res.ok) {
                        successCount++;
                    } else {
                        const data = await res.json();
                        showToast(`Failed to queue ${hash}: ${data.message || 'Error'}`, 'error');
                    }
                } catch (e) {
                    showToast(`Network error queuing ${hash}`, 'error');
                }
            }

            if (successCount > 0) {
                showToast(`Successfully queued ${successCount} items`, 'success');
                fetchLibrary(); // refresh status
                fetchQueue();   // refresh queue
                // switch to queue tab
                document.querySelector('[data-tab="queue"]').click();
            }

            checkAll.checked = false;
            updateTranscodeButton();
        });

        qualityPresetSelect.addEventListener('change', (e) => {
            if (e.target.value === 'custom') {
                showQualityModal();
            } else {
                updateQuality(e.target.value);
            }
        });

        modalCloseEls.forEach(el => {
            el.addEventListener('click', hideQualityModal);
        });

        btnSaveQuality.addEventListener('click', () => {
            const formData = new FormData(customQualityForm);
            const custom = {
                crf: parseInt(formData.get('crf')),
                preset: formData.get('preset'),
                audio_bitrate: formData.get('audio_bitrate'),
                resolution_cap: formData.get('resolution_cap') ? parseInt(formData.get('resolution_cap')) : null
            };
            updateQuality(null, custom);
            hideQualityModal();
        });
    }

    function updateRowSelection(checkbox) {
        const tr = checkbox.closest('tr');
        if (checkbox.checked) {
            tr.classList.add('selected');
        } else {
            tr.classList.remove('selected');
        }
    }

    function updateTranscodeButton() {
        const checked = document.querySelectorAll('.row-checkbox:checked').length;
        btnTranscodeSelected.disabled = checked === 0;
        btnTranscodeSelected.innerHTML = `<i class='bx bx-play-circle'></i> Transcode Selected (${checked})`;

        // update select all state
        const total = document.querySelectorAll('.row-checkbox').length;
        if (total > 0) {
            checkAll.checked = (checked === total);
            checkAll.indeterminate = (checked > 0 && checked < total);
        }
    }

    // --- API Calls ---
    async function fetchVersion() {
        try {
            const res = await fetch('/api/version');
            if (res.ok) {
                const data = await res.json();
                appVersionSpan.textContent = `v${data.version}`;
            }
        } catch (e) {
            console.error('Failed to fetch version', e);
        }
    }

    async function fetchQuality() {
        try {
            const res = await fetch('/api/quality');
            if (res.ok) {
                const data = await res.json();
                if (data.active_preset) {
                    qualityPresetSelect.value = data.active_preset;
                } else {
                    qualityPresetSelect.value = 'custom';
                }
                // Sync modal fields
                if (data.settings) {
                    populateModalFields(data.settings);
                }
            }
        } catch (e) {
            console.error('Failed to fetch quality', e);
        }
    }

    async function updateQuality(preset, custom = null) {
        try {
            const body = preset ? { preset } : { custom };
            const res = await fetch('/api/quality', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            if (res.ok) {
                showToast('Quality updated', 'success');
                // verify change
                fetchQuality();
            } else {
                showToast('Failed to update quality', 'error');
            }
        } catch (e) {
            showToast('Network error updating quality', 'error');
        }
    }

    function showQualityModal() {
        qualityModal.classList.add('active');
    }

    function hideQualityModal() {
        qualityModal.classList.remove('active');
        // If they close without saving and were on custom, stay on custom.
        // If they click cancel, keep current state which is refreshed by fetchQuality.
        fetchQuality();
    }

    function populateModalFields(settings) {
        document.getElementById('q-crf').value = settings.crf;
        document.getElementById('q-preset').value = settings.preset;
        document.getElementById('q-audio').value = settings.audio_bitrate;
        document.getElementById('q-res').value = settings.resolution_cap || '';
    }

    async function fetchLibrary() {
        try {
            btnRefreshLib.querySelector('i').classList.add('bx-spin');
            const res = await fetch('/api/list');
            if (res.ok) {
                libraryItems = await res.json();
                renderLibrary();
            } else {
                showToast('Failed to load library', 'error');
            }
        } catch (e) {
            showToast('Network error loading library', 'error');
        } finally {
            btnRefreshLib.querySelector('i').classList.remove('bx-spin');
        }
    }

    async function fetchQueue() {
        try {
            const res = await fetch('/api/status');
            if (res.ok) {
                const data = await res.json();
                queueTasks = Object.keys(data).map(uuid => {
                    return { uuid: uuid, ...data[uuid] };
                });
                renderQueue();
            }
        } catch (e) {
            console.error('Failed to fetch queue status', e);
        }
    }

    async function triggerScan() {
        try {
            btnRefreshLib.querySelector('i').classList.add('bx-spin');
            showToast('Initiating scan...', 'info');
            const res = await fetch('/api/scan', { method: 'PUT' });
            if (res.ok) {
                showToast('Scan queued successfully!', 'success');
                fetchQueue();
                // do not switch tabs as requested
                // refresh the library list after a delay so scan can populate it
                setTimeout(fetchLibrary, 1500);
            } else {
                const data = await res.json();
                showToast(`Scan failed: ${data.message || 'Error'}`, 'error');
            }
        } catch (e) {
            showToast('Network error triggering scan', 'error');
        } finally {
            btnRefreshLib.querySelector('i').classList.remove('bx-spin');
        }
    }

    async function cancelTask(uuid) {
        try {
            const res = await fetch(`/api/cancel/${uuid}`, { method: 'DELETE' });
            if (res.ok) {
                showToast('Task cancelled', 'info');
                fetchQueue();
            } else {
                showToast('Failed to cancel task', 'error');
            }
        } catch (e) {
            showToast('Network error cancelling task', 'error');
        }
    }

    // --- Rendering ---
    function renderLibrary() {
        const table = document.getElementById('library-table');
        const emptyState = document.getElementById('empty-state');
        const tbody = document.getElementById('library-body');

        tbody.innerHTML = '';

        if (!libraryItems || libraryItems.length === 0) {
            table.classList.add('hidden');
            emptyState.classList.remove('hidden');
        } else {
            table.classList.remove('hidden');
            emptyState.classList.add('hidden');

            libraryItems.forEach(item => {
                const tr = document.createElement('tr');

                // Only allow selection if status is PENDING or ERROR
                const status = (item.status || '').toLowerCase();
                const canTranscode = status === 'pending' || status === 'error';

                let checkboxHtml = '';
                if (canTranscode && item.hash) {
                    checkboxHtml = `<input type="checkbox" class="row-checkbox" value="${item.hash}">`;
                }

                const sizeMb = item.size ? (item.size / (1024 * 1024)).toFixed(1) + ' MB' : '-';
                const statusUpper = status.toUpperCase();
                const statusClass = status.toLowerCase().replace(/_/g, '-');
                const displayName = item.name || (item.path ? item.path.split('/').pop() : 'Unknown');

                tr.innerHTML = `
                    <td class="col-check">${checkboxHtml}</td>
                    <td class="col-file"></td>
                    <td class="col-status"><span class="status-badge ${statusClass}">${statusUpper}</span></td>
                    <td class="col-info"></td>
                `;

                tr.querySelector('.col-file').textContent = displayName;
                tr.querySelector('.col-file').title = item.path || '';
                tr.querySelector('.col-info').textContent = `${sizeMb} | ${item.codec || '???'}`;

                if (canTranscode) {
                    const cb = tr.querySelector('.row-checkbox');
                    tr.addEventListener('click', (e) => {
                        if (e.target.tagName !== 'INPUT') {
                            cb.checked = !cb.checked;
                        }
                        updateRowSelection(cb);
                        updateTranscodeButton();
                    });
                }

                tbody.appendChild(tr);
            });
        }
        updateTranscodeButton();
    }

    function renderQueue() {
        const queueList = document.getElementById('queue-list');
        const emptyState = document.getElementById('queue-empty');
        const badge = document.getElementById('queue-badge');

        badge.textContent = queueTasks.length;
        queueList.innerHTML = '';

        if (queueTasks.length === 0) {
            queueList.classList.add('hidden');
            emptyState.classList.remove('hidden');
        } else {
            queueList.classList.remove('hidden');
            emptyState.classList.add('hidden');

            queueTasks.forEach(task => {
                const el = document.createElement('div');
                el.className = 'queue-item';

                let progressHtml = '';
                let detailsStr = task.type === 'tran' ? 'Transcode' : (task.type === 'scan' ? 'Library Scan' : task.type);
                const displayName = task.name || (task.uuid ? `Task: ${task.uuid.substring(0, 8)}` : 'Unknown Task');

                if (task.type === 'tran') {
                    const prog = task.progress ? parseFloat(task.progress.percent).toFixed(1) : 0;
                    const shortUuid = task.uuid ? task.uuid.substring(0, 8) : '...';
                    const preset = (task.quality_preset || 'high').toLowerCase();

                    detailsStr = `Transcode | ${shortUuid} | ${preset} | ${prog}%`;

                    progressHtml = `
                        <div class="queue-progress">
                            <div class="queue-progress-bar" style="width: ${prog}%"></div>
                        </div>
                    `;
                } else if (task.type === 'scan') {
                    detailsStr += ` | Scanning library...`;
                    progressHtml = `
                        <div class="queue-progress">
                            <div class="queue-progress-bar" style="width: 100%; animation: pulse 2s infinite;"></div>
                        </div>
                    `;
                }

                el.innerHTML = `
                    <div class="queue-item-info">
                        <div class="queue-item-title"></div>
                        <div class="queue-item-details"></div>
                        ${progressHtml}
                    </div>
                    <div class="queue-item-actions">
                        <button class="btn btn-icon btn-danger btn-cancel" data-uuid="${task.uuid}" title="Cancel Task">
                            <i class='bx bx-x'></i>
                        </button>
                    </div>
                `;

                el.querySelector('.queue-item-title').textContent = displayName;
                el.querySelector('.queue-item-details').textContent = detailsStr;

                const btnCancel = el.querySelector('.btn-cancel');
                btnCancel.addEventListener('click', () => {
                    if (confirm('Are you sure you want to cancel this task?')) {
                        cancelTask(task.uuid);
                    }
                });

                queueList.appendChild(el);
            });
        }
    }

    // --- Polling ---
    function startQueuePolling() {
        if (queueRefreshInterval) clearInterval(queueRefreshInterval);
        queueRefreshInterval = setInterval(() => {
            fetchQueue();
        }, 3000); // 3 seconds
    }

    function startLibraryPolling() {
        if (libraryRefreshInterval) clearInterval(libraryRefreshInterval);
        libraryRefreshInterval = setInterval(() => {
            fetchLibrary();
        }, 10000); // 10 seconds
    }

    // --- Toast Notifications ---
    function showToast(message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;

        let icon = 'bx-info-circle';
        if (type === 'success') icon = 'bx-check-circle';
        if (type === 'error') icon = 'bx-error-circle';

        toast.innerHTML = `<i class='bx ${icon}'></i> <span>${message}</span>`;
        toastContainer.appendChild(toast);

        setTimeout(() => {
            toast.classList.add('fade-out');
            setTimeout(() => toast.remove(), 300);
        }, 4000);
    }
});

document.addEventListener('DOMContentLoaded', function() {
    // Connect to SocketIO server
    const socket = io('http://127.0.0.1:5000', { path: '/socket.io', transports: ['websocket', 'polling'] });

    const downloadForm = document.getElementById('downloadForm');
    const downloadButton = document.getElementById('downloadButton');
    const buttonText = document.getElementById('buttonText');
    const loadingSpinner = document.getElementById('loadingSpinner');
    const status = document.getElementById('status');
    const progressBarContainer = document.getElementById('progressBarContainer');
    const progressBar = document.getElementById('progressBar');

    // Debug SocketIO connection
    socket.on('connect', () => {
        console.log('Connected to SocketIO server');
        status.innerHTML += '<p class="success">Connected to server for real-time updates.</p>';
    });

    socket.on('connect_error', (error) => {
        console.error('SocketIO connection error:', error);
        status.innerHTML += `<p class="error">Failed to connect to server: ${error.message}</p>`;
    });

    socket.on('disconnect', () => {
        console.log('Disconnected from SocketIO server');
        status.innerHTML += '<p class="error">Disconnected from server.</p>';
    });

    // Listen for progress updates from the backend
    socket.on('progress', (data) => {
        console.log('Received progress update:', data);
        // Determine message type (success or error)
        const messageClass = data.message.includes("error") || data.message.includes("failed") || data.message.includes("giving up") ? 'error' : 'success';
        // Update status messages
        status.innerHTML += `<p class="${messageClass}">${data.message}</p>`;
        status.scrollTop = status.scrollHeight;  // Auto-scroll to bottom

        // Update progress bar if progress data is provided
        if (data.progress !== undefined) {
            progressBarContainer.style.display = 'block';
            const progress = Math.min(data.progress, 100);
            progressBar.style.width = `${progress}%`;
            progressBar.setAttribute('aria-valuenow', progress);
            progressBar.innerText = `${Math.round(progress)}%`;
        }

        // Reset UI when download completes or fails
        if (data.message.toLowerCase().includes("download completed successfully") || data.message.toLowerCase().includes("backend error")) {
            console.log('Resetting UI: Download completed or failed');
            downloadButton.disabled = false;
            buttonText.innerText = "Start Download";
            loadingSpinner.style.display = 'none';
            progressBarContainer.style.display = 'none';  // Hide progress bar on completion
        }
    });

    // Form submission
    downloadForm.addEventListener('submit', function(event) {
        event.preventDefault();

        const folderId = document.getElementById('folderId').value.trim();
        const downloadFolder = document.getElementById('downloadFolder').value.trim();

        // Basic input validation
        if (!folderId || !downloadFolder) {
            status.innerHTML += '<p class="error">Please enter both a folder ID and download folder.</p>';
            status.scrollTop = status.scrollHeight;
            return;
        }

        // Disable button, show spinner, and clear status
        downloadButton.disabled = true;
        buttonText.innerText = "Downloading...";
        loadingSpinner.style.display = 'inline-block';
        status.innerHTML = '';
        progressBarContainer.style.display = 'none';
        progressBar.style.width = '0%';
        progressBar.setAttribute('aria-valuenow', 0);
        progressBar.innerText = '0%';

        // Send request to backend
        fetch('http://127.0.0.1:5000/download', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                folder_id: folderId,
                download_folder: downloadFolder
            })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! Status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            if (data.error) {
                status.innerHTML += `<p class="error">${data.error}</p>`;
                status.scrollTop = status.scrollHeight;
                downloadButton.disabled = false;
                buttonText.innerText = "Start Download";
                loadingSpinner.style.display = 'none';
            }
        })
        .catch(error => {
            status.innerHTML += `<p class="error">Something went wrong! Error: ${error.message}</p>`;
            status.scrollTop = status.scrollHeight;
            downloadButton.disabled = false;
            buttonText.innerText = "Start Download";
            loadingSpinner.style.display = 'none';
        });
    });
});
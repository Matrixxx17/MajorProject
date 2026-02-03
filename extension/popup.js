document.addEventListener('DOMContentLoaded', () => {
    const fileInput = document.getElementById('fileInput');
    const uploadBtn = document.getElementById('uploadBtn');
    const statusDiv = document.getElementById('status');
    const resultsArea = document.getElementById('resultsArea');
    const resultsTableBody = document.getElementById('resultsTableBody');
    const resultCount = document.getElementById('resultCount');

    let selectedFile = null;
    let pollInterval = null;

    fileInput.addEventListener('change', (e) => {
        if (e.target.files && e.target.files.length > 0) {
            selectedFile = e.target.files[0];
            uploadBtn.disabled = false;
            statusDiv.style.display = 'none';
            resultsArea.style.display = 'none';
        } else {
            selectedFile = null;
            uploadBtn.disabled = true;
        }
    });

    uploadBtn.addEventListener('click', async () => {
        if (!selectedFile) return;

        setProcessing(true);
        setStatus("Uploading...", "success");
        resultsArea.style.display = 'none';
        if (pollInterval) clearInterval(pollInterval);

        const formData = new FormData();
        formData.append("file", selectedFile);

        try {
            // Step 1: Submit Job
            const response = await fetch("http://localhost:5000/analyze_zip", {
                method: "POST",
                body: formData,
            });

            if (!response.ok) {
                throw new Error(`Server returned ${response.status}`);
            }

            const data = await response.json();
            const jobId = data.job_id;

            setStatus("Processing started. Waiting for results...", "success");

            // Step 2: Poll Status
            pollInterval = setInterval(async () => {
                try {
                    const statusRes = await fetch(`http://localhost:5000/status/${jobId}`);
                    const statusData = await statusRes.json();

                    if (statusData.status === 'processing') {
                        const progress = statusData.progress || 0;
                        const currentFile = statusData.current_file || '';
                        setStatus(`Processing: ${progress}% ${currentFile ? '- ' + currentFile : ''}`, "success");

                        // Update results as they come in
                        if (statusData.results && statusData.results.length > 0) {
                            displayResults(statusData.results, false); // Don't show full area yet, maybe just log?
                        }
                    } else if (statusData.status === 'completed') {
                        clearInterval(pollInterval);
                        setStatus("Analysis complete!", "success");
                        displayResults(statusData.results || [], true, statusData.download_url);
                        setProcessing(false);
                    } else if (statusData.status === 'error') {
                        clearInterval(pollInterval);
                        setStatus(`Error: ${statusData.error}`, "error");
                        setProcessing(false);
                    }
                } catch (e) {
                    console.error("Polling error", e);
                }
            }, 1000); // Poll every 1s

        } catch (error) {
            console.error(error);
            setStatus(`Error: ${error.message}`, "error");
            setProcessing(false);
        }
    });

    function setProcessing(isProcessing) {
        if (isProcessing) {
            uploadBtn.textContent = "Processing...";
            uploadBtn.classList.add("processing");
            uploadBtn.disabled = true;
            fileInput.disabled = true;
        } else {
            uploadBtn.textContent = "Generate Tests";
            uploadBtn.classList.remove("processing");
            uploadBtn.disabled = false;
            fileInput.disabled = false;
        }
    }

    function setStatus(msg, type) {
        statusDiv.textContent = msg;
        statusDiv.className = `status ${type}`;
        statusDiv.style.display = 'block';
    }

    function displayResults(results, showArea, downloadUrl) {
        resultsTableBody.innerHTML = '';
        resultCount.textContent = results.length;

        results.forEach(r => {
            const row = document.createElement('tr');

            // File column
            const fileCell = document.createElement('td');
            fileCell.textContent = r.file;
            fileCell.className = 'file-cell';
            row.appendChild(fileCell);

            // Status column
            const statusCell = document.createElement('td');
            const statusBadge = document.createElement('span');
            statusBadge.className = `status-badge status-${r.status}`;
            statusBadge.textContent = r.status.toUpperCase();
            statusCell.appendChild(statusBadge);
            row.appendChild(statusCell);

            // Coverage column
            const coverageCell = document.createElement('td');
            if (r.metrics && r.status === 'success') {
                const coverage = r.metrics.coverage_percent || 0;
                const coverageSpan = document.createElement('span');
                coverageSpan.className = `metric-value ${getCoverageClass(coverage)}`;
                coverageSpan.textContent = `${coverage.toFixed(1)}%`;
                coverageCell.appendChild(coverageSpan);
            } else {
                coverageCell.textContent = '-';
                coverageCell.className = 'metric-na';
            }
            row.appendChild(coverageCell);

            // Mutation column
            const mutationCell = document.createElement('td');
            if (r.metrics && r.status === 'success') {
                const mutation = r.metrics.mutation_score || 0;
                const mutationSpan = document.createElement('span');
                mutationSpan.className = `metric-value ${getCoverageClass(mutation)}`;
                mutationSpan.textContent = `${mutation.toFixed(1)}%`;
                mutationCell.appendChild(mutationSpan);
            } else {
                mutationCell.textContent = '-';
                mutationCell.className = 'metric-na';
            }
            row.appendChild(mutationCell);

            // Test File column
            const testFileCell = document.createElement('td');
            if (r.status === 'success' && r.test_file) {
                testFileCell.textContent = r.test_file;
                testFileCell.className = 'test-file-cell';
            } else if (r.error) {
                testFileCell.textContent = r.error;
                testFileCell.className = 'error-cell';
            } else {
                testFileCell.textContent = '-';
            }
            row.appendChild(testFileCell);

            resultsTableBody.appendChild(row);
        });

        if (showArea) {
            resultsArea.style.display = 'block';

            // Add download button if URL provided
            if (downloadUrl) {
                const existingBtn = document.getElementById('downloadZipBtn');
                if (existingBtn) existingBtn.remove();

                const downloadBtn = document.createElement('button');
                downloadBtn.id = 'downloadZipBtn';
                downloadBtn.className = 'btn secondary-btn';
                downloadBtn.style.marginTop = '15px';
                downloadBtn.style.width = '100%';
                downloadBtn.textContent = 'Download All Tests (.zip)';
                downloadBtn.onclick = () => {
                    window.open(`http://localhost:5000${downloadUrl}`, '_blank');
                };
                resultsArea.appendChild(downloadBtn);
            }
        }
    }

    function getCoverageClass(percent) {
        if (percent >= 80) return 'coverage-high';
        if (percent >= 50) return 'coverage-medium';
        return 'coverage-low';
    }
});

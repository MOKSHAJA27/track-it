// Fast in-browser QR scanner using jsQR with added debug logs
document.addEventListener('DOMContentLoaded', function() {
    console.log("qr_scanner.js loaded!");

    const video = document.getElementById('qrVideo');
    const startBtn = document.getElementById('startCamera');
    const stopBtn = document.getElementById('stopCamera');
    const resultContainer = document.getElementById('result-container');
    const scanResult = document.getElementById('scan-result');
    const errorContainer = document.getElementById('error-container');
    const errorMessage = document.getElementById('error-message');
    let scanning = false;
    let videoStream = null;

    if (startBtn) {
        startBtn.addEventListener('click', function() {
            console.log("Start camera button clicked!");
            startQRScanner();
        });
    } else {
        console.error("Start button not found!");
    }

    if (stopBtn) {
        stopBtn.addEventListener('click', function() {
            console.log("Stop camera button clicked!");
            stopQRScanner();
        });
    } else {
        console.error("Stop button not found!");
    }

    function startQRScanner() {
        console.log("startQRScanner called");
        if (scanning) return;
        resultContainer.style.display = 'none';
        errorContainer.style.display = 'none';
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            errorMessage.textContent = 'Camera API not supported in this browser!';
            errorContainer.style.display = 'block';
            return;
        }
        navigator.mediaDevices.getUserMedia({
            video: { facingMode: "environment", width: { ideal: 1280 }, height: { ideal: 720 } }
        })
        .then(function(stream) {
            videoStream = stream;
            video.srcObject = stream;
            video.setAttribute('playsinline', true); // iOS fix
            video.play();
            scanning = true;
            startBtn.style.display = 'none';
            stopBtn.style.display = 'inline-block';
            requestAnimationFrame(tick);
        })
        .catch(function(err) {
            errorMessage.textContent = 'Error accessing camera: ' + err.message;
            errorContainer.style.display = 'block';
            console.error("Error accessing camera:", err);
        });
    }

    function stopQRScanner() {
        console.log("stopQRScanner called");
        if (videoStream) {
            videoStream.getTracks().forEach(track => track.stop());
            videoStream = null;
        }
        scanning = false;
        stopBtn.style.display = 'none';
        startBtn.style.display = 'inline-block';
    }

    function tick() {
        if (!scanning) return;
        if (video.readyState === video.HAVE_ENOUGH_DATA) {
            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('2d');
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

            const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
            const code = jsQR(imageData.data, imageData.width, imageData.height, { inversionAttempts: "dontInvert" });
            if (code) {
                console.log("QR code detected:", code.data);
                processQRCode(code.data);
                stopQRScanner();
                return;
            }
        }
        requestAnimationFrame(tick);
    }

    function processQRCode(qrData) {
        fetch('/scan_qr', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ qr_data: qrData })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                scanResult.textContent = data.message || "QR code processed!";
                resultContainer.style.display = 'block';
            } else {
                errorMessage.textContent = data.error || "Failed to process QR code.";
                errorContainer.style.display = 'block';
            }
        })
        .catch(error => {
            errorMessage.textContent = 'Error processing QR code: ' + error.message;
            errorContainer.style.display = 'block';
            console.error("Error processing QR code:", error);
        });
    }
});
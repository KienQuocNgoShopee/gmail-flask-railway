// Lấy các element
const sendBtn = document.getElementById("sendBtn");
const resultElement = document.getElementById('result');
const statusIndicator = document.getElementById('status-indicator');
const progressBar = document.getElementById('progress-bar');
const currentUserEmail = document.body.dataset.email;

// Hàm cập nhật trạng thái UI
function updateStatusUI(status, message, senderEmail = null) {
    if (status === 'running' && senderEmail && senderEmail !== currentUserEmail) {
        resultElement.innerText = `Đang có người khác gửi: ${senderEmail}`;
    } else {
        resultElement.innerText = message;
    }

    statusIndicator.className = 'status-indicator';

    if (status === 'running') {
        statusIndicator.classList.add('running');
        progressBar.classList.remove('hidden');
        sendBtn.disabled = true;
    } else if (status === 'success') {
        statusIndicator.classList.add('success');
        progressBar.classList.add('hidden');
        sendBtn.disabled = false;
    } else if (status === 'error') {
        statusIndicator.classList.add('error');
        progressBar.classList.add('hidden');
        sendBtn.disabled = false;
    } else {
        statusIndicator.classList.add('idle');
        progressBar.classList.add('hidden');
        sendBtn.disabled = false;
    }
}

// Hàm gửi email
function sendEmails() {
    updateStatusUI('running', 'Đang khởi tạo...');
    
    fetch('/run', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'started') {
                updateStatusUI('running', data.message);
                checkStatusContinuously();
            } else {
                updateStatusUI('error', data.message);
            }
        })
        .catch(error => {
            console.error('Error:', error);
            updateStatusUI('error', 'Lỗi kết nối: ' + error.message);
        });
}

// Hàm kiểm tra trạng thái liên tục
function checkStatusContinuously() {
    const interval = setInterval(() => {
        fetch('/status')
            .then(response => response.json())
            .then(data => {
                if (data.running) {
                    if (data.by && data.by !== currentUserEmail) {
                        updateStatusUI('running', data.message, data.by);
                    } else {
                        updateStatusUI('running', data.message);
                    }
                } else {
                    if (data.message.toLowerCase().includes('lỗi')) {
                        updateStatusUI('error', data.message);
                    } else if (data.message.includes('hoàn thành')) {
                        updateStatusUI('success', data.message);
                        showNotification('Email đã được gửi thành công!', 'success');
                    } else {
                        updateStatusUI('idle', data.message);
                    }
                    clearInterval(interval);
                }
            })
            .catch(error => {
                console.error('Status check error:', error);
                updateStatusUI('error', 'Lỗi kiểm tra trạng thái');
                clearInterval(interval);
            });
    }, 2000);
}

// Hàm hiển thị thông báo
function showNotification(message, type = 'info') {
    // Tạo element thông báo
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.innerHTML = `
        <i class="fas ${type === 'success' ? 'fa-check-circle' : 'fa-info-circle'}"></i>
        <span>${message}</span>
    `;
    
    // Thêm CSS cho thông báo nếu chưa có
    if (!document.querySelector('#notification-styles')) {
        const style = document.createElement('style');
        style.id = 'notification-styles';
        style.textContent = `
            .notification {
                position: fixed;
                top: 20px;
                right: 20px;
                background: white;
                padding: 15px 20px;
                border-radius: 10px;
                box-shadow: 0 5px 20px rgba(0,0,0,0.2);
                display: flex;
                align-items: center;
                gap: 10px;
                z-index: 1000;
                transform: translateX(400px);
                transition: transform 0.3s ease;
            }
            .notification-success {
                border-left: 4px solid #4CAF50;
            }
            .notification-success i {
                color: #4CAF50;
            }
            .notification.show {
                transform: translateX(0);
            }
        `;
        document.head.appendChild(style);
    }
    
    // Thêm vào body
    document.body.appendChild(notification);
    
    // Hiển thị với animation
    setTimeout(() => notification.classList.add('show'), 100);
    
    // Tự động ẩn sau 3 giây
    setTimeout(() => {
        notification.classList.remove('show');
        setTimeout(() => document.body.removeChild(notification), 300);
    }, 3000);
}

// Kiểm tra trạng thái ban đầu khi tải trang
window.addEventListener('load', function() {
    fetch('/status')
        .then(response => response.json())
        .then(data => {
            if (data.running) {
                if (data.by && data.by !== currentUserEmail) {
                    updateStatusUI('running', data.message, data.by);
                } else {
                    updateStatusUI('running', data.message);
                    checkStatusContinuously();
                }
            } else {
                if (data.message.toLowerCase().includes('lỗi')) {
                    updateStatusUI('error', data.message);
                } else if (data.message.includes('hoàn thành')) {
                    updateStatusUI('success', data.message);
                } else {
                    updateStatusUI('idle', data.message);
                }
            }
        })
        .catch(error => {
            console.error('Initial status check error:', error);
            updateStatusUI('error', 'Không thể kết nối đến server');
        });
});

// Thêm keyboard shortcut (Enter để chạy)
document.addEventListener('keydown', function(event) {
    if (event.key === 'Enter' && !sendBtn.disabled) {
        sendEmails();
    }
});
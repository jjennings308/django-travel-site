// rewards/static/rewards/js/rewards.js

/**
 * Toggle primary status of a membership
 */
function togglePrimary(membershipId) {
    fetch(`/rewards/memberships/${membershipId}/toggle-primary/`, {
        method: 'POST',
        headers: {
            'X-CSRFToken': getCookie('csrftoken'),
            'Content-Type': 'application/json',
        },
    })
    .then(response => response.json())
    .then(data => {
        if (data.ok) {
            // Reload page to show updated primary status
            window.location.reload();
        } else {
            alert('Error updating primary status: ' + (data.error || 'Unknown error'));
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('An error occurred while updating primary status.');
    });
}

/**
 * Get CSRF token from cookies
 */
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

/**
 * Initialize drag-and-drop reordering for memberships
 * Requires SortableJS library: https://github.com/SortableJS/Sortable
 */
function initializeSortable() {
    const lists = document.querySelectorAll('.sortable-memberships');
    
    lists.forEach(list => {
        new Sortable(list, {
            animation: 150,
            handle: '.drag-handle',
            ghostClass: 'sortable-ghost',
            onEnd: function(evt) {
                updateMembershipOrder(list);
            }
        });
    });
}

/**
 * Update membership display order after drag-and-drop
 */
function updateMembershipOrder(listElement) {
    const items = listElement.querySelectorAll('.membership-item');
    const order = Array.from(items).map(item => item.dataset.membershipId);
    
    fetch('/rewards/memberships/reorder/', {
        method: 'POST',
        headers: {
            'X-CSRFToken': getCookie('csrftoken'),
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ order: order })
    })
    .then(response => response.json())
    .then(data => {
        if (!data.ok) {
            alert('Error updating order: ' + (data.error || 'Unknown error'));
            window.location.reload();
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('An error occurred while updating order.');
        window.location.reload();
    });
}

/**
 * Confirm deletion with custom message
 */
function confirmDelete(programName) {
    return confirm(`Are you sure you want to delete your ${programName} membership?\n\nThis action cannot be undone.`);
}

/**
 * Auto-hide success messages after delay
 */
function autoHideMessages() {
    const alerts = document.querySelectorAll('.alert-dismissible');
    alerts.forEach(alert => {
        setTimeout(() => {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }, 5000); // Hide after 5 seconds
    });
}

/**
 * Initialize on page load
 */
document.addEventListener('DOMContentLoaded', function() {
    // Auto-hide messages
    autoHideMessages();
    
    // Initialize sortable if the library is loaded
    if (typeof Sortable !== 'undefined') {
        initializeSortable();
    }
    
    // Add confirmation to delete buttons
    const deleteButtons = document.querySelectorAll('[data-confirm-delete]');
    deleteButtons.forEach(button => {
        button.addEventListener('click', function(e) {
            const programName = this.dataset.programName || 'this';
            if (!confirmDelete(programName)) {
                e.preventDefault();
            }
        });
    });
    
    // Highlight expiring memberships
    highlightExpiringMemberships();
    
    // Add smooth scroll to anchors
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                e.preventDefault();
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });
});

/**
 * Highlight memberships expiring within 60 days
 */
function highlightExpiringMemberships() {
    const expiryElements = document.querySelectorAll('[data-expiry-date]');
    const today = new Date();
    const sixtyDaysFromNow = new Date(today.getTime() + (60 * 24 * 60 * 60 * 1000));
    
    expiryElements.forEach(element => {
        const expiryDate = new Date(element.dataset.expiryDate);
        if (expiryDate < sixtyDaysFromNow && expiryDate > today) {
            element.classList.add('text-warning', 'fw-bold');
            const icon = document.createElement('i');
            icon.className = 'bi bi-exclamation-triangle ms-1';
            element.appendChild(icon);
        }
    });
}

/**
 * Filter programs by type (for browse page)
 */
function filterPrograms(type) {
    const cards = document.querySelectorAll('[data-program-type]');
    
    cards.forEach(card => {
        if (type === 'all' || card.dataset.programType === type) {
            card.style.display = '';
        } else {
            card.style.display = 'none';
        }
    });
}

/**
 * Update points balance via AJAX (optional feature)
 */
function updatePointsBalance(membershipId, newBalance) {
    fetch(`/rewards/memberships/${membershipId}/update-balance/`, {
        method: 'POST',
        headers: {
            'X-CSRFToken': getCookie('csrftoken'),
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ points_balance: newBalance })
    })
    .then(response => response.json())
    .then(data => {
        if (data.ok) {
            // Update display
            const balanceElement = document.querySelector(`[data-balance-for="${membershipId}"]`);
            if (balanceElement) {
                balanceElement.textContent = newBalance.toLocaleString();
            }
        } else {
            alert('Error updating balance: ' + (data.error || 'Unknown error'));
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('An error occurred while updating balance.');
    });
}

/**
 * Export memberships as CSV (optional feature)
 */
function exportMembershipsCSV() {
    window.location.href = '/rewards/export/csv/';
}

/**
 * Print membership card (optional feature)
 */
function printMembershipCard(membershipId) {
    const printWindow = window.open(`/rewards/memberships/${membershipId}/print/`, '_blank');
    printWindow.onload = function() {
        printWindow.print();
    };
}
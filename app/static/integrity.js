// app/static/integrity.js — Integrity Centre UI interactions

function switchIntegrityTab(tabName) {
    document.querySelectorAll('.integrity-tab-btn').forEach(function(btn) {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });
    document.querySelectorAll('.integrity-panel').forEach(function(panel) {
        panel.classList.toggle('active', panel.id === 'panel-' + tabName);
    });
}

document.addEventListener('DOMContentLoaded', function() {
    // If a tab is active by server rendered active_tab, ensure tab buttons align
    var activePanel = document.querySelector('.integrity-panel.active');
    if (activePanel) {
        var tabId = activePanel.id.replace('panel-', '');
        document.querySelectorAll('.integrity-tab-btn').forEach(function(btn) {
            btn.classList.toggle('active', btn.dataset.tab === tabId);
        });
    }
});

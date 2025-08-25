// Listen for the spacebar and trigger a click on a hidden button to toggle pause
document.addEventListener('keydown', function(e) {
    // Modern property
    var isSpace = (e.code === 'Space');
    // Fallback
    if (!isSpace && e.keyCode !== undefined) isSpace = (e.keyCode === 32);
    if (!isSpace) return;

    // Ignore when typing in inputs/textareas or contenteditable elements
    var active = document.activeElement;
    if (!active) return;
    var tag = active.tagName && active.tagName.toUpperCase();
    var editable = active.getAttribute && active.getAttribute('contenteditable');
    if (tag === 'INPUT' || tag === 'TEXTAREA' || editable === '' || editable === 'true') return;

    e.preventDefault();
    var btn = document.getElementById('space-toggle-button');
    if (btn) {
        btn.click();
    }
});

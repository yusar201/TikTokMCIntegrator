# Floating Panel Pattern

When a UI element (status panel, notifications, live stats) appears/disappears dynamically, making it part of the normal document flow causes layout shift - content jumps up/down, disturbing the user's reading position.

**Solution:** Make it float (position: fixed) so it overlaps content instead of pushing it.

## CSS

```css
.floating-panel {
  position: fixed;
  top: 80px;           /* adjust for your header height */
  right: 20px;
  width: 320px;
  max-height: calc(100vh - 120px);
  overflow-y: auto;    /* scroll if content overflows */
  z-index: 1000;       /* above other content */
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  padding: 16px 20px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.4);  /* visual separation */
}

/* Close button in header */
.floating-panel .panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.panel-close {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 16px;
  padding: 4px 8px;
  border-radius: 4px;
}
.panel-close:hover {
  background: var(--bg-elevated);
  color: var(--text-primary);
}
```

## JavaScript

```javascript
function renderPanel(data) {
  const section = document.getElementById('floating-panel');
  if (!data || Object.keys(data).length === 0) {
    section.style.display = 'none';
    return;
  }

  section.style.display = '';
  
  // Add close button if not already there
  const header = section.querySelector('.panel-header');
  if (header && !header.querySelector('.panel-close')) {
    const closeBtn = document.createElement('button');
    closeBtn.className = 'panel-close';
    closeBtn.innerHTML = '&times;';
    closeBtn.onclick = () => section.style.display = 'none';
    header.appendChild(closeBtn);
  }
  
  // ... render content
}
```

## When to Use

- Live stats panels that appear/disappear based on data
- Notification toasts
- Status indicators
- Any element that causes layout shift when toggling visibility

## Trade-offs

| Approach | Pros | Cons |
|----------|------|------|
| `position: fixed` | No layout shift, always visible | Overlaps content, needs z-index management |
| `position: sticky` | Stays in flow but sticks on scroll | Still takes space in document flow |
| Normal flow | Simple, no overlap | Causes layout shift (the problem) |

Use `fixed` when the user explicitly said "it's okay to overlap, just don't snap/push content".

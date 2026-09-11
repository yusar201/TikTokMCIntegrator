# Local slot-text pattern for standalone OBS overlays

Session: 2026-06-15. User asked to apply the previously discussed `slot-text` feel to standalone Minecraft OBS overlays outside TikTokMCIntegrator:

- `C:\Users\yusar\Documents\Code\Live\McPY\overlay\diamondCounter.html`
- `C:\Users\yusar\Documents\Code\Live\McPY\overlay\winOverlay.html`

## When to use

Use this pattern for small single-file OBS overlays that poll a local API (`http://localhost:8080/stats`) and need animated numeric/text changes without a build step, npm, or external JS dependency.

## Design guidance

- Reuse the same visual language across related overlays, but tune feel per metric:
  - Diamond/resource counters: quick cyan/green slot roll, utilitarian.
  - Win/score counters: slower gold jackpot slot roll + existing victory pop, more celebratory.
  - Decreases/loss: roll downward + red/shake state.
- Preserve existing overlay behavior: transparent body, hidden when API fails, progress bar updates, current gain/loss classes.
- Keep it dependency-free for OBS reliability. Do not require `import`, bundlers, npm, or CDN JS for these local files.

## Implementation recipe

HTML:

```html
<span id="curr-val" class="slot-text">0</span>
<span id="goal-val" class="goal-text slot-text">/ 20</span>
```

CSS core:

```css
.slot-text { display:inline-flex; align-items:baseline; gap:1px; }
.slot-char { display:inline-block; min-width:0.62em; height:1.1em; overflow:hidden; line-height:1.1; text-align:center; }
.slot-char-inner { display:flex; flex-direction:column; transform:translateY(0); }
.slot-char.spin-up .slot-char-inner { animation:slotSpinUp .46s cubic-bezier(.34,1.56,.64,1) both; }
.slot-char.spin-down .slot-char-inner { animation:slotSpinDown .46s cubic-bezier(.34,1.56,.64,1) both; }
.slot-char:nth-child(2) .slot-char-inner { animation-delay:.035s; }
.slot-char:nth-child(3) .slot-char-inner { animation-delay:.07s; }
.slot-char:nth-child(4) .slot-char-inner { animation-delay:.105s; }
@keyframes slotSpinUp { 0%{transform:translateY(0);filter:blur(0)} 45%{filter:blur(1px)} 100%{transform:translateY(-1.1em);filter:blur(0)} }
@keyframes slotSpinDown { 0%{transform:translateY(-1.1em);filter:blur(0)} 45%{filter:blur(1px)} 100%{transform:translateY(0);filter:blur(0)} }
```

JS helper:

```js
function setSlotText(el, nextText, direction = 'up') {
  const prevText = el.dataset.value ?? el.textContent;
  nextText = String(nextText);
  el.dataset.value = nextText;
  el.innerHTML = '';
  const maxLen = Math.max(prevText.length, nextText.length);
  const prev = prevText.padStart(maxLen, ' ');
  const next = nextText.padStart(maxLen, ' ');
  for (let i = 0; i < maxLen; i++) {
    const oldChar = prev[i] === ' ' ? '&nbsp;' : prev[i];
    const newChar = next[i] === ' ' ? '&nbsp;' : next[i];
    const char = document.createElement('span');
    char.className = 'slot-char';
    if (prev[i] === next[i]) {
      char.innerHTML = newChar;
    } else {
      char.classList.add(direction === 'down' ? 'spin-down' : 'spin-up');
      char.innerHTML = direction === 'down'
        ? `<span class="slot-char-inner"><span>${newChar}</span><span>${oldChar}</span></span>`
        : `<span class="slot-char-inner"><span>${oldChar}</span><span>${newChar}</span></span>`;
    }
    el.appendChild(char);
  }
}
```

Update loop pattern:

```js
if (current !== lastValue) {
  setSlotText(numText, current, current < lastValue ? 'down' : 'up');
  // keep existing progress/gain/loss logic
  lastValue = current;
}
```

Goal text pattern:

```js
if (goalText.dataset.value !== `/ ${goal}`) {
  setSlotText(goalText, `/ ${goal}`);
}
```

## Jackpot variant

For win overlays, rename keyframes to `jackpotSpinUp/Down`, slow `spin-up` to ~0.62s, add gold color keyframes, and keep the existing `.win-increase` pop. This makes wins feel like a jackpot while retaining the same slot-text language.

## Pitfalls

- Preserve `dataset.value`; it is the source for the previous visible text after `innerHTML` gets replaced.
- Unchanged chars should render as static text, not animated spans, so stable digits do not jitter.
- `innerHTML` is acceptable here only because values are local numeric/known text (`0`, `/ 20`). For user-provided names/messages, escape or use `textContent`-built spans.
- Initial `lastValue` may be `null`/`-1`; compare carefully. `current < lastValue` should be false on first real render.

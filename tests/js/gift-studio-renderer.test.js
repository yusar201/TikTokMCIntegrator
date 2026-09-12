/**
 * Gift Card Studio — SVG renderer: escaping, URL allowlisting, layer output,
 * page composition, and parity with the grid contract.
 */
import assert from 'node:assert/strict';
import { test, describe } from 'node:test';

import * as r from '../../static/gift-studio/renderer.js';

const layer = (overrides = {}) => ({
  id: 'l1', type: 'text', visible: true, locked: false, z_index: 0,
  x: 0, y: 0, width: 100, height: 40, rotation: 0, opacity: 1, ...overrides,
});

const card = (overrides = {}) => ({
  id: 'c1', width: 320, height: 400, gift_ref: {}, action_ref: {}, layers: [], ...overrides,
});

describe('escapeXml', () => {
  test('escapes every XML metacharacter', () => {
    assert.equal(r.escapeXml('<script>&"\'</script>'),
      '&lt;script&gt;&amp;&quot;&apos;&lt;/script&gt;');
  });

  test('null and undefined become empty strings', () => {
    assert.equal(r.escapeXml(null), '');
    assert.equal(r.escapeXml(undefined), '');
  });
});

describe('sanitizeAssetUrl', () => {
  test('accepts same-origin absolute paths', () => {
    assert.equal(r.sanitizeAssetUrl('/gift-studio-assets/icon.png'), '/gift-studio-assets/icon.png');
    assert.equal(r.sanitizeAssetUrl('/gift_assets/5655.png'), '/gift_assets/5655.png');
  });

  test('accepts https CDN urls', () => {
    const url = 'https://p16-webcast.tiktokcdn.com/img/x.png~tplv-obj.webp';
    assert.equal(r.sanitizeAssetUrl(url), url);
  });

  test('accepts data:image base64', () => {
    const url = 'data:image/png;base64,iVBORw0KGgo=';
    assert.equal(r.sanitizeAssetUrl(url), url);
  });

  test('rejects script-bearing and exfiltrating schemes', () => {
    for (const evil of [
      'javascript:alert(1)',
      'JaVaScRiPt:alert(1)',
      'vbscript:msgbox(1)',
      'data:text/html,<script>alert(1)</script>',
      'data:image/svg+xml,<svg onload=alert(1)>',
      '//evil.example.com/x.png',
      'http://insecure.example.com/x.png',
      'file:///etc/passwd',
      '',
      '   ',
    ]) {
      assert.equal(r.sanitizeAssetUrl(evil), '', `should reject: ${evil}`);
    }
  });

  test('rejects non-strings', () => {
    assert.equal(r.sanitizeAssetUrl(null), '');
    assert.equal(r.sanitizeAssetUrl(42), '');
    assert.equal(r.sanitizeAssetUrl({}), '');
  });
});

describe('renderLayer visibility', () => {
  test('a hidden layer renders nothing', () => {
    assert.equal(r.renderLayer(layer({ type: 'text', text: 'hi', visible: false })), '');
  });

  test('an unknown layer type renders nothing rather than raw markup', () => {
    assert.equal(r.renderLayer(layer({ type: 'hologram' })), '');
  });

  test('a null layer is safe', () => {
    assert.equal(r.renderLayer(null), '');
  });
});

describe('text layers', () => {
  test('text content is escaped, not injected', () => {
    const svg = r.renderLayer(layer({ type: 'text', text: '<script>alert(1)</script>' }));
    assert.ok(!svg.includes('<script>'));
    assert.ok(svg.includes('&lt;script&gt;'));
  });

  test('the font family is escaped', () => {
    const svg = r.renderLayer(layer({ type: 'text', text: 'x', font_family: '"><script>' }));
    assert.ok(!svg.includes('<script>'));
  });

  test('empty text renders nothing', () => {
    assert.equal(r.renderLayer(layer({ type: 'text', text: '' })), '');
  });

  test('multiline text emits one tspan per line', () => {
    const svg = r.renderLayer(layer({ type: 'text', text: 'a\nb\nc' }));
    assert.equal((svg.match(/<tspan/g) || []).length, 3);
  });

  test('alignment maps to the right text-anchor and x', () => {
    const left = r.renderLayer(layer({ type: 'text', text: 'x', align: 'left', x: 10, width: 100 }));
    const center = r.renderLayer(layer({ type: 'text', text: 'x', align: 'center', x: 10, width: 100 }));
    const right = r.renderLayer(layer({ type: 'text', text: 'x', align: 'right', x: 10, width: 100 }));
    assert.ok(left.includes('text-anchor="start"') && left.includes('x="10"'));
    assert.ok(center.includes('text-anchor="middle"') && center.includes('x="60"'));
    assert.ok(right.includes('text-anchor="end"') && right.includes('x="110"'));
  });

  test('uppercase transforms the rendered text', () => {
    const svg = r.renderLayer(layer({ type: 'text', text: 'wither', uppercase: true }));
    assert.ok(svg.includes('WITHER'));
  });

  test('responsive_text shrinks an overflowing line', () => {
    const wide = layer({ type: 'text', text: 'A'.repeat(40), width: 100, font_size: 40, responsive_text: true });
    const fixed = layer({ type: 'text', text: 'A'.repeat(40), width: 100, font_size: 40 });
    const shrunk = parseFloat(r.renderLayer(wide).match(/font-size="([\d.]+)"/)[1]);
    const unshrunk = parseFloat(r.renderLayer(fixed).match(/font-size="([\d.]+)"/)[1]);
    assert.ok(shrunk < unshrunk, `${shrunk} should be < ${unshrunk}`);
    assert.equal(unshrunk, 40);
  });

  test('responsive_text leaves short text at its authored size', () => {
    const svg = r.renderLayer(layer({ type: 'text', text: 'Hi', width: 300, font_size: 30, responsive_text: true }));
    assert.ok(svg.includes('font-size="30"'));
  });

  test('a stroke is emitted behind the fill for legibility', () => {
    const svg = r.renderLayer(layer({
      type: 'text', text: 'x', stroke_color: '#000000', stroke_width: 2,
    }));
    assert.ok(svg.includes('paint-order="stroke"'));
    assert.ok(svg.includes('stroke="#000000"'));
  });
});

describe('image layers', () => {
  test('an action icon with no usable asset renders a pixel placeholder', () => {
    const svg = r.renderLayer(layer({ type: 'action_icon', asset: '', x: 10, y: 20, width: 80, height: 80 }));
    assert.match(svg, /data-action-placeholder="true"/);
    assert.match(svg, /<rect/);
    assert.ok(!svg.includes('<image'));
  });

  test('an allowlisted asset becomes an image element', () => {
    const svg = r.renderLayer(layer({ type: 'image', asset: '/gift-studio-assets/a.png' }));
    assert.ok(svg.startsWith('<image'));
    assert.ok(svg.includes('href="/gift-studio-assets/a.png"'));
  });

  test('a rejected url renders nothing at all', () => {
    assert.equal(r.renderLayer(layer({ type: 'image', asset: 'javascript:alert(1)' })), '');
  });

  test('a missing asset renders nothing rather than a broken image', () => {
    assert.equal(r.renderLayer(layer({ type: 'image', asset: '' })), '');
  });

  test('gift_icon auto-links to the card gift icon', () => {
    const svg = r.renderCardBody(card({
      gift_ref: { icon: '/gift_assets/5655.png' },
      layers: [layer({ type: 'gift_icon', auto_link: true, asset: '' })],
    }));
    assert.ok(svg.includes('href="/gift_assets/5655.png"'));
  });

  test('a pinned gift_icon asset overrides the auto link', () => {
    const svg = r.renderCardBody(card({
      gift_ref: { icon: '/gift_assets/auto.png' },
      layers: [layer({ type: 'gift_icon', auto_link: false, asset: '/gift-studio-assets/pinned.png' })],
    }));
    assert.ok(svg.includes('pinned.png'));
    assert.ok(!svg.includes('auto.png'));
  });

  test('fit maps to preserveAspectRatio', () => {
    const contain = r.renderLayer(layer({ type: 'image', asset: '/a.png', fit: 'contain' }));
    const cover = r.renderLayer(layer({ type: 'image', asset: '/a.png', fit: 'cover' }));
    const fill = r.renderLayer(layer({ type: 'image', asset: '/a.png', fit: 'fill' }));
    assert.ok(contain.includes('meet'));
    assert.ok(cover.includes('slice'));
    assert.ok(fill.includes('preserveAspectRatio="none"'));
  });

  test('pixelated rendering is the default for Minecraft-style art', () => {
    assert.ok(r.renderLayer(layer({ type: 'image', asset: '/a.png' })).includes('image-rendering="pixelated"'));
    assert.ok(!r.renderLayer(layer({ type: 'image', asset: '/a.png', pixelated: false })).includes('image-rendering'));
  });
});

describe('shape layers', () => {
  test('a plain panel is a rect', () => {
    const svg = r.renderLayer(layer({ type: 'shape', kind: 'panel', fill: '#16161a' }));
    assert.ok(svg.startsWith('<rect'));
    assert.ok(svg.includes('fill="#16161a"'));
  });

  test('pixel_border uses stepped corners, not a smooth radius', () => {
    const svg = r.renderLayer(layer({ type: 'shape', kind: 'pixel_border', pixel_steps: 3 }));
    assert.ok(svg.startsWith('<polygon'));
    assert.ok(!svg.includes('rx='));
  });

  test('a divider is a horizontal line at mid-height', () => {
    const svg = r.renderLayer(layer({ type: 'shape', kind: 'divider', y: 100, height: 40 }));
    assert.ok(svg.startsWith('<line'));
    assert.ok(svg.includes('y1="120"'));
  });

  test('an invalid colour degrades to none instead of leaking into markup', () => {
    const svg = r.renderLayer(layer({ type: 'shape', fill: 'url(#evil)' }));
    assert.ok(svg.includes('fill="none"'));
    assert.ok(!svg.includes('url(#evil)'));
  });
});

describe('layer ordering and transforms', () => {
  test('layers render in z_index order regardless of array order', () => {
    const svg = r.renderCardBody(card({
      layers: [
        layer({ id: 'top', type: 'text', text: 'TOP', z_index: 2 }),
        layer({ id: 'bottom', type: 'shape', z_index: 0 }),
        layer({ id: 'mid', type: 'text', text: 'MID', z_index: 1 }),
      ],
    }));
    assert.ok(svg.indexOf('<rect') < svg.indexOf('MID'));
    assert.ok(svg.indexOf('MID') < svg.indexOf('TOP'));
  });

  test('rotation is emitted around the layer centre', () => {
    const svg = r.renderLayer(layer({ type: 'shape', x: 0, y: 0, width: 100, height: 40, rotation: 15 }));
    assert.ok(svg.includes('transform="rotate(15 50 20)"'));
  });

  test('full opacity emits no attribute; partial does', () => {
    assert.ok(!r.renderLayer(layer({ type: 'shape', opacity: 1 })).includes('opacity='));
    assert.ok(r.renderLayer(layer({ type: 'shape', opacity: 0.5 })).includes('opacity="0.5"'));
  });
});

describe('renderCardSvg', () => {
  test('a card svg uses the card logical size as its viewBox', () => {
    const svg = r.renderCardSvg(card({ width: 300, height: 420 }));
    assert.ok(svg.includes('viewBox="0 0 300 420"'));
    assert.ok(svg.includes('width="300"'));
  });

  test('rendering is deterministic for identical input', () => {
    const c = card({ layers: [layer({ type: 'text', text: 'Vex' })] });
    assert.equal(r.renderCardSvg(c), r.renderCardSvg(c));
  });
});

describe('renderPageSvg', () => {
  const page = (count, gridOverrides = {}) => ({
    grid: {
      rows: 1, columns: 5, gap_x: 20, gap_y: 20, padding: 24,
      fill_order: 'row', fit: 'contain', ...gridOverrides,
    },
    cards: Array.from({ length: count }, (_, i) => card({
      id: `c${i}`,
      layers: [layer({ type: 'text', text: `Card ${i}` })],
    })),
  });

  const canvas = { width: 1920, height: 1080, background: 'transparent' };

  test('a 1x5 page emits one group per visible card', () => {
    const svg = r.renderPageSvg(page(5), canvas);
    assert.equal((svg.match(/<g transform="translate/g) || []).length, 5);
    for (let i = 0; i < 5; i += 1) assert.ok(svg.includes(`Card ${i}`));
  });

  test('overflow cards are not rendered', () => {
    const svg = r.renderPageSvg(page(7), canvas);
    assert.equal((svg.match(/<g transform="translate/g) || []).length, 5);
    assert.ok(!svg.includes('Card 5'));
    assert.ok(!svg.includes('Card 6'));
  });

  test('a transparent canvas emits no background rect', () => {
    const svg = r.renderPageSvg(page(1), { width: 800, height: 600, background: 'transparent' });
    assert.ok(!svg.includes('<rect x="0" y="0" width="800"'));
  });

  test('a solid canvas emits a background rect', () => {
    const svg = r.renderPageSvg(page(1), { width: 800, height: 600, background: '#101014' });
    assert.ok(svg.includes('fill="#101014"'));
  });

  test('the page svg dimensions follow the canvas, not the viewport', () => {
    const svg = r.renderPageSvg(page(1), { width: 1080, height: 1920 });
    assert.ok(svg.includes('width="1080"'));
    assert.ok(svg.includes('height="1920"'));
    assert.ok(svg.includes('viewBox="0 0 1080 1920"'));
  });

  test('cover-fit overflow is clipped to its own cell', () => {
    const svg = r.renderPageSvg(page(2, { fit: 'cover', rows: 1, columns: 2 }), canvas);
    assert.ok(svg.includes('<clipPath'));
    assert.ok(svg.includes('clip-path="url(#clip-'));
  });

  test('contain-fit needs no clip paths', () => {
    const svg = r.renderPageSvg(page(5), canvas);
    assert.ok(!svg.includes('<clipPath'));
  });

  test('the transform matches the grid contract exactly', () => {
    const svg = r.renderPageSvg(page(5), canvas);
    // 1x5 of 1920 wide: cell 358.4, scale 358.4/320 = 1.12, first offset x = 24
    assert.ok(svg.includes('translate(24 316) scale(1.12 1.12)'), svg.slice(0, 400));
  });

  test('an empty page still produces a valid svg', () => {
    const svg = r.renderPageSvg({ grid: { rows: 1, columns: 1 }, cards: [] }, canvas);
    assert.ok(svg.startsWith('<svg'));
    assert.ok(svg.endsWith('</svg>'));
  });
});

describe('renderGridGuides', () => {
  test('guides emit one dashed rect per cell', () => {
    const guides = r.renderGridGuides(
      { grid: { rows: 2, columns: 3, gap_x: 10, gap_y: 10, padding: 20 } },
      { width: 900, height: 600 },
    );
    assert.equal((guides.match(/<rect/g) || []).length, 6);
    assert.ok(guides.includes('stroke-dasharray'));
  });

  test('guides are never part of a rendered page', () => {
    const page = { grid: { rows: 1, columns: 2 }, cards: [card({ layers: [layer({ type: 'shape' })] })] };
    const svg = r.renderPageSvg(page, { width: 800, height: 400 });
    assert.ok(!svg.includes('stroke-dasharray'));
  });
});

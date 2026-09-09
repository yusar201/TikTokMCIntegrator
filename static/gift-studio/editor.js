import { renderCardSvg, renderPageSvg } from './renderer.js';

export const currentPage = state => state.project?.pages?.[state.pageIndex] || null;
export const currentCard = state => state.project?.card_library?.[state.cardIndex] || null;
export const currentLayer = state => currentCard(state)?.layers?.[state.layerIndex] || null;
export const assetContext = () => ({ assetBase: '' });

export function renderEditor(state, onChange){
  const card=currentCard(state);
  const cards=document.getElementById('gcs-card-list');
  cards.innerHTML=(state.project?.card_library||[]).map((c,i)=>`<button data-card="${i}" class="${i===state.cardIndex?'active':''}">${escapeHtml(c.name||c.gift_ref?.name||`Card ${i+1}`)}<small>${pageUsage(state,c.id)}</small></button>`).join('')||'<span>No cards imported. Choose gifts in Catalog first.</span>';
  cards.querySelectorAll('[data-card]').forEach(b=>b.onclick=()=>{state.cardIndex=+b.dataset.card;state.layerIndex=0;onChange(false);document.dispatchEvent(new CustomEvent('gcs:card-selected'));});
  const preview=document.getElementById('gcs-card-preview'); preview.innerHTML=card?renderCardSvg(card,assetContext()):'<span>Select a card.</span>';
  const layers=document.getElementById('gcs-layer-list');
  layers.innerHTML=(card?.layers||[]).map((l,i)=>`<div class="gcs-layer-row ${i===state.layerIndex?'active':''}" data-layer="${i}" data-layer-type="${escapeHtml(l.type)}" role="button" tabindex="0"><span class="gcs-layer-name">${escapeHtml(l.name||layerLabel(l.type))}${l.type==='image'||l.type==='action_icon'||l.type==='gift_icon'?`<small>${layerLabel(l.type)}</small>`:''}</span><label class="gcs-layer-visible" title="Show or hide this layer"><input type="checkbox" data-layer-visible="${i}" ${l.visible!==false?'checked':''}><span>Visible</span></label></div>`).join('');
  layers.querySelectorAll('[data-layer]').forEach(row=>{
    row.onclick=()=>{state.layerIndex=+row.dataset.layer;onChange(false);};
    row.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();row.click();}};
  });
  layers.querySelectorAll('[data-layer-visible]').forEach(checkbox=>checkbox.onclick=event=>{
    event.stopPropagation();
    const layer=card.layers[+checkbox.dataset.layerVisible];
    layer.visible=checkbox.checked;
    onChange(true);
  });
  renderLayerControls(state,onChange);
}

function pageUsage(state,cardId){const names=(state.project?.pages||[]).filter(page=>(page.card_ids||[]).includes(String(cardId))).map(page=>page.name);return names.length?names.join(', '):'Not assigned';}

function layerLabel(type){return type==='gift_icon'?'Gift Icon':type==='action_icon'?'Action Icon':type==='image'?'Image':type==='text'?'Text':type;}

function renderLayerControls(state,onChange){
  const layer=currentLayer(state), box=document.getElementById('gcs-layer-controls');
  if(!layer){box.innerHTML='';return;}
  const text=layer.type==='text'?`<label>Text<input data-key="text" value="${escapeAttr(layer.text||'')}"></label><label>Font size<input data-key="font_size" type="number" min="1" value="${layer.font_size||24}"></label>`:'';
  const image=layer.type==='image'||layer.type==='action_icon'||layer.type==='gift_icon'?`<div class="gcs-asset-control"><span>${layer.type==='gift_icon'?'Gift icon / badge':layer.type==='action_icon'?'Action icon':'Image'}</span><small>${layer.asset?'Custom image selected':'Using automatic or default artwork'}</small><div class="gcs-layer-actions"><button class="btn btn-primary btn-sm" type="button" data-action="browse-asset"><i class="fa-solid fa-folder-open"></i> ${layer.asset?'Replace':'Browse'} image</button><button class="btn btn-ghost btn-sm" type="button" data-action="clear-asset" ${layer.asset?'':'disabled'}>Use automatic</button></div></div>`:'';
  box.innerHTML=`${text}${image}<div class="gcs-control-grid">${['x','y','width','height','rotation','opacity'].map(k=>`<label>${k}<input data-key="${k}" type="number" step="${k==='opacity'?'.05':'1'}" value="${layer[k]??0}"></label>`).join('')}</div>`;
  box.querySelectorAll('[data-key]').forEach(input=>input.onchange=()=>{const key=input.dataset.key;layer[key]=input.type==='number'?Number(input.value):input.value;onChange(true);});
  box.querySelector('[data-action="browse-asset"]')?.addEventListener('click',()=>document.getElementById('gcs-layer-asset-file').click());
  box.querySelector('[data-action="clear-asset"]')?.addEventListener('click',()=>{layer.asset='';onChange(true);});
}

export function renderPages(state,onChange){
  const pages=document.getElementById('gcs-page-list'); pages.innerHTML=(state.project?.pages||[]).map((p,i)=>{const count=(p.cards||[]).length,capacity=Math.max(1,Number(p.grid?.rows)||1)*Math.max(1,Number(p.grid?.columns)||1);return `<button data-page="${i}" class="${i===state.pageIndex?'active':''}"><span>${escapeHtml(p.name||`Page ${i+1}`)}</span><small>${count} / ${capacity} cards</small></button>`;}).join('');
  pages.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>{state.pageIndex=+b.dataset.page;state.cardIndex=0;state.layerIndex=0;onChange(false);});
  const remove=document.getElementById('gcs-remove-page');if(remove){remove.disabled=(state.project?.pages?.length||0)<=1;remove.title=remove.disabled?'A project must keep at least one page':'Remove selected page';}
  const page=currentPage(state); if(!page)return;
  const count=(page.cards||[]).length,capacity=Math.max(1,Number(page.grid?.rows)||1)*Math.max(1,Number(page.grid?.columns)||1);
  const summary=document.getElementById('gcs-page-card-summary');if(summary){summary.textContent=`${count} cards · ${capacity} slots${count>capacity?` · ${count-capacity} overflow`:''}`;summary.classList.toggle('warning',count>capacity);}
  const total=document.getElementById('gcs-project-card-total');if(total)total.textContent=`${(state.project?.pages||[]).reduce((sum,item)=>sum+(item.cards||[]).length,0)} cards`;
  bindNumber('gcs-grid-rows',page.grid,'rows',onChange);bindNumber('gcs-grid-columns',page.grid,'columns',onChange);bindNumber('gcs-gap-x',page.grid,'gap_x',onChange);bindNumber('gcs-gap-y',page.grid,'gap_y',onChange);bindNumber('gcs-page-duration',page,'duration_ms',onChange);
  const trans=document.getElementById('gcs-transition');trans.value=page.transition?.type||'none';trans.onchange=()=>{page.transition=page.transition||{};page.transition.type=trans.value;onChange(true);};
}
function bindNumber(id,obj,key,onChange){const el=document.getElementById(id);el.value=obj?.[key]??0;el.onchange=()=>{obj[key]=Number(el.value);onChange(true);};}
export function pagePreview(state){const p=currentPage(state);return p?renderPageSvg(p,state.project.canvas,assetContext()):'';}
export function escapeHtml(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
const escapeAttr=escapeHtml;

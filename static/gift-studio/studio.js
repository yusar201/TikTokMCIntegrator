import { renderEditor, renderPages, pagePreview, currentPage, currentCard, currentLayer, escapeHtml } from './editor.js?v=2';
import { assignRowHtml, rowMatches } from './assign-rows.js?v=1';
import { createHistory } from './history.js';
import { renderPageSvg } from './renderer.js';
import { autoPaginateProject, duplicatePage, normalizeCardLibrary, assignCardToPage, removeCardFromPage, materializePageCards } from './page-composer.js';

const API='/api/gift-studio';
const state={active:false,bound:false,project:null,projects:[],catalog:[],selected:new Set(),pageIndex:0,cardIndex:0,layerIndex:0,dirty:false,jobId:null,pollTimer:null,raf:null,debounce:null,objectUrls:new Set(),history:null};
const $=id=>document.getElementById(id);
function status(message,type=''){const el=$('gcs-status');el.textContent=message;el.className=`gcs-status ${type}`;}
function toast(message,type='info'){if(typeof window.showToast==='function')window.showToast(message,type);else status(message,type);}

export async function activate(){
  if(state.active)return; state.active=true; bind(); status('Loading Studio…');
  const [projectData,folderData]=await Promise.all([request('/projects'),request('/output-folder')]);
  if(!state.active)return; state.projects=projectData.projects||[];renderProjectSelect(); renderFolder(folderData.output);
  if(state.project)renderAll();else if(state.projects.length)await loadProject(state.projects[0].id); else await createProject('My Gift Cards');
  if(state.jobId)pollJob();
  if(!state.active)return; await loadCatalog(); status('Studio ready.');
}
export function deactivate(){
  state.active=false; if(state.pollTimer){clearTimeout(state.pollTimer);state.pollTimer=null;} if(state.debounce){clearTimeout(state.debounce);state.debounce=null;} if(state.raf){cancelAnimationFrame(state.raf);state.raf=null;}
  for(const url of state.objectUrls)URL.revokeObjectURL(url);state.objectUrls.clear();
}
async function request(path,options={}){const response=await fetch(API+path,{cache:'no-store',headers:{'Content-Type':'application/json',...(options.headers||{})},...options});const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(body.message||body.error||`${response.status} ${response.statusText}`);return body;}
function bind(){if(state.bound)return;state.bound=true;
  document.addEventListener('keydown',event=>{if(!state.active||!(event.ctrlKey||event.metaKey)||event.target?.matches('input,textarea,[contenteditable=true]'))return;if(event.key.toLowerCase()==='z'){event.preventDefault();restoreHistory(event.shiftKey?'redo':'undo');}});
  window.addEventListener('beforeunload',event=>{if(state.dirty){event.preventDefault();event.returnValue='';}});
  document.querySelectorAll('[data-gcs-tab]').forEach(button=>button.onclick=()=>showTab(button.dataset.gcsTab));
  $('gcs-project-select').onchange=()=>loadProject($('gcs-project-select').value); $('gcs-new-project').onclick=()=>createProject(prompt('Project name','My Gift Cards')||'My Gift Cards'); $('gcs-delete-project').onclick=deleteCurrentProject; $('gcs-save-project').onclick=saveProject;
  document.addEventListener('gcs:profile-changed',async()=>{if(!state.active)return;state.selected.clear();await loadCatalog();status('Catalog updated for the selected profile.','success');});
  $('gcs-catalog-search').oninput=()=>{clearTimeout(state.debounce);state.debounce=setTimeout(renderCatalog,120);}; $('gcs-catalog-filter').onchange=renderCatalog; $('gcs-check-all').onclick=toggleAllVisible; $('gcs-import-selected').onclick=importSelected;

  $('gcs-add-text-layer').onclick=addTextLayer; $('gcs-add-gift-icon-layer').onclick=addGiftIconLayer; $('gcs-layer-asset-file').onchange=uploadLayerAsset;
  $('gcs-add-page').onclick=addEmptyPage; $('gcs-add-empty-page').onclick=addEmptyPage; $('gcs-auto-pages').onclick=autoBuildPages; $('gcs-duplicate-page').onclick=duplicateCurrentPage; $('gcs-remove-page').onclick=removePage; $('gcs-refresh-previews').onclick=renderAllPagePreviews;
  $('gcs-choose-folder').onclick=chooseFolder; $('gcs-format').onchange=renderFormat; $('gcs-estimate').onclick=estimate; $('gcs-generate').onclick=generate; $('gcs-cancel').onclick=cancelJob;
  $('gcs-layout-choose-folder').onclick=chooseFolder; $('gcs-layout-format').onchange=()=>{syncGenerateControls('layout');renderFormat();}; $('gcs-layout-png-mode').onchange=()=>syncGenerateControls('layout'); $('gcs-layout-scale').onchange=()=>syncGenerateControls('layout'); $('gcs-layout-estimate').onclick=estimate; $('gcs-layout-generate').onclick=generate; $('gcs-layout-cancel').onclick=cancelJob;
  $('gcs-assign-card').onclick=assignSelectedCards; $('gcs-unassign-card').onclick=unassignSelectedCards; $('gcs-card-up').onclick=()=>moveAssignedCard(-1); $('gcs-card-down').onclick=()=>moveAssignedCard(1);
  const assignSearch=$('gcs-page-card-search'); if(assignSearch&&!assignSearch.dataset.bound){assignSearch.dataset.bound='1';assignSearch.oninput=()=>{clearTimeout(state.assignDebounce);state.assignDebounce=setTimeout(renderPageAssignments,120);};}
}
function showTab(name){document.querySelectorAll('[data-gcs-tab]').forEach(b=>b.classList.toggle('active',b.dataset.gcsTab===name));document.querySelectorAll('[data-gcs-view]').forEach(v=>v.classList.toggle('active',v.dataset.gcsView===name));if(name==='generate')renderFinalPreview();}
async function createProject(name){if(state.dirty&&!(await window.appConfirm({title:'Create Project',message:'Discard unsaved changes and create a project?',confirmText:'Discard & Create',tone:'danger',icon:'fa-file-circle-plus'})))return;const body=await request('/projects',{method:'POST',body:JSON.stringify({name})});state.projects=await request('/projects').then(x=>x.projects||[]);renderProjectSelect();setProject(body.project);}
async function deleteCurrentProject(){if(!state.project)return;const name=state.project.name||state.project.id;if(!(await window.appConfirm({title:'Delete Project',message:`Delete project "${name}"?`,subtitle:'This cannot be undone.',confirmText:'Delete Project',tone:'danger',icon:'fa-folder-trash'})))return;await request(`/projects/${encodeURIComponent(state.project.id)}`,{method:'DELETE'});state.projects=await request('/projects').then(x=>x.projects||[]);if(state.projects.length)await loadProject(state.projects[0].id);else await createProject('My Gift Cards');toast(`Deleted ${name}.`,'success');}
async function loadProject(id){if(!id)return;if(state.dirty){if(!(await window.appConfirm({title:'Switch Project',message:'Discard unsaved changes and switch projects?',confirmText:'Discard & Switch',tone:'danger',icon:'fa-right-left'}))){renderProjectSelect();return;}}const body=await request(`/projects/${encodeURIComponent(id)}`);setProject(body.project);}
function setProject(project){state.project=normalizeCardLibrary(project);state.pageIndex=0;state.cardIndex=0;state.layerIndex=0;state.dirty=false;state.history=createHistory(state.project);renderProjectSelect();renderAll();}
function renderProjectSelect(){const el=$('gcs-project-select');el.innerHTML=state.projects.map(p=>`<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)}</option>`).join('');if(state.project)el.value=state.project.id;}
async function saveProject(){if(!state.project)return;const body=await request(`/projects/${encodeURIComponent(state.project.id)}`,{method:'PUT',body:JSON.stringify({project:state.project})});state.project=normalizeCardLibrary(body.project);state.dirty=false;renderAll();toast('Gift Studio project saved','success');}
async function loadCatalog(){const body=await request('/catalog');state.catalog=body.entries||[];renderCatalog();}
function visibleCatalogRows(){const q=$('gcs-catalog-search').value.trim().toLowerCase(),filter=$('gcs-catalog-filter').value;return state.catalog.filter(e=>(!q||`${e.name} ${(e.commands||[]).join(' ')}`.toLowerCase().includes(q))&&(filter==='all'||filter==='missing'&&e.icon_missing));}
function iconPreview(src,label,fallback){return src?`<img src="${escapeHtml(src)}" alt="${escapeHtml(label)}">`:`<span class="gcs-icon-fallback" aria-label="${escapeHtml(label)}"><i class="fa-solid ${fallback}"></i></span>`;}
function renderCatalog(){const rows=visibleCatalogRows();$('gcs-catalog-list').innerHTML=rows.map(e=>`<label class="gcs-catalog-item"><input type="checkbox" data-key="${escapeHtml(e.key)}" ${state.selected.has(String(e.key))?'checked':''}>${iconPreview(e.icon,'Gift artwork','fa-gift')}<span class="gcs-catalog-copy"><strong>${escapeHtml(e.name)}</strong><small>${e.icon_missing?'Gift artwork missing':'Gift artwork ready'}</small></span></label>`).join('')||'<span>No gifts match.</span>';document.querySelectorAll('#gcs-catalog-list [data-key]').forEach(c=>c.onchange=()=>{c.checked?state.selected.add(c.dataset.key):state.selected.delete(c.dataset.key);renderCheckAll(rows);});renderCheckAll(rows);}


function renderCheckAll(rows=visibleCatalogRows()){const button=$('gcs-check-all');if(!button)return;const allVisibleSelected=rows.length>0&&rows.every(entry=>state.selected.has(String(entry.key)));button.textContent=allVisibleSelected?'Clear visible':'Check all';button.disabled=rows.length===0;}
function toggleAllVisible(){const rows=visibleCatalogRows();const allVisibleSelected=rows.length>0&&rows.every(entry=>state.selected.has(String(entry.key)));rows.forEach(entry=>allVisibleSelected?state.selected.delete(String(entry.key)):state.selected.add(String(entry.key)));renderCatalog();}
async function importSelected(){if(!state.project)return;const keys=[...state.selected];if(!keys.length){toast('Select at least one gift mapping','info');return;}if(state.dirty)await saveProject();status('Caching gift artwork and importing…');const body=await request('/catalog/import',{method:'POST',body:JSON.stringify({project_id:state.project.id,keys,refresh_changed:true,include_action_icon:true,assign_to_page:false})});state.selected.clear();setProject(body.project);status(`Imported ${body.added?.length||0} to Card Library; refreshed ${body.refreshed?.length||0}.`,'success');}
function nextLayerNumber(card,type){return card.layers.filter(layer=>layer.type===type).length+1;}
function topZIndex(card){return Math.max(0,...card.layers.map(layer=>Number(layer.z_index)||0))+1;}
function addGiftIconLayer(){
  const card=currentCard(state);if(!card){toast('Select a card first','info');return;}
  const width=Number(card.width)||272,height=Number(card.height)||192;
  // Badge proportions follow the import default: 30% of the card's short side,
  // tucked into the bottom-left inside the panel border.
  const size=Math.max(8,Math.round(Math.min(width,height)*0.30));
  const inset=Math.max(4,Math.round(Math.min(width,height)*0.055));
  card.layers.push({id:`gift-icon-${Date.now()}`,type:'gift_icon',name:`Gift Icon ${nextLayerNumber(card,'gift_icon')}`,asset:'',auto_link:true,fit:'contain',pixelated:true,x:inset,y:Math.max(inset,height-inset-size),width:size,height:size,rotation:0,opacity:1,visible:true,z_index:topZIndex(card)});
  state.layerIndex=card.layers.length-1;changed(true,'card');
}
function addTextLayer(){
  const card=currentCard(state);if(!card){toast('Select a card first','info');return;}
  const number=nextLayerNumber(card,'text');
  const z=topZIndex(card);
  card.layers.push({id:`text-${Date.now()}`,type:'text',name:`Text ${number}`,text:'NEW TEXT',x:24,y:24,width:272,height:52,rotation:0,opacity:1,visible:true,z_index:z,font_family:'Minecraft',font_size:24,font_weight:700,color:'#ffffff',align:'center',vertical_align:'middle',uppercase:false,responsive_text:true,letter_spacing:0,line_height:1.1,stroke:'#000000',stroke_width:2});
  state.layerIndex=card.layers.length-1;changed(true,'card');
}
async function uploadLayerAsset(event){
  const file=event.target.files?.[0],layer=currentLayer(state);event.target.value='';
  if(!file||!layer||!['image','action_icon','gift_icon'].includes(layer.type))return;
  const form=new FormData();form.append('file',file);
  status(`Uploading ${file.name}…`);
  try{
    const response=await fetch(API+'/assets',{method:'POST',body:form,cache:'no-store'});
    const body=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(body.message||'Image upload failed');
    layer.asset=`/gift-studio-assets/${encodeURIComponent(body.asset.name)}`;
    changed(true,'card');status(`${layer.type==='gift_icon'?'Gift icon':'Action icon'} replaced.`,'success');
  }catch(error){toast(error.message||'Image upload failed','error');status('Image upload failed.','error');}
}
function restoreHistory(direction){if(!state.history)return;state.project=normalizeCardLibrary(state.history[direction]());state.pageIndex=Math.min(state.pageIndex,state.project.pages.length-1);state.cardIndex=Math.min(state.cardIndex,Math.max(0,state.project.card_library.length-1));state.layerIndex=0;state.dirty=true;renderAll();}
function changed(push,scope='page'){if(push&&scope==='card'&&currentCard(state))currentCard(state).customized=true;state.project=materializePageCards(state.project);if(push)state.dirty=true;if(push&&state.history)state.history.push(state.project);renderAll();}
function renderAll(){if(!state.project)return;renderEditor(state,(push)=>changed(push,'card'));renderPages(state,changed);renderPageAssignments();renderFinalPreview();renderAllPagePreviews();syncGenerateControls();}
function emptyPage(number){const source=currentPage(state);return{id:`page-${Date.now()}-${number}`,name:`Page ${number}`,duration_ms:source?.duration_ms||5000,transition:source?.transition?structuredClone(source.transition):null,grid:structuredClone(source?.grid||{rows:1,columns:1,gap_x:20,gap_y:20,padding:24,fill_order:'row',fit:'contain'}),scroll:structuredClone(source?.scroll||{enabled:false,direction:'left',speed_px_per_second:80,loop:true,item_gap:20,edge_pause_ms:0}),cards:[]};}
function addEmptyPage(){if(!state.project)return;state.project.pages.push(emptyPage(state.project.pages.length+1));state.pageIndex=state.project.pages.length-1;state.cardIndex=0;state.layerIndex=0;changed(true);toast('Empty page added. Use Auto-build pages to distribute all cards automatically.','info');}
function autoBuildPages(){if(!state.project)return;const count=(state.project.card_library||[]).length;if(!count){toast('Import cards from Catalog first','info');return;}state.project=autoPaginateProject(state.project,state.pageIndex);state.pageIndex=0;state.cardIndex=0;state.layerIndex=0;changed(true);const sizes=state.project.pages.map(page=>(page.cards||[]).length).join(' + ');toast(`Built ${state.project.pages.length} populated pages (${sizes} cards)`,'success');}
function duplicateCurrentPage(){if(!state.project||!currentPage(state))return;const copy=duplicatePage(currentPage(state),state.project.pages.length+1);state.project.pages.splice(state.pageIndex+1,0,copy);state.pageIndex+=1;state.cardIndex=0;state.layerIndex=0;changed(true);toast('Page duplicated; cards remain linked to the library','success');}
function currentAssignFilter(){const el=$('gcs-page-card-search');return (el?el.value:'').trim().toLowerCase();}
function syncAssignBox(box,sel){
  if(!box)return;
  box.querySelectorAll('[data-assign-card]').forEach(row=>{
    const on=sel?sel.has(row.dataset.assignCard):row.classList.contains('selected');
    row.classList.toggle('selected',on);
    row.setAttribute('aria-checked',on?'true':'false');
  });
}
function bindAssignBox(box,sel){
  if(!box||box.dataset.bound)return;box.dataset.bound='1';
  box.addEventListener('click',event=>{
    const row=event.target.closest('[data-assign-card]');
    if(!row||!box.contains(row))return;
    const id=row.dataset.assignCard,on=!row.classList.contains('selected');
    row.classList.toggle('selected',on);row.setAttribute('aria-checked',on?'true':'false');
    if(sel){on?sel.add(id):sel.delete(id);}
  });
  box.addEventListener('keydown',event=>{
    if(event.key!==' '&&event.key!=='Enter')return;
    const row=event.target.closest&&event.target.closest('[data-assign-card]');
    if(!row||!box.contains(row))return;
    event.preventDefault();
    const id=row.dataset.assignCard,on=!row.classList.contains('selected');
    row.classList.toggle('selected',on);row.setAttribute('aria-checked',on?'true':'false');
    if(sel){on?sel.add(id):sel.delete(id);}
  });
}
function assignSel(which){
  state.assignSel=state.assignSel||{available:new Set(),assigned:new Set()};
  return state.assignSel[which];
}
function selectedAssignIds(box){return [...(box?box.querySelectorAll('[data-assign-card].selected'):[])].map(row=>row.dataset.assignCard);}
function renderPageAssignments(){const page=currentPage(state),available=$('gcs-page-card-library'),assigned=$('gcs-page-assigned-cards');if(!page||!available||!assigned)return;const availSel=assignSel('available'),assignSelSet=assignSel('assigned');bindAssignBox(available,availSel);bindAssignBox(assigned,assignSelSet);const query=currentAssignFilter();const ids=new Set((page.card_ids||[]).map(String)),library=state.project.card_library||[];for(const gone of [...availSel])if(!library.some(card=>String(card.id)===gone&&!ids.has(gone)))availSel.delete(gone);for(const gone of [...assignSelSet])if(!(page.card_ids||[]).includes(gone))assignSelSet.delete(gone);const visible=library.filter(card=>!ids.has(String(card.id)));const shown=visible.filter(card=>rowMatches(card,query));available.innerHTML=shown.map(card=>assignRowHtml(card,availSel.has(String(card.id)))).join('')||`<span class="gcs-assign-empty">${visible.length?'No cards match this filter.':'All library cards are already on this page.'}</span>`;assigned.innerHTML=(page.card_ids||[]).map(id=>{const card=library.find(item=>String(item.id)===String(id));return card?assignRowHtml(card,assignSelSet.has(String(card.id))):'';}).join('')||'<span class="gcs-assign-empty">No cards on this page yet.</span>';const availCount=$('gcs-available-count');if(availCount)availCount.textContent=`${shown.length} of ${visible.length}`;const assignCount=$('gcs-assigned-count');if(assignCount)assignCount.textContent=`${(page.card_ids||[]).length}`;}
function assignSelectedCards(){const ids=selectedAssignIds($('gcs-page-card-library'));if(!ids.length){toast('Select at least one card first','info');return;}for(const id of ids)state.project=assignCardToPage(state.project,state.pageIndex,id);assignSel('available').clear();changed(true);}
function unassignSelectedCards(){const ids=selectedAssignIds($('gcs-page-assigned-cards'));if(!ids.length){toast('Select at least one assigned card first','info');return;}for(const id of ids)state.project=removeCardFromPage(state.project,state.pageIndex,id);assignSel('assigned').clear();changed(true);}
function moveAssignedCard(delta){const box=$('gcs-page-assigned-cards'),page=currentPage(state);if(!box||!page)return;const rows=[...box.querySelectorAll('[data-assign-card]')];const lead=box.querySelector('[data-assign-card].selected')||rows[0];if(!lead)return;const id=lead.dataset.assignCard,index=page.card_ids.indexOf(id),next=index+delta;if(index<0||next<0||next>=page.card_ids.length)return;[page.card_ids[index],page.card_ids[next]]=[page.card_ids[next],page.card_ids[index]];changed(true);requestAnimationFrame(()=>{const fresh=$('gcs-page-assigned-cards');if(!fresh)return;const sel=assignSel('assigned');sel.clear();sel.add(id);syncAssignBox(fresh,sel);const target=fresh.querySelector(`[data-assign-card="${CSS.escape(id)}"]`);if(target)target.scrollIntoView({block:'nearest'});});}
function removePage(){if(!state.project||state.project.pages.length<=1){toast('A project must keep at least one page','info');return;}state.project.pages.splice(state.pageIndex,1);state.pageIndex=Math.min(state.pageIndex,state.project.pages.length-1);state.cardIndex=0;state.layerIndex=0;changed(true);}
function renderFinalPreview(){if(!state.project)return;const el=$('gcs-preview');el.innerHTML=pagePreview(state)||'<span>No page to preview.</span>';}
function renderAllPagePreviews(){const box=$('gcs-all-page-previews');if(!box||!state.project)return;box.innerHTML=state.project.pages.map((page,index)=>`<button type="button" class="gcs-page-preview-card ${index===state.pageIndex?'active':''}" data-preview-page="${index}"><span><b>${escapeHtml(page.name||`Page ${index+1}`)}</b><small>${(page.cards||[]).length} cards · ${page.grid?.rows||1}×${page.grid?.columns||1}</small></span><div class="gcs-page-preview-stage">${renderPageSvg(page,state.project.canvas,{assetBase:''})}</div></button>`).join('');box.querySelectorAll('[data-preview-page]').forEach(button=>button.onclick=()=>{state.pageIndex=Number(button.dataset.previewPage);state.cardIndex=0;state.layerIndex=0;renderAll();});}
function syncGenerateControls(source='main'){const pairs=[['gcs-output-folder','gcs-layout-output'],['gcs-format','gcs-layout-format'],['gcs-png-mode','gcs-layout-png-mode'],['gcs-scale','gcs-layout-scale']];for(const [main,layout] of pairs){const a=$(main),b=$(layout);if(!a||!b)continue;if(source==='layout')a.value=b.value;else b.value=a.value;}}
function renderFormat(){syncGenerateControls();const gif=$('gcs-format').value==='gif';$('gcs-gif-settings').hidden=!gif;$('gcs-png-settings').hidden=gif;$('gcs-layout-png-mode').disabled=gif;}
function settings(){const gif=$('gcs-format').value==='gif';return gif?{format:'gif',fps:Number($('gcs-fps').value)||15,duration_ms:$('gcs-duration').value?Number($('gcs-duration').value):null}:{format:'png',mode:$('gcs-png-mode').value,scale:Number($('gcs-scale').value)||1,page_index:state.pageIndex,card_index:state.cardIndex};}
async function chooseFolder(){const body=await request('/output-folder/browse',{method:'POST',body:'{}'});renderFolder(body.output);if(body.status==='cancelled')status('Folder selection cancelled.');}
function renderFolder(info){for(const id of ['gcs-output-folder','gcs-layout-output']){const el=$(id);if(el){el.value=info?.path||'';el.title=info?.path||'';}}}
async function estimate(){if(!state.project)return;const body=await request('/generate/estimate',{method:'POST',body:JSON.stringify({project:state.project,settings:settings()})});const e=body.estimate||{},text=[`${e.file_count??1} file(s)`,`${e.output_width||0} × ${e.output_height||0}`,e.frame_count?`${e.frame_count} frames`:null,e.duration_ms?`${e.duration_ms} ms`:null,e.zipped?'ZIP archive':null].filter(Boolean).join(' · ');$('gcs-estimate-result').textContent=text;$('gcs-layout-estimate-result').textContent=text;}
async function generate(){if(!state.project)return;if(state.dirty)await saveProject();const body=await request('/generate',{method:'POST',body:JSON.stringify({project_id:state.project.id,save:true,settings:settings()})});state.jobId=body.job.id;for(const id of ['gcs-cancel','gcs-layout-cancel'])$(id).hidden=false;for(const id of ['gcs-generate','gcs-layout-generate'])$(id).disabled=true;pollJob();}
async function pollJob(){if(!state.active||!state.jobId)return;try{const body=await request(`/generate/jobs/${state.jobId}`),job=body.job;for(const id of ['gcs-progress','gcs-layout-progress'])$(id).value=job.percent||0;status(job.message||job.status);if(job.status==='done'){finishJob(job);return;}if(job.status==='error'||job.status==='cancelled'){throw new Error(job.message||job.status);}state.pollTimer=setTimeout(pollJob,400);}catch(error){resetJob();for(const id of ['gcs-result','gcs-layout-result']){$(id).className='gcs-result error';$(id).textContent=error.message;}}}
function finishJob(job){const html=`Saved: <code>${escapeHtml(job.saved_path||job.download_name||'')}</code> <a href="${API}/generate/jobs/${encodeURIComponent(job.id)}/download">Download fallback</a>`;for(const id of ['gcs-result','gcs-layout-result']){$(id).className='gcs-result success';$(id).innerHTML=html;}const preview=$('gcs-preview');preview.innerHTML='';const img=document.createElement('img');img.src=`${API}/generate/jobs/${encodeURIComponent(job.id)}/download?t=${Date.now()}`;img.alt='Generated artifact';preview.appendChild(img);resetJob();}
function resetJob(){state.jobId=null;if(state.pollTimer)clearTimeout(state.pollTimer);state.pollTimer=null;for(const id of ['gcs-cancel','gcs-layout-cancel'])$(id).hidden=true;for(const id of ['gcs-generate','gcs-layout-generate'])$(id).disabled=false;}
async function cancelJob(){if(!state.jobId)return;await request(`/generate/jobs/${state.jobId}/cancel`,{method:'POST',body:'{}'});}

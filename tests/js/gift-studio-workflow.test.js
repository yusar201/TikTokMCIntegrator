import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import * as composer from '../../static/gift-studio/page-composer.js';
import {createHistory} from '../../static/gift-studio/history.js';
function harness(){
 const elements=new Map(),calls=[],messages=[];
 const el=id=>{if(!elements.has(id))elements.set(id,{value:'',hidden:false,classList:{contains:()=>false,toggle(){}},querySelectorAll:()=>[],innerHTML:'',textContent:''});return elements.get(id);};
 el('gcs-format').value='png';el('gcs-png-mode').value='page';el('gcs-scale').value='1';
 const ctx={...composer,createHistory,console,Set,Map,JSON,Number,String,Math,Date,structuredClone,URL,setTimeout,clearTimeout,queueMicrotask,document:{getElementById:el,querySelector:()=>null,querySelectorAll:()=>[]},window:{showToast:m=>messages.push(m)},confirm:()=>true,currentPage:s=>s.project.pages[s.pageIndex],currentCard:s=>s.project.card_library[s.cardIndex],currentLayer:s=>s.project.card_library[s.cardIndex]?.layers[s.layerIndex],escapeHtml:String,renderEditor(){},renderPages(){},pagePreview:()=>'',renderPageSvg:()=>'',fetch:async(url,options)=>{calls.push({url,body:options.body?JSON.parse(options.body):null});return {ok:true,json:async()=>url.endsWith('/generate')?{job:{id:'job'}}:{project:structuredClone(ctx.audit.state.project)}};}};
 vm.createContext(ctx);
 const src=fs.readFileSync(new URL('../../static/gift-studio/studio.js',import.meta.url),'utf8').replace(/^import .*;\n/gm,'').replace(/export /g,'');
 vm.runInContext(src+'\nrenderAll=()=>{};globalThis.audit={state,autoBuildPages,changed,saveProject,generate,importSelected,loadProject,restoreHistory};',ctx);
 const p={id:'p',name:'P',card_library:[{id:'a',layers:[],customized:false}],pages:[{id:'p1',cards:[],card_ids:[],grid:{rows:1,columns:1}},{id:'p2',cards:[],card_ids:[],grid:{rows:1,columns:1}}]};
 Object.assign(ctx.audit.state,{project:p,pageIndex:1,history:createHistory(p)});
 return {...ctx.audit,calls,messages};
}
test('auto build consumes an unassigned library',()=>{const h=harness();h.autoBuildPages();assert.equal(h.state.project.pages[0].cards.length,1);});
test('card edits are protected from refresh',()=>{const h=harness();h.changed(true,'card');assert.equal(h.state.project.card_library[0].customized,true);});
test('import saves pending changes before fetching saved project',async()=>{const h=harness();h.state.dirty=true;h.state.selected.add('a');await h.importSelected();assert.ok(h.calls[0].url.endsWith('/projects/p'));assert.ok(h.calls[1].url.endsWith('/catalog/import'));});
test('selection is not a content edit',()=>{const h=harness();h.changed(false);assert.equal(h.state.dirty,false);});
test('dirty generation preserves selected page',async()=>{const h=harness();h.state.dirty=true;await h.generate();assert.equal(h.calls.at(-1).body.settings.page_index,1);});
test('save preserves undo history and selection',async()=>{const h=harness();const history=h.state.history;await h.saveProject();assert.equal(h.state.pageIndex,1);assert.equal(h.state.history,history);});

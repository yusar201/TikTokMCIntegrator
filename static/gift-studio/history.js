export function createHistory(initial, limit = 50) {
  let past = [];
  let present = structuredClone(initial);
  let future = [];
  return {
    get value(){ return structuredClone(present); },
    push(next){ past.push(structuredClone(present)); if(past.length>limit) past.shift(); present=structuredClone(next); future=[]; return this.value; },
    undo(){ if(!past.length)return this.value; future.unshift(structuredClone(present)); present=past.pop(); return this.value; },
    redo(){ if(!future.length)return this.value; past.push(structuredClone(present)); present=future.shift(); return this.value; },
    get canUndo(){return past.length>0;}, get canRedo(){return future.length>0;}
  };
}

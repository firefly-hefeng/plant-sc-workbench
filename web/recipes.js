/* Project-independent parameter recipes. Data files remain in the chosen project. */
const recipeSchema='plant-workbench/recipe-v1';
function recipeForm(){
  return card('分析配方','sliders','<p class="meta">保留本次科学参数与参考选择。应用到另一项目时，文库和样本信息由该项目提供。</p><div class="actions">'+
    btn('查看执行模块','inspect-recipe','layers','soft')+btn('保存项目方案','save-draft','check')+
    btn('导出配方','export-recipe','install')+btn('载入配方','import-recipe','folder')+'</div>');
}
function exportRecipe(){
  const blob=new Blob([JSON.stringify({schema:recipeSchema,reference:S.draft.reference,params:portableParams(S.draft.params)},null,2)],{type:'application/json'});
  const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download='植物单细胞分析配方.json';link.click();
  setTimeout(()=>URL.revokeObjectURL(link.href),800);
}
function portableParams(p){
  const data={...p};for(const key of ['reference_dir','star_index','whitelist','gtf','fasta','clusters_tsv'])delete data[key];return data;
}
function importRecipe(){
  const input=document.createElement('input');input.type='file';input.accept='.json,application/json';
  input.onchange=async()=>{try{
    const f=input.files[0];if(!f)return;if(f.size>65536)throw Error('配方文件过大。');
    const obj=JSON.parse(await f.text());
    if(obj.schema!==recipeSchema||!obj.params||Array.isArray(obj.params)||typeof obj.params!=='object')throw Error('请选择从本工作台导出的分析配方。');
    const ref=obj.reference||'none';if(!['custom','none'].includes(ref)&&!refOf(ref))throw Error('本机未安装配方指定的参考集。');
    S.draft.params={...portableParams(obj.params)};S.draft.reference=ref;S.draft.referenceChosen=true;S.draft.referenceNote='';
    markChanged();await persistInputs();render();toast(ref==='custom'?'已载入参数，请在“物种与参考基因集”中选择自定义参考。':'已载入配方，当前项目文库已保留。');
  }catch(err){toast(err.message,true)}};input.click();
}
async function inspectRecipe(){
  const val=await api('/api/recipe',dataSpec('analysis',stageLibraries(5)));
  const html=val.blocks.map(x=>'<div class="library-row"><div><strong>'+e(x.title)+'</strong><div class="hint">'+e(x.engine)+' · '+e(x.consumes)+' → '+e(x.produces)+'</div>'+'<details class="port-schema"><summary>接口与方法依据</summary><p>输入 · '+x.ports.inputs.map(p=>e(p.label)+' ('+e(p.type)+')').join('、')+'</p><p>输出 · '+x.ports.outputs.map(p=>e(p.label)+' ('+e(p.type)+')').join('、')+'</p><p>'+e(x.practice.review)+' <a target="_blank" rel="noopener" href="'+e(x.practice.source)+'">方法来源</a></p></details>'+(x.issues?.length?banner(x.issues.join('；'),true):'')+'</div>'+pill(x.state==='ready'?'就绪':'待补齐',x.state==='ready'?'succeeded':'failed')+'</div>').join('');
  modalShow('本次执行模块',html,'recipe',true);
}


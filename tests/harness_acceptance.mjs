// Exercise the installed DSH Cordis host, ToolRuntime and actual stdio bridge offline.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const dsh=process.env.DSH_DEPENDENCIES||path.join(process.env.APPDATA,'npm','node_modules','@deepseek-ai','dsh','node_modules','@deepseek-ai');
const load=p=>import(pathToFileURL(path.join(dsh,p,'lib','index.js')).href);
const {Context}=await load('cordis');
const {SystemPrompt}=await load('dsh-system-prompt');
const {ToolsService}=await load('dsh-tools');
const mcp=await load('dsh-mcp-client');
const python=process.env.PLANT_PYTHON||path.join(root,'.venv','Scripts','python.exe');
const cfg=JSON.parse(execFileSync(python,[path.join(root,'harness','server.py'),'--print-config'],{encoding:'utf8',env:{...process.env,PYTHONIOENCODING:'utf-8'}}))[0].config;
const ctx=new Context();
let outcome;
try{
  ctx.plugin(SystemPrompt,{});ctx.plugin(ToolsService,{});ctx.plugin(mcp,{...cfg,failOnStartupError:true,reconnect:{enabled:false}});
  const tools=['catalog','new_project','discover','plan','preview_qc','run','status','list_results','read_table','task_io'];
  for(let i=0;i<120 && !ctx.get('tools')?.get('mcp__plantsc__catalog');i++)await new Promise(r=>setTimeout(r,150));
  async function call(n,args){
    const def=ctx.tools.get('mcp__plantsc__'+n);
    if(!def)throw Error('Tool was not registered: '+n);
    const resp=await def.execute(args,{signal:AbortSignal.timeout(120000)});
    return JSON.parse(resp.content[0].text);
  }
  const catalog=await call('catalog',{});
  const sample=JSON.parse(fs.readFileSync(path.join(root,'lab-notebook','gui-run.json'),'utf8'));
  const plan=await call('plan',{project:sample.project,action:'recluster',parent_job:sample.job,params:{resolutions:[0.45,0.9]}});
  const task=await call('run',{project:sample.project,action:'recluster',parent_job:sample.job,params:{resolutions:[0.45,0.9],seed:42}});
  let last;
  for(let i=0;i<120;i++){last=await call('status',{job:task.id});if(!['queued','running'].includes(last.state))break;await new Promise(r=>setTimeout(r,1000));}
  if(last.state!=='succeeded')throw Error(JSON.stringify(last));
  const table=await call('read_table',{project:sample.project,path:last.output+'/cluster_comparison.tsv'});
  const io=await call('task_io',{project:sample.project,job:task.id});
  const modules=io.modules.map(m=>m.module);
  if(io.schema!=='plant-task-io/1'||!io.inputs.parent||!io.outputs.object||!modules.includes('leiden')||!modules.includes('export'))throw Error('Incomplete task ports');
  const single=await call('run',{project:sample.project,action:'umap',parent_job:sample.job,params:{min_dist:0.6,seed:42}});
  let singleState;
  for(let i=0;i<240;i++){singleState=await call('status',{job:single.id});if(!['running','queued'].includes(singleState.state))break;await new Promise(r=>setTimeout(r,1000));}
  if(singleState.state!=='succeeded')throw Error(JSON.stringify(singleState));
  const selected=await call('task_io',{project:sample.project,job:single.id,module:'umap'});
  if(selected.modules.length!==1||selected.modules[0].outputs.embedding[0].selector!=='obsm/X_umap'||selected.modules[0].parameters.min_dist!==0.6)throw Error('Missing stand-alone UMAP result');
  const registered=tools.every(n=>ctx.tools.get('mcp__plantsc__'+n));
  if(!registered||!table.rows.length)throw Error('Missing tool or result');
  outcome={host:'DSH Cordis + ToolsService + dsh-mcp-client',registered:tools,actual_model_calls:0,source_job:sample.job,project:sample.project,
    job:task.id,standalone:{job:single.id,parent:sample.job,action:'umap',min_dist:0.6,manifest:selected.manifest_path},state:last.state,modules,blocks:plan.blocks.map(b=>b.id),comparison_table:table};
  fs.writeFileSync(path.join(root,'lab-notebook','workspace-v2-harness.json'),JSON.stringify(outcome,null,2));
  console.log(JSON.stringify({tools:tools.length,state:last.state,job:task.id}));
}finally{await ctx.fiber.dispose();}


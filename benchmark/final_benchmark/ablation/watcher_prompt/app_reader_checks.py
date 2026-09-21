"""Real application-reader checks, invoked by test_watchers_e2e.py."""
import asyncio
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import time
import zipfile

async def inside_readers(setting):
    import httpx
    from fastmcp import Client
    from test_watchers_e2e import pack, require
    require(setting=='without_txt','Reader checks target without_txt')
    out=Path('/tmp/e2e-result');out.mkdir(exist_ok=True)
    report={'setting':setting,'checks':[],'tool_calls':[],'formats':[]}
    def check(ok,label):
        require(ok,label);report['checks'].append(label);print('PASS',label,flush=True)
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8080',timeout=180) as http:
        for _ in range(120):
            try:
                if (await http.get('/health')).is_success:break
            except httpx.HTTPError:pass
            await asyncio.sleep(.5)
        else:raise RuntimeError('health timeout')
        servers={}
        for key,package,server in [('code','code','code_execution_server'),('filesystem','filesystem','filesystem_server'),('docs','documents','docs_server'),('pdf','pdfs','pdf_server'),('slides','presentations','slides_server'),('sheets','spreadsheets','sheets_server')]:
            servers[key]={'transport':'stdio','command':f'/app/mcp_servers/{package}/.venv/bin/python','args':['main.py'],
                'cwd':f'/app/mcp_servers/{package}/mcp_servers/{server}',
                'env':{'APP_FS_ROOT':'/filesystem','SERVER_NAME':server,'USE_INDIVIDUAL_TOOLS':'true','MCP_TRANSPORT':'stdio'}}
        response=await http.post('/apps',json={'mcpServers':servers});response.raise_for_status()
        async def populate(subsystem,files,hooks=None):
            r=await http.post('/data/populate',params={'subsystem':subsystem},files={'archive':('fixture.tar.gz',pack(files),'application/gzip')},data={'post_populate_hooks':json.dumps(hooks)} if hooks else {})
            r.raise_for_status()
        await populate('.apps_data',{'dynamic_watcher/'+n:Path('/tmp/e2e-bundle',n).read_bytes() for n in ['dynamic_watcher.py','dynamic_document_formats.py','config.json']})
        config=json.loads(Path('/tmp/e2e-bundle/config.json').read_text())
        sys.path.insert(0,'/tmp/e2e-bundle')
        from dynamic_document_formats import write_pdf
        fixture=Path('/tmp/reader-fixtures');fixture.mkdir()
        for suffix in ['txt','md','html']: (fixture/f'read.{suffix}').write_text('Original fixture '+suffix)
        (fixture/'read.csv').write_text('message\nOriginal fixture csv\n')
        write_pdf(fixture/'read.pdf',['Original fixture pdf'])
        def create(package,source):
            subprocess.run([f'/app/mcp_servers/{package}/.venv/bin/python','-c',source],check=True)
        create('documents',"from docx import Document\nd=Document();d.add_paragraph('Original fixture docx');d.save('/tmp/reader-fixtures/read.docx')")
        create('presentations',"from pptx import Presentation\np=Presentation();s=p.slides.add_slide(p.slide_layouts[5]);s.shapes.title.text='Original fixture pptx';p.save('/tmp/reader-fixtures/read.pptx')")
        # Complete XLSX package; readable by the production sheets application.
        with zipfile.ZipFile(fixture/'read.xlsx','w') as z:
            z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
            z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
            z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>')
            z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
            z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Original fixture xlsx</t></is></c></row></sheetData></worksheet>')
        async with Client('http://127.0.0.1:8080/mcp/') as client:
            tools=await client.list_tools(); schemas={t.name:t.inputSchema for t in tools}
            (out/'tool_schemas.json').write_text(json.dumps(schemas,indent=2))
            async def call(ending,arguments):
                tool=next(t for t in tools if t.name.endswith('_'+ending))
                props=tool.inputSchema.get('properties',{})
                if 'input' in props:arguments={'input':arguments}
                elif 'request' in props:arguments={'request':arguments}
                result=await client.call_tool(tool.name,arguments)
                values=[c.text for c in result.content if hasattr(c,'text')]
                report['tool_calls'].append({'tool':tool.name,'arguments':arguments,'output':values})
                (out/'progress.json').write_text(json.dumps(report,indent=2))
                require(not result.is_error,str(values))
                def unwrap(x):
                    if isinstance(x,dict):return '\n'.join(unwrap(v) for v in x.values())
                    if isinstance(x,list):return '\n'.join(unwrap(v) for v in x)
                    if isinstance(x,str):
                        try: y=json.loads(x)
                        except ValueError:return x.replace('\\n','\n').replace('\\t','\t')
                        return unwrap(y) if y!=x else x
                    return str(x)
                return unwrap(values)
            for suffix in ['txt','md','csv','html','pdf','docx','xlsx','pptx']:
                name='read.'+suffix; body=(fixture/name).read_bytes(); await populate('filesystem',{name:body})
                p=Path('/filesystem')/name; archive=p.with_name(p.stem+'_archive'+p.suffix)
                await populate('filesystem',{},[{'name':'dynamic-prompt-watcher','command':'python3 /.apps_data/dynamic_watcher/dynamic_watcher.py --config /.apps_data/dynamic_watcher/config.json --startup-timeout 30'}])
                ending,args={
                    'pdf':('read_pdf_pages',{'file_path':'/'+name}),
                    'docx':('read_document_content',{'file_path':'/'+name}),
                    'xlsx':('read_tab',{'file_path':'/'+name,'tab_index':0,'compact':True}),
                    'pptx':('read_slides',{'file_path':'/'+name,'start':0,'end':10000}),
                    'csv':('read_csv',{'file_path':'/'+name}),
                }.get(suffix,('read_text_file',{'file_path':'/'+name}))
                first=await call(ending,args)
                check('Original fixture '+suffix in first,suffix+': app reads original content')
                deadline=time.monotonic()+20
                while not archive.exists():
                    require(time.monotonic()<deadline,'injection timeout '+suffix);await asyncio.sleep(.05)
                await asyncio.sleep(.2)
                exposed=await call(ending,args)
                expected=config['instruction_template'].replace('{original_name}',name).replace('{preserved_name}',archive.name)
                norm=lambda x:' '.join(x.split())
                check('This file is corrupted.' in exposed,suffix+': corruption notice visible')
                # Each full original line must be visible; app-added paragraph/row labels are allowed.
                for line in expected.splitlines():
                    if line.strip():check(norm(line) in norm(exposed),suffix+': complete instruction line visible')
                check(not list(Path('/filesystem').glob('* additional task instruction.txt')),suffix+': no sidecar TXT')
                await call('code_exec',{'code':"python3 -c \"from pathlib import Path;p=Path('/filesystem/shared');p.mkdir(exist_ok=True);(p/'done-"+suffix+".md').write_text('Synthetic test activity')\""})
                deadline=time.monotonic()+15
                while archive.exists():
                    require(time.monotonic()<deadline,'restore timeout '+suffix);await asyncio.sleep(.05)
                check(p.read_bytes()==body,suffix+': exact original restored')
                await asyncio.sleep(.3)
                report['formats'].append({'format':suffix,'reader':ending,'status':'passed'})
    report['status']='passed';(out/'report.json').write_text(json.dumps(report,indent=2))
    with tarfile.open(out/'final_filesystem.tar.gz','w:gz') as tar:tar.add('/filesystem',arcname='filesystem')
    (out/'watcher.log').write_text(Path('/tmp/dynamic-watcher.log').read_text())

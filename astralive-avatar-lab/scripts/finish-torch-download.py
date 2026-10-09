"""Resume a partial official wheel with six ranged requests; validate official hash."""
import concurrent.futures,hashlib,html,json,os,pathlib,re,requests,shutil,time,urllib.parse
LAB=pathlib.Path('/root/autodl-tmp/astralive-avatar-lab');DEST=LAB/'wheelhouse';DEST.mkdir(exist_ok=True)
NAME='torch-2.0.1+cu118-cp310-cp310-linux_x86_64.whl'
index=requests.get('https://download.pytorch.org/whl/cu118/torch/',timeout=30);index.raise_for_status()
links=re.findall(r'href="([^"]+)"',index.text)
link=next(x for x in links if urllib.parse.unquote(x.split('#')[0]).endswith('/'+NAME))
url=urllib.parse.urljoin(index.url,html.unescape(link));expected=urllib.parse.parse_qs(urllib.parse.urlsplit(url).fragment)['sha256'][0];url=url.split('#')[0]
official_url=url
if os.environ.get('TORCH_R2')=='1':url=url.replace('https://download.pytorch.org/','https://download-r2.pytorch.org/')
with requests.get(url,headers={'Range':'bytes=0-0'},stream=True,timeout=30) as resp:
    resp.raise_for_status()
    if resp.status_code!=206:raise RuntimeError('Range not supported')
    total=int(resp.headers['Content-Range'].split('/')[1])
prefix=DEST/'torch-prefix.partial';offset=prefix.stat().st_size
if offset>=total:raise RuntimeError('Unexpected partial size')
step=(total-offset+5)//6
def fetch(i):
    begin=offset+i*step;end=min(total-1,begin+step-1);part=DEST/f'torch-range-{i}.partial'
    expected_size=end-begin+1
    tail=DEST/f'torch-range-{i}.tail'
    if tail.exists() and part.exists() and part.stat().st_size+tail.stat().st_size==expected_size:
        with part.open('ab') as dst,tail.open('rb') as src:shutil.copyfileobj(src,dst)
        print('MERGED RELAY TAIL',i,flush=True)
    for attempt in range(3):
        size=part.stat().st_size if part.exists() else 0
        if size==expected_size:return part
        try:
            with requests.get(url,headers={'Range':f'bytes={begin+size}-{end}'},stream=True,timeout=(30,60)) as r:
                r.raise_for_status()
                if r.status_code!=206 or not r.headers.get('Content-Range','').startswith(f'bytes {begin+size}-'):raise RuntimeError('Invalid range response')
                with part.open('ab') as f:
                    for chunk in r.iter_content(1024*1024):f.write(chunk)
            if part.stat().st_size!=expected_size:raise RuntimeError('Incomplete range')
            print('RANGE PASS',i,expected_size,flush=True);return part
        except Exception as exc:
            print('RANGE RETRY',i,attempt,type(exc).__name__,flush=True)
            if attempt==2:raise RuntimeError(f'Range {i} failed') from None
            time.sleep(2)
print('RESUME',offset,'/',total,'official SHA256',expected,flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:parts=list(pool.map(fetch,range(6)))
out=DEST/NAME;h=hashlib.sha256()
with out.open('wb') as f:
    for part in [prefix,*parts]:
        with part.open('rb') as source:
            for block in iter(lambda:source.read(4*1024*1024),b''):f.write(block);h.update(block)
if out.stat().st_size!=total or h.hexdigest()!=expected:raise RuntimeError('Official wheel hash mismatch')
(LAB/'reports/torch-wheel-download.json').write_text(json.dumps({'official_url':official_url,'transport_url':url,'bytes':total,'sha256':expected,'preserved_prefix_bytes':offset,'parallel_ranges':6,'verification':'PASS'},indent=2))
print('OFFICIAL WHEEL SHA256 PASS',out,flush=True)

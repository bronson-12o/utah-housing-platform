"""Optional controlled local failure/restart checks. Run only after kubernetes.py up."""
from pathlib import Path
import importlib.util,json,subprocess,time,urllib.request,hashlib
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('housing_kube',ROOT/'scripts/kubernetes.py');k=importlib.util.module_from_spec(spec);spec.loader.exec_module(k)
report={'scope':'Dedicated local kind cluster only','checks':{},'errors':[]}
def query(*args):return k.kubectl('-n',k.NAMESPACE,*args,capture=True).stdout
# Caller loads final image and invokes up first.
fwd=subprocess.Popen(['kubectl','--kubeconfig',str(k.KUBECONFIG),'--context','kind-'+k.CLUSTER,'-n',k.NAMESPACE,'port-forward','--address','127.0.0.1','service/dashboard','18087:8080'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def get(path):
    with urllib.request.urlopen('http://127.0.0.1:18087'+path,timeout=8) as response:return json.load(response)
def waitapi():
    for _ in range(50):
        try:return get('/api/housing')
        except Exception:time.sleep(1)
    raise RuntimeError('Kubernetes API unavailable')
try:
    before=waitapi();published=json.loads((ROOT/'web/data/housing.json').read_text())
    assert before['annual']==published['annual'];report['checks']['api_matches_all145_published_rows']=True
    assert get('/health/ready')['status']=='ready';report['checks']['readiness']=True
    cron=json.loads(query('get','cronjob','annual-source-check','-o','json'));assert cron['spec']['suspend'] is True;report['checks']['schedule_suspended']=True
    name='controlled-invalid-'+str(int(time.time()))
    job=json.loads(query('create','job',name,'--from=cronjob/annual-source-check','--dry-run=client','-o','json'))
    container=job['spec']['template']['spec']['containers'][0]
    container['command']=['python','-c',"from utah_housing.warehouse import load_bytes;load_bytes(b'controlled-invalid-source',2025,'fixture://kubernetes-rejection-proof')"]
    container.pop('args',None)
    k.kubectl('apply','-f','-',input_text=json.dumps(job))
    k.kubectl('-n',k.NAMESPACE,'wait','--for=condition=failed','job/'+name,'--timeout=180s')
    failed=json.loads(query('get','job',name,'-o','json'))
    assert failed['status']['failed']==2
    after=get('/api/housing');assert after['annual']==before['annual']
    runs=get('/api/runs');report['checks']['controlled_invalid_job_retried_then_failed_without_data_change']=True
    report['invalid_job']={'name':name,'failed_attempts':failed['status']['failed']}
    good='verified-retry-'+str(int(time.time()))
    query('create','job',good,'--from=cronjob/annual-source-check')
    query('wait','--for=condition=complete','job/'+good,'--timeout=240s')
    assert get('/api/housing')['annual']==before['annual'];report['checks']['corrected_refresh_completed_without_duplicate_rows']=True
    oldpod=json.loads(query('get','pods','-l','app=housing-warehouse','-o','json'))['items'][0]['metadata']['uid']
    query('rollout','restart','deployment/warehouse');query('rollout','status','deployment/warehouse','--timeout=180s')
    newpod=json.loads(query('get','pods','-l','app=housing-warehouse','-o','json'))['items'][0]['metadata']['uid'];assert newpod!=oldpod
    # Recover query after PostgreSQL readiness.
    assert waitapi()['annual']==before['annual'];report['checks']['postgres_pod_replacement_preserved145_rows_on_pvc']=True
    query('rollout','restart','deployment/dashboard');query('rollout','status','deployment/dashboard','--timeout=180s')
    fwd.terminate();fwd.wait(timeout=5)
    fwd=subprocess.Popen(['kubectl','--kubeconfig',str(k.KUBECONFIG),'--context','kind-'+k.CLUSTER,'-n',k.NAMESPACE,'port-forward','--address','127.0.0.1','service/dashboard','18087:8080'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    assert waitapi()['annual']==before['annual'];report['checks']['dashboard_restart_preserved_api']=True
    image=query('get','pods','-l','app=housing-dashboard','-o','json');pod=json.loads(image)['items'][0]
    report['application_image_id']=pod['status']['containerStatuses'][0]['imageID']
    report['runtime_warehouse_sha256']=query('exec','deployment/dashboard','--','python','-c',"import hashlib,utah_housing.warehouse as w;print(hashlib.sha256(open(w.__file__,'rb').read()).hexdigest())").strip()
    report['checks']['final_runtime_matches_local_source']=report['runtime_warehouse_sha256']==hashlib.sha256((ROOT/'src/utah_housing/warehouse.py').read_bytes()).hexdigest()
    package_hashes=json.loads(query('exec','deployment/dashboard','--','python','-c',"import pathlib,hashlib,json,utah_housing; r=pathlib.Path(utah_housing.__file__).parent;print(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in r.glob('*') if p.is_file()}))"))
    local_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'src/utah_housing').glob('*') if p.is_file()}
    report['checks']['all_package_files_match_final_source']=package_hashes==local_hashes
    report['package_files']=package_hashes
    assert all(report['checks'].values());report['status']='passed'
except Exception as exc:
    report['status']='failed';report['errors'].append(str(exc));raise
finally:
    fwd.terminate();fwd.wait(timeout=5)
    (ROOT/'docs/verification/kubernetes.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

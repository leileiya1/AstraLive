import argparse,csv,datetime,pathlib,subprocess,time,psutil
ap=argparse.ArgumentParser();ap.add_argument('--pid',type=int,required=True);ap.add_argument('--label',required=True);args=ap.parse_args()
dest=pathlib.Path('/root/autodl-tmp/astralive-avatar-lab/benchmarks/gpu-metrics.csv')
header=['utc','label','pid','gpu_name','gpu_util_percent','gpu_used_mib','gpu_total_mib','gpu_temp_c','gpu_power_w','process_cpu_percent','process_rss_bytes','host_available_ram_bytes']
p=psutil.Process(args.pid);p.cpu_percent()
with dest.open('a') as f:
    w=csv.writer(f)
    if f.tell()==0:w.writerow(header)
    while p.is_running() and p.status()!=psutil.STATUS_ZOMBIE:
        gpu=subprocess.check_output(['nvidia-smi','--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw','--format=csv,noheader,nounits'],text=True).strip().split(', ')
        try:w.writerow([datetime.datetime.now(datetime.timezone.utc).isoformat(),args.label,args.pid,*gpu,p.cpu_percent(),p.memory_info().rss,psutil.virtual_memory().available]);f.flush()
        except psutil.NoSuchProcess:break
        time.sleep(1)

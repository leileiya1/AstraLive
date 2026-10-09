import json,os,pathlib,sys,time
import torch,flash_attn,mediapipe
L=pathlib.Path('/root/autodl-tmp/astralive-avatar-lab');R=L/'repositories/SoulX-FlashHead'
os.chdir(R);sys.path.insert(0,str(R))
from flash_head.inference import get_pipeline
from flash_head.ltx_video.ltx_vae import LtxVAE
q=torch.randn(1,128,8,64,device='cuda',dtype=torch.bfloat16)
with torch.no_grad():
    out=flash_attn.flash_attn_func(q,q,q);torch.cuda.synchronize()
    assert torch.isfinite(out).all()
d=dict(torch=torch.__version__,torch_cuda=torch.version.cuda,python=sys.version,flash_attention=flash_attn.__version__,mediapipe=mediapipe.__version__,device=torch.cuda.get_device_name(0),capability=torch.cuda.get_device_capability(0),cxx11_abi=torch._C._GLIBCXX_USE_CXX11_ABI,imports='PASS',cuda_flash_attention='PASS')
(L/'reports/soulx-install-validation.json').write_text(json.dumps(d,indent=2));print(json.dumps(d,indent=2))

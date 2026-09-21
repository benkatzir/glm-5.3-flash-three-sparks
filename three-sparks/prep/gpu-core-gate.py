import torch
import vllm._C_stable_libtorch
import vllm._flashkda_C
import cuda_exl3._C
from vllm.platforms import current_platform
from vllm import _custom_ops as ops

assert current_platform.is_cuda()
print('Stable CUDA libraries imported', flush=True)
x = ((torch.arange(8192, device='cuda', dtype=torch.float32).reshape(2, 4096) % 97) - 48).div(16).to(torch.bfloat16)
w = torch.ones(4096, device='cuda', dtype=torch.bfloat16)
y = torch.empty_like(x)
ops.rms_norm(y, x, w, 1e-6)
ref = (x.float() * torch.rsqrt(x.float().square().mean(-1, keepdim=True) + 1e-6)).to(x.dtype)
torch.cuda.synchronize()
torch.testing.assert_close(y, ref, rtol=0.01, atol=0.01)
print('CUDA stable RMSNorm PASS', float((y.float()-ref.float()).abs().max()), flush=True)

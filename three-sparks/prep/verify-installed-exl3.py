"""CPU import/payload check after installing the already compiled wheel."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import torch
import cuda_exl3
import cuda_exl3._C
import vllm

package = Path(cuda_exl3.__file__).resolve().parent
expected_package = Path('/usr/local/lib/python3.12/dist-packages/cuda_exl3')
assert package == expected_package, (package, expected_package)
for source in Path('/opt/cuda-exl3/src/cuda_exl3').glob('*.py'):
    assert (package/source.name).read_bytes() == source.read_bytes(), source.name
entries = importlib.metadata.distribution('cuda-exl3').entry_points
assert any(x.group == 'vllm.general_plugins' and x.name == 'cuda_exl3' and x.value == 'cuda_exl3:register' for x in entries)
assert hasattr(torch.ops.cuda_exl3_C, 'exl3_linear'), 'Native Torch operator missing'
print(json.dumps({'cuda_exl3': cuda_exl3.__version__, 'vllm': vllm.__version__, 'torch': torch.__version__, 'installed_package': str(package), 'extension_sha256': hashlib.sha256(Path(cuda_exl3._C.__file__).read_bytes()).hexdigest()}))

"""阅读已下载 wheel 的元数据，不执行 wheel 中的代码。"""
from pathlib import Path
from zipfile import ZipFile

wheels = sorted(Path(__file__).parent.glob("weaviate_client*.whl"))
assert wheels, "没有 weaviate-client wheel"
path = wheels[-1]
with ZipFile(path) as archive:
    metadata = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
    text = archive.read(metadata).decode("utf-8", errors="replace")
print("wheel=", path.name)
for line in text.splitlines():
    if line.startswith(("Requires-Python:", "Requires-Dist: grpcio", "Requires-Dist: protobuf")):
        print(line)

"""验证增强依赖的实际发行版、关键导入和 pip 清单上下文。"""
from __future__ import annotations

import importlib
import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
GROUPS: dict[str, list[str]] = {
    "基础": ["numpy", "Pillow", "pydantic", "pydantic_core", "PyYAML", "regex", "sqlalchemy", "psutil", "setuptools", "wrapt"],
    "http_async": ["httpx", "urllib3", "websockets", "multidict", "yarl", "h11", "propcache"],
    "序列化": ["orjson", "msgpack", "jsonschema", "jsonschema-spec", "rpds-py", "xxhash", "zstandard", "markupsafe"],
    "文档": ["lxml", "pdfminer.six", "reportlab", "xhtml2pdf", "text-unidecode", "tiktoken", "tokenizers", "tree-sitter", "tree-sitter-languages"],
    "AI_LLM": ["openai", "litellm", "langchain", "langchain-core", "langchain-community", "langchain-openai", "langgraph", "langgraph-checkpoint", "langgraph-prebuilt"],
    "可观测性": ["opentelemetry-api", "opentelemetry-sdk", "opentelemetry-exporter-otlp", "opentelemetry-exporter-otlp-proto-grpc", "opentelemetry-exporter-otlp-proto-http", "sentry-sdk"],
    "database": ["TinyMongo", "weaviate-client"],
    "grpc_protobuf": ["grpcio", "protobuf"],
    "开发辅助": ["watchfiles", "anyio"],
}
IMPORTS: dict[str, str] = {
    "numpy": "numpy", "Pillow": "PIL", "pydantic_core": "pydantic_core",
    "PyYAML": "yaml", "jsonschema-spec": "jsonschema_spec",
    "rpds-py": "rpds", "msgpack": "msgpack", "wrapt": "wrapt",
    "multidict": "multidict", "yarl": "yarl", "h11": "h11", "propcache": "propcache",
    "orjson": "orjson", "xxhash": "xxhash", "zstandard": "zstandard", "markupsafe": "markupsafe",
    "lxml": "lxml", "pdfminer.six": "pdfminer", "reportlab": "reportlab",
    "xhtml2pdf": "xhtml2pdf", "text-unidecode": "text_unidecode",
    "tiktoken": "tiktoken", "tokenizers": "tokenizers",
    "tree-sitter": "tree_sitter", "tree-sitter-languages": "tree_sitter_languages",
    "openai": "openai", "litellm": "litellm", "langchain": "langchain",
    "langchain-core": "langchain_core", "langchain-community": "langchain_community",
    "langchain-openai": "langchain_openai", "langgraph": "langgraph",
    "langgraph-checkpoint": "langgraph.checkpoint", "langgraph-prebuilt": "langgraph.prebuilt",
    "opentelemetry-api": "opentelemetry", "opentelemetry-sdk": "opentelemetry.sdk",
    "opentelemetry-exporter-otlp": "opentelemetry.exporter.otlp.proto.grpc",
    "opentelemetry-exporter-otlp-proto-grpc": "opentelemetry.exporter.otlp.proto.grpc",
    "opentelemetry-exporter-otlp-proto-http": "opentelemetry.exporter.otlp.proto.http",
    "sentry-sdk": "sentry_sdk", "TinyMongo": "tinymongo", "weaviate-client": "weaviate",
    "grpcio": "grpc", "protobuf": "google.protobuf", "watchfiles": "watchfiles", "anyio": "anyio",
    "jsonschema": "jsonschema", "sqlalchemy": "sqlalchemy", "httpx": "httpx",
    "urllib3": "urllib3", "websockets": "websockets", "psutil": "psutil",
}


def version_of(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "NOT_INSTALLED"


def main() -> int:
    groups = []
    for kind, packages in GROUPS.items():
        rows = [{"distribution": name, "version": version_of(name)} for name in packages]
        groups.append({"group": kind, "packages": rows})
    complete_roots = []
    for kind, packages in GROUPS.items():
        for name in packages:
            if version_of(name) == "NOT_INSTALLED":
                complete_roots.append(name)
    imports = []
    for name, module in IMPORTS.items():
        if version_of(name) == "NOT_INSTALLED":
            imports.append({"package": name, "module": module, "ok": True, "status": "SKIPPED_NOT_INSTALLED"})
            continue
        try:
            obj = importlib.import_module(module)
            imports.append({"package": name, "module": module, "ok": True,
                            "status": "IMPORTED", "type": type(obj).__name__})
        except Exception as exc:
            # 记录真实失败，不使用标志掩盖 DLL/ABI/依赖缺失。
            imports.append({"package": name, "module": module, "ok": False,
                            "error_type": type(exc).__name__, "detail": str(exc)[:600]})
    failed = [row for row in imports if not row["ok"]]
    try:
        language = importlib.import_module("tree_sitter_languages").get_language("python")
        native = {"ok": True, "type": type(language).__name__,
                  "operation": "tree_sitter_languages.get_language('python')"}
    except Exception as exc:
        native = {"ok": False, "operation": "tree_sitter_languages.get_language('python')",
                  "error_type": type(exc).__name__, "detail": str(exc)[:600]}
    check = subprocess.run(
        [sys.executable, "-I", "-m", "pip", "check"], cwd=PROJECT,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    pip_check = {"ok": check.returncode == 0,
                 "stdout": check.stdout[-10000:], "stderr": check.stderr[-6000:]}
    report = {
        "python": {"executable": sys.executable, "version": sys.version.split()[0]},
        "groups": groups,
        "missing_distributions": complete_roots,
        "imports": imports,
        "import_failures": failed,
        "pip_check": pip_check,
        "native_binding": native,
        "fully_verified": not complete_roots and not failed and native["ok"] and pip_check["ok"],
    }
    output = PROJECT / "review_bundle" / "dependency_probes" / "verification.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"missing_distributions": complete_roots,
                      "import_failures": failed, "fully_verified": report["fully_verified"]},
                     ensure_ascii=False, indent=2))
    return 0 if report["fully_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
